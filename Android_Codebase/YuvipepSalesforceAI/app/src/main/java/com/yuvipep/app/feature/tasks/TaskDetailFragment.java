package com.yuvipep.app.feature.tasks;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.google.android.material.chip.Chip;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.snackbar.Snackbar;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.ProjectDetailDto;
import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.core.net.dto.TaskResponses;
import com.yuvipep.app.databinding.FragmentTaskDetailBinding;
import com.yuvipep.app.feature.assistant.WhySheet;
import com.yuvipep.app.feature.leads.LeadStates;
import com.yuvipep.app.feature.projects.ProjectsRepository;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Task detail (03 §7): the full lifecycle in one screen — complete, decline,
 * block/unblock, new date, split, vendor promise/slip, progress. Reached
 * with a projectId when known (My Tasks resolves it while aggregating, the
 * project Tasks tab always has it); without one, the screen still works but
 * honestly narrows what it can show (11 §6e).
 */
@AndroidEntryPoint
public class TaskDetailFragment extends Fragment {

    private static final String ARG_PROJECT = "project_id";
    private static final String ARG_TASK = "task_id";

    public static TaskDetailFragment create(@Nullable String projectId, @NonNull String taskId) {
        TaskDetailFragment fragment = new TaskDetailFragment();
        Bundle args = new Bundle();
        args.putString(ARG_PROJECT, projectId);
        args.putString(ARG_TASK, taskId);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject TasksRepository repository;
    @Inject ProjectsRepository projectsRepository;
    @Inject TokenStore tokenStore;

    private FragmentTaskDetailBinding binding;
    private String projectId;
    private String taskId;
    private TaskDto task;
    private final Map<String, String> taskTitlesById = new HashMap<>();
    @Nullable private List<ProjectDetailDto.Commitment> commitments;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentTaskDetailBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        projectId = requireArguments().getString(ARG_PROJECT);
        taskId = requireArguments().getString(ARG_TASK, "");
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
    }

    @Override
    public void onResume() {
        super.onResume();
        load();
    }

    private void load() {
        if (binding == null) return;
        binding.stateView.showLoading();
        if (projectId != null) {
            projectsRepository.detail(projectId, result -> {
                if (binding == null) return;
                if (result.isSuccess() && result.data != null) {
                    ProjectDetailDto project = result.data;
                    commitments = project.commitments;
                    taskTitlesById.clear();
                    TaskDto found = null;
                    if (project.tasks != null) {
                        for (TaskDto t : project.tasks) {
                            taskTitlesById.put(t.id, t.title);
                            if (t.id.equals(taskId)) found = t;
                        }
                    }
                    if (found == null) {
                        binding.stateView.showError(getString(R.string.task_detail_title)
                                + " — not found", this::load);
                        return;
                    }
                    found.projectId = project.id;
                    found.projectName = project.name;
                    found.rich = true;
                    task = found;
                    enrichThenRender(task.assigneeId);
                } else if (result.error != null) {
                    binding.stateView.showError(result.error.message, this::load);
                }
            });
        } else {
            repository.actionItemsForOwner("me", result -> {
                if (binding == null) return;
                if (result.isSuccess() && result.data != null) {
                    for (TaskDto t : result.data) {
                        if (t.id.equals(taskId)) {
                            t.rich = false;
                            task = t;
                        }
                    }
                    if (task == null) {
                        binding.stateView.showError(getString(R.string.task_detail_title)
                                + " — not found", this::load);
                        return;
                    }
                    render();
                } else if (result.error != null) {
                    binding.stateView.showError(result.error.message, this::load);
                }
            });
        }
    }

    /** Backfill description/result_note/completed_at from /action-items —
     * available regardless of how the task was reached (11 §6e). */
    private void enrichThenRender(@Nullable String ownerId) {
        if (ownerId == null) {
            render();
            return;
        }
        repository.actionItemsForOwner(ownerId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                for (TaskDto t : result.data) {
                    if (t.id.equals(taskId)) {
                        task.description = t.description;
                        task.resultNote = t.resultNote;
                        task.completedAt = t.completedAt;
                        task.createdAt = t.createdAt;
                        task.assigneeName = t.assigneeName;
                        if (task.leadName == null) task.leadName = t.leadName;
                        break;
                    }
                }
            }
            render();
        });
    }

    private void render() {
        if (binding == null || task == null) return;
        binding.stateView.hide();
        binding.taskTitle.setText(task.title);

        StringBuilder meta = new StringBuilder(LeadStates.label(task.status));
        if (task.priority != null) meta.append(" · ").append(task.priority);
        if (task.phase != null) meta.append(" · ").append(LeadStates.label(task.phase));
        if (task.dueDate != null) {
            meta.append(" · due ").append(
                    com.yuvipep.app.core.util.Times.dateLabel(task.dueDate));
        }
        if (task.assigneeName != null) meta.append(" · ").append(task.assigneeName);
        binding.taskMeta.setText(meta);

        if (task.blocked) {
            binding.taskBlockedBanner.setText(getString(R.string.task_blocked_prefix,
                    task.blockedReason == null ? "" : task.blockedReason));
            binding.taskBlockedBanner.setVisibility(View.VISIBLE);
        } else {
            binding.taskBlockedBanner.setVisibility(View.GONE);
        }

        bindOptional(binding.taskDescription, task.description);

        if (task.assignmentReason != null && !task.assignmentReason.isEmpty()) {
            binding.reasonRow.setVisibility(View.VISIBLE);
            binding.reasonText.setText(getString(R.string.task_assigned_reason)
                    + ": " + task.assignmentReason);
            binding.reasonWhyButton.setOnClickListener(v ->
                    WhySheet.open(getParentFragmentManager(), "action_item", task.id));
        } else {
            binding.reasonRow.setVisibility(View.GONE);
        }

        String commitmentText = null;
        if (task.clientCommitmentId != null && commitments != null) {
            for (ProjectDetailDto.Commitment c : commitments) {
                if (c.id.equals(task.clientCommitmentId)) {
                    commitmentText = getString(R.string.task_commitment_linked) + ": " + c.text;
                    break;
                }
            }
        }
        bindOptional(binding.commitmentText, commitmentText);

        renderDependencies();

        binding.progressSeek.setProgress(task.progressPercent == null ? 0 : task.progressPercent);
        binding.progressValue.setText(
                (task.progressPercent == null ? 0 : task.progressPercent) + "%");
        binding.progressSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                binding.progressValue.setText(progress + "%");
            }

            @Override public void onStartTrackingTouch(SeekBar seekBar) { }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                repository.progress(task.id, seekBar.getProgress(), null, result -> {
                    if (binding == null) return;
                    if (result.isSuccess()) {
                        task.progressPercent = seekBar.getProgress();
                        Snackbar.make(binding.getRoot(), R.string.task_progress_success,
                                Snackbar.LENGTH_SHORT).show();
                    } else if (result.error != null) {
                        Snackbar.make(binding.getRoot(), result.error.message,
                                Snackbar.LENGTH_LONG).show();
                    }
                });
            }
        });

        binding.limitedDetailNote.setVisibility(task.rich ? View.GONE : View.VISIBLE);

        renderActions();
    }

    private void renderDependencies() {
        binding.dependenciesContainer.removeAllViews();
        List<String> ids = task.dependsOnIds;
        boolean has = ids != null && !ids.isEmpty();
        binding.dependenciesLabel.setVisibility(has ? View.VISIBLE : View.GONE);
        if (!has) return;
        for (String id : ids) {
            String title = taskTitlesById.get(id);
            TextView row = new TextView(requireContext());
            int vpad = (int) (4 * getResources().getDisplayMetrics().density);
            row.setPadding(0, vpad, 0, vpad);
            if (title != null) {
                row.setText(getString(R.string.task_dependency_row, title));
                final String depId = id;
                row.setOnClickListener(v -> {
                    if (getActivity() instanceof com.yuvipep.app.MainActivity) {
                        ((com.yuvipep.app.MainActivity) getActivity()).push(
                                TaskDetailFragment.create(projectId, depId));
                    }
                });
            } else {
                row.setText(R.string.task_dependency_outside_project);
            }
            binding.dependenciesContainer.addView(row);
        }
    }

    private void renderActions() {
        binding.actionsGroup.removeAllViews();
        boolean isAssignee = task.assigneeId != null
                && task.assigneeId.equals(tokenStore.getUserId());
        boolean done = "done".equals(task.status);

        // Finding F51: this screen computed isAssignee and spent it on exactly one
        // chip. Everything else was offered to everybody, and the server agreed —
        // a non-assignee blocked another user's task through this very screen.
        // The server now enforces ownership, so the chips have to mirror it or we
        // would be inviting a tap that is refused: the opposite of this app's
        // honest-refusal pattern.
        //
        // Same rule as the backend's can_reassign_task: agents act on their own
        // work, leads and admins act across the team. An UNASSIGNED task stays
        // open to anyone, exactly as the server allows.
        String role = tokenStore.getRole();
        boolean actsForTeam = RoleGate.SALES_LEAD.equals(role)
                || RoleGate.OPERATIONS_LEAD.equals(role)
                || RoleGate.ORG_ADMIN.equals(role);
        boolean canManage = isAssignee || actsForTeam || task.assigneeId == null;

        if (!done) {
            // Done and Progress stay open to everyone by decision: covering for a
            // colleague who finished the work is teamwork, not an escalation.
            binding.actionsGroup.addView(actionChip(R.string.task_action_done, this::doneDialog));
        }
        if (isAssignee && !done) {
            binding.actionsGroup.addView(
                    actionChip(R.string.task_action_decline, this::declineDialog));
        }
        if (!done && canManage) {
            if (task.blocked) {
                binding.actionsGroup.addView(
                        actionChip(R.string.task_action_unblock, this::unblock));
            } else {
                binding.actionsGroup.addView(
                        actionChip(R.string.task_action_block, this::blockDialog));
            }
            binding.actionsGroup.addView(
                    actionChip(R.string.task_action_new_date, this::newDateDialog));
            binding.actionsGroup.addView(actionChip(R.string.task_action_split, this::splitDialog));
            binding.actionsGroup.addView(
                    actionChip(R.string.task_action_vendor_promise, this::vendorPromiseDialog));
            binding.actionsGroup.addView(
                    actionChip(R.string.task_action_vendor_slip, this::vendorSlipDialog));
        }
    }

    private Chip actionChip(int labelRes, @NonNull Runnable action) {
        Chip chip = new Chip(requireContext(), null,
                com.google.android.material.R.attr.chipStyle);
        chip.setText(labelRes);
        chip.setCheckable(false);
        chip.setOnClickListener(v -> action.run());
        return chip;
    }

    // ── Actions ──────────────────────────────────────────────────────

    private void doneDialog() {
        EditText input = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        input.setHint(R.string.task_done_note_hint);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.task_done_title)
                .setView(pad(input))
                .setPositiveButton(R.string.task_action_done, (d, w) ->
                        repository.complete(task.id, emptyToNull(input.getText().toString()),
                                result -> {
                                    if (binding == null) return;
                                    if (result.isSuccess() && result.data != null) {
                                        task.status = "done";
                                        Snackbar.make(binding.getRoot(),
                                                Boolean.TRUE.equals(result.data.alreadyDone)
                                                        ? getString(R.string.task_already_done)
                                                        : getString(R.string.task_done_success),
                                                Snackbar.LENGTH_SHORT).show();
                                        render();
                                    } else if (result.error != null) {
                                        Snackbar.make(binding.getRoot(), result.error.message,
                                                Snackbar.LENGTH_LONG).show();
                                    }
                                }))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void declineDialog() {
        String[] reasons = {"busy", "wrong_skill", "on_site_elsewhere", "other"};
        String[] labels = {
                getString(R.string.task_decline_reason_busy),
                getString(R.string.task_decline_reason_wrong_skill),
                getString(R.string.task_decline_reason_on_site_elsewhere),
                getString(R.string.task_decline_reason_other),
        };
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.task_decline_title)
                .setItems(labels, (d, which) -> declineNoteDialog(reasons[which]))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void declineNoteDialog(@NonNull String reason) {
        EditText input = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        input.setHint(R.string.task_decline_note_hint);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.task_decline_title)
                .setView(pad(input))
                .setPositiveButton(R.string.task_action_decline, (d, w) ->
                        repository.decline(task.id, reason, emptyToNull(input.getText().toString()),
                                result -> {
                                    if (binding == null) return;
                                    if (result.isSuccess() && result.data != null) {
                                        TaskResponses.Decline r = result.data;
                                        String outcome = r.needsLead
                                                ? getString(R.string.task_decline_needs_lead)
                                                : getString(R.string.task_decline_reassigned);
                                        Snackbar.make(binding.getRoot(),
                                                getString(R.string.task_decline_success, outcome),
                                                Snackbar.LENGTH_LONG).show();
                                        load();
                                    } else if (result.error != null) {
                                        Snackbar.make(binding.getRoot(), result.error.message,
                                                Snackbar.LENGTH_LONG).show();
                                    }
                                }))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void blockDialog() {
        EditText input = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        input.setHint(R.string.task_block_reason_hint);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.task_block_title)
                .setView(pad(input))
                .setPositiveButton(R.string.task_action_block, (d, w) -> {
                    String reason = input.getText().toString().trim();
                    if (reason.length() < 2) return;
                    repository.block(task.id, reason, result -> {
                        if (binding == null) return;
                        if (result.isSuccess()) {
                            task.blocked = true;
                            task.blockedReason = reason;
                            // Say who was told, when the server found a colleague
                            // in the reason (customer ask, 21 Sep 2026).
                            String told = com.yuvipep.app.feature.home.WaitingOnYou
                                    .blockedOnName(result.data);
                            Snackbar.make(binding.getRoot(), told != null
                                            ? getString(R.string.task_blocked_told, told)
                                            : getString(R.string.task_blocked_success),
                                    Snackbar.LENGTH_LONG).show();
                            render();
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void unblock() {
        repository.unblock(task.id, result -> {
            if (binding == null) return;
            if (result.isSuccess()) {
                task.blocked = false;
                task.blockedReason = null;
                Snackbar.make(binding.getRoot(), R.string.task_unblocked_success,
                        Snackbar.LENGTH_SHORT).show();
                render();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message, Snackbar.LENGTH_LONG).show();
            }
        });
    }

    private void newDateDialog() {
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);

        TextView dateLabel = new TextView(requireContext());
        dateLabel.setText(R.string.task_pick_date_hint);
        java.util.Calendar cal = java.util.Calendar.getInstance();
        String[] chosen = {null};
        dateLabel.setOnClickListener(v -> new android.app.DatePickerDialog(requireContext(),
                (view, year, month, day) -> {
                    chosen[0] = String.format(java.util.Locale.US, "%04d-%02d-%02d",
                            year, month + 1, day);
                    dateLabel.setText(chosen[0]);
                }, cal.get(java.util.Calendar.YEAR), cal.get(java.util.Calendar.MONTH),
                cal.get(java.util.Calendar.DAY_OF_MONTH)).show());
        wrapper.addView(dateLabel);

        EditText reason = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        reason.setHint(R.string.task_new_date_reason_hint);
        wrapper.addView(reason);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.task_new_date_title)
                .setView(wrapper)
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    if (chosen[0] == null) return;
                    repository.newDate(task.id, chosen[0] + "T00:00:00",
                            emptyToNull(reason.getText().toString()), result -> {
                                if (binding == null) return;
                                if (result.isSuccess() && result.data != null) {
                                    if (result.data.accepted) {
                                        task.dueDate = chosen[0] + "T00:00:00";
                                        Snackbar.make(binding.getRoot(),
                                                R.string.task_new_date_accepted,
                                                Snackbar.LENGTH_SHORT).show();
                                    } else {
                                        String breaks = result.data.breaks == null ? ""
                                                : String.join("; ", result.data.breaks);
                                        Snackbar.make(binding.getRoot(),
                                                getString(R.string.task_new_date_routed, breaks),
                                                Snackbar.LENGTH_LONG).show();
                                    }
                                    render();
                                } else if (result.error != null) {
                                    Snackbar.make(binding.getRoot(), result.error.message,
                                            Snackbar.LENGTH_LONG).show();
                                }
                            });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void splitDialog() {
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);

        EditText part1 = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        part1.setHint(getString(R.string.task_split_part_hint, 1));
        wrapper.addView(part1);
        EditText part2 = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        part2.setHint(getString(R.string.task_split_part_hint, 2));
        wrapper.addView(part2);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.task_split_title)
                .setView(wrapper)
                .setPositiveButton(R.string.task_action_split, (d, w) -> {
                    String t1 = part1.getText().toString().trim();
                    String t2 = part2.getText().toString().trim();
                    if (t1.isEmpty() || t2.isEmpty()) return;
                    List<Map<String, Object>> parts = new ArrayList<>();
                    Map<String, Object> p1 = new HashMap<>();
                    p1.put("title", t1);
                    Map<String, Object> p2 = new HashMap<>();
                    p2.put("title", t2);
                    parts.add(p1);
                    parts.add(p2);
                    repository.split(task.id, parts, result -> {
                        if (binding == null) return;
                        if (result.isSuccess() && result.data != null) {
                            Snackbar.make(binding.getRoot(),
                                    getString(R.string.task_split_success,
                                            result.data.children.size()),
                                    Snackbar.LENGTH_LONG).show();
                            requireActivity().getOnBackPressedDispatcher().onBackPressed();
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void vendorPromiseDialog() {
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);

        EditText vendorName = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        vendorName.setHint(R.string.task_vendor_name_hint);
        wrapper.addView(vendorName);
        EditText date = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        date.setHint(R.string.task_vendor_date_hint);
        wrapper.addView(date);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.task_vendor_promise_title)
                .setView(wrapper)
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    String name = vendorName.getText().toString().trim();
                    String isoDate = date.getText().toString().trim();
                    if (name.isEmpty() || isoDate.isEmpty()) return;
                    repository.vendorPromise(task.id, name, isoDate + "T00:00:00", result -> {
                        if (binding == null) return;
                        if (result.isSuccess()) {
                            Snackbar.make(binding.getRoot(), R.string.task_vendor_promise_success,
                                    Snackbar.LENGTH_SHORT).show();
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void vendorSlipDialog() {
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);

        EditText date = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        date.setHint(R.string.task_vendor_date_hint);
        wrapper.addView(date);
        EditText note = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        note.setHint(R.string.task_decline_note_hint);
        wrapper.addView(note);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.task_vendor_slip_title)
                .setView(wrapper)
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    String isoDate = date.getText().toString().trim();
                    if (isoDate.isEmpty()) return;
                    repository.vendorSlip(task.id, isoDate + "T00:00:00",
                            emptyToNull(note.getText().toString()), result -> {
                                if (binding == null) return;
                                if (result.isSuccess()) {
                                    Snackbar.make(binding.getRoot(),
                                            R.string.task_vendor_slip_success,
                                            Snackbar.LENGTH_SHORT).show();
                                } else if (result.error != null) {
                                    Snackbar.make(binding.getRoot(), result.error.message,
                                            Snackbar.LENGTH_LONG).show();
                                }
                            });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    // ── Helpers ──────────────────────────────────────────────────────

    private static void bindOptional(@NonNull TextView view, @Nullable String value) {
        if (value == null || value.isEmpty()) {
            view.setVisibility(View.GONE);
        } else {
            view.setText(value);
            view.setVisibility(View.VISIBLE);
        }
    }

    @Nullable
    private static String emptyToNull(@Nullable String value) {
        return value == null || value.trim().isEmpty() ? null : value.trim();
    }

    private View pad(@NonNull View view) {
        LinearLayout wrapper = new LinearLayout(requireContext());
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);
        wrapper.addView(view, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return wrapper;
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
