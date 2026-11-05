package com.yuvipep.app.feature.projects;

import android.content.res.ColorStateList;
import android.os.Bundle;
import android.text.method.ScrollingMovementMethod;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.chip.Chip;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.snackbar.Snackbar;
import com.google.android.material.tabs.TabLayout;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.ConflictDto;
import com.yuvipep.app.core.net.dto.ContactDto;
import com.yuvipep.app.core.net.dto.DraftMessageResponse;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.net.dto.MessageRequests;
import com.yuvipep.app.core.net.dto.OrgUserDto;
import com.yuvipep.app.core.net.dto.PlanVersionDto;
import com.yuvipep.app.core.net.dto.ProjectDetailDto;
import com.yuvipep.app.core.net.dto.ProjectRequests;
import com.yuvipep.app.core.net.dto.ProjectResponses;
import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.core.net.dto.TimelineEventDto;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentProjectDetailBinding;
import com.yuvipep.app.feature.assistant.Pretty;
import com.yuvipep.app.feature.assistant.WhySheet;
import com.yuvipep.app.feature.home.WorkflowRepository;
import com.yuvipep.app.feature.leads.ConsentSheet;
import com.yuvipep.app.feature.leads.LeadStates;
import com.yuvipep.app.feature.leads.LeadsRepository;
import com.yuvipep.app.feature.leads.RowAdapter;
import com.yuvipep.app.feature.meetings.RecorderFragment;
import com.yuvipep.app.feature.tasks.TaskDetailFragment;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Project home + its 7 tabs (03 §6): overview (health, what's-blocking,
 * next tasks, commitments, quick actions), plan (version diff), tasks
 * (grouped by phase), timeline, people (stakeholders + provenance via
 * WhySheet), team (members), conflicts (resolve inline), reports (weekly
 * digest preview). One generic row list, same pattern as LeadDetailFragment.
 */
@AndroidEntryPoint
public class ProjectDetailFragment extends Fragment {

    private static final String ARG_PROJECT = "project_id";
    private static final String ARG_INITIAL_TAB = "initial_tab";

    private static final int TAB_OVERVIEW = 0;
    private static final int TAB_PLAN = 1;
    private static final int TAB_TASKS = 2;
    private static final int TAB_TIMELINE = 3;
    private static final int TAB_PEOPLE = 4;
    private static final int TAB_TEAM = 5;
    private static final int TAB_CONFLICTS = 6;
    private static final int TAB_REPORTS = 7;

    private static final String[] PHASE_ORDER = {
            "sales", "proposal", "preparation", "delivery", "payment", "closure",
    };

    public static ProjectDetailFragment create(@NonNull String projectId) {
        return create(projectId, -1);
    }

    /**
     * F58: open the project on a specific tab. A conflict notification's screen
     * is the Conflicts tab — which has existed and worked since Act 11, while
     * tapping the notification said "this opens fully in a later phase".
     *
     * @param initialTab one of TAB_*, or -1 to keep the default.
     */
    public static ProjectDetailFragment create(@NonNull String projectId, int initialTab) {
        ProjectDetailFragment fragment = new ProjectDetailFragment();
        Bundle args = new Bundle();
        args.putString(ARG_PROJECT, projectId);
        args.putInt(ARG_INITIAL_TAB, initialTab);
        fragment.setArguments(args);
        return fragment;
    }

    /** F58: which tab to land on, or -1 for the default. */
    public static int tabForEntity(@Nullable String entityType) {
        if ("conflict".equals(entityType)) return TAB_CONFLICTS;
        if ("action_plan".equals(entityType)) return TAB_PLAN;
        return -1;
    }

    @Inject ProjectsRepository repository;
    @Inject LeadsRepository leadsRepository;
    @Inject WorkflowRepository workflowRepository;
    @Inject TokenStore tokenStore;

    private FragmentProjectDetailBinding binding;
    private final RowAdapter adapter = new RowAdapter();
    private String projectId;
    private ProjectDetailDto project;
    private List<PlanVersionDto> plans;
    private List<TimelineEventDto> timeline;
    private List<ConflictDto> conflicts;
    private int currentTab = TAB_OVERVIEW;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentProjectDetailBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        projectId = requireArguments().getString(ARG_PROJECT, "");
        // F58: honour a requested tab, but only on first creation — on a
        // rotation the restored tab is the user's own last choice and wins.
        int requestedTab = requireArguments().getInt(ARG_INITIAL_TAB, -1);
        if (savedInstanceState == null && requestedTab >= 0) {
            currentTab = requestedTab;
        }
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.rowList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.rowList.setAdapter(adapter);

        String[] titles = {
                getString(R.string.project_tab_overview), getString(R.string.project_tab_plan),
                getString(R.string.project_tab_tasks), getString(R.string.project_tab_timeline),
                getString(R.string.project_tab_people), getString(R.string.project_tab_team),
                getString(R.string.project_tab_conflicts), getString(R.string.project_tab_reports),
        };
        for (String title : titles) {
            binding.tabs.addTab(binding.tabs.newTab().setText(title));
        }
        // The tab strip is rebuilt every time this view is recreated (e.g.
        // returning from a pushed Task detail screen) and defaults back to
        // position 0 — re-select whatever tab was actually open so the
        // indicator doesn't desync from the content (same class of bug as
        // the Phase-2 LeadDetail wart, fixed here instead of just noted).
        TabLayout.Tab restored = binding.tabs.getTabAt(currentTab);
        if (restored != null) restored.select();
        binding.tabs.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override
            public void onTabSelected(TabLayout.Tab tab) {
                currentTab = tab.getPosition();
                renderTab();
            }

            @Override public void onTabUnselected(TabLayout.Tab tab) { }
            @Override public void onTabReselected(TabLayout.Tab tab) { }
        });

        getParentFragmentManager().setFragmentResultListener(
                ConsentSheet.RESULT_KEY, this, (key, result) ->
                        pushFragment(RecorderFragment.create(project.leadId, project.name)));
        getParentFragmentManager().setFragmentResultListener(
                ChainWizardSheet.RESULT_KEY, this, (key, result) -> load());
    }

    @Override
    public void onResume() {
        super.onResume();
        load();
    }

    private void load() {
        if (binding == null) return;
        if (project == null) binding.stateView.showLoading();
        repository.detail(projectId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                project = result.data;
                renderHeader();
                renderQuickActions();
                renderTab();
                loadBlocking();
            } else if (result.isError() && result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    // ── Header ───────────────────────────────────────────────────────

    private void renderHeader() {
        binding.projectName.setText(project.name);
        binding.statusChip.setText(LeadStates.label(project.status));
        binding.statusChip.setBackgroundTintList(ColorStateList.valueOf(
                ContextCompat.getColor(requireContext(), R.color.md_light_outline)));
        binding.statusChip.setOnClickListener(v -> changeStatusDialog());

        binding.healthChip.setText(project.health == null
                ? getString(R.string.state_loading) : LeadStates.label(project.health));
        binding.healthChip.setBackgroundTintList(ContextCompat.getColorStateList(
                requireContext(), ProjectStates.healthColor(project.health)));
        binding.healthWhyButton.setOnClickListener(v ->
                WhySheet.open(getParentFragmentManager(), "project", projectId));

        StringBuilder meta = new StringBuilder();
        if (project.objective != null && !project.objective.isEmpty()) {
            meta.append(project.objective);
        }
        if (project.valueEstimate != null && project.valueEstimate > 0) {
            if (meta.length() > 0) meta.append(" · ");
            meta.append(com.yuvipep.app.core.util.Money.format(
                    project.valueEstimate, project.currency));
        }
        binding.projectMeta.setText(meta);
    }

    private void loadBlocking() {
        // Cap the banner height (android:maxLines) and let the text scroll inside
        // itself, so a long "what's blocking" list can never starve the weighted
        // tab-content area below the tabs.
        binding.blockingText.setMovementMethod(new ScrollingMovementMethod());
        binding.blockingText.setText(R.string.project_whats_blocking_loading);
        binding.blockingRefresh.setOnClickListener(v -> loadBlocking());
        repository.whatsBlocking(projectId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                binding.blockingText.setText(result.data.answer);
            } else if (result.error != null) {
                binding.blockingText.setText(result.error.message);
            }
        });
    }

    private void changeStatusDialog() {
        String[] labels = new String[ProjectStates.STATUSES.length];
        for (int i = 0; i < ProjectStates.STATUSES.length; i++) {
            labels[i] = LeadStates.label(ProjectStates.STATUSES[i]);
        }
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.project_change_status)
                .setItems(labels, (d, which) -> repository.setStatus(projectId,
                        ProjectStates.STATUSES[which], null, result -> {
                            if (binding == null) return;
                            if (result.isSuccess()) {
                                load();
                            } else if (result.error != null) {
                                Snackbar.make(binding.getRoot(), result.error.message,
                                        Snackbar.LENGTH_LONG).show();
                            }
                        }))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void renderQuickActions() {
        binding.quickActions.removeAllViews();
        boolean canRecord = RoleGate.has(tokenStore.getRole(), RoleGate.RECORD_MEETING);
        boolean canMessage = RoleGate.has(tokenStore.getRole(), RoleGate.SEND_MESSAGES);

        if (canRecord && project.leadId != null) {
            binding.quickActions.addView(actionChip(
                    getString(R.string.project_quick_record_meeting),
                    () -> ConsentSheet.open(getParentFragmentManager(), project.leadId)));
        }
        if (canMessage) {
            binding.quickActions.addView(actionChip(
                    getString(R.string.project_quick_draft_message), this::draftMessageFlow));
        }
        binding.quickActions.addView(actionChip(
                getString(R.string.project_quick_catch_me_up), this::catchMeUp));
        if (project.parentProjectId == null) {
            binding.quickActions.addView(actionChip(
                    getString(R.string.project_quick_split_branches),
                    () -> ChainWizardSheet.open(getParentFragmentManager(), projectId)));
        }
        String role = tokenStore.getRole();
        boolean canShiftPhase = RoleGate.OPERATIONS_LEAD.equals(role)
                || RoleGate.ORG_ADMIN.equals(role);
        if (canShiftPhase) {
            binding.quickActions.addView(actionChip(
                    getString(R.string.project_quick_phase_shift), this::phaseShiftDialog));
        }
    }

    private void phaseShiftDialog() {
        String[] phases = {"sales", "proposal", "preparation", "delivery", "payment", "closure"};
        String[] labels = new String[phases.length];
        for (int i = 0; i < phases.length; i++) labels[i] = LeadStates.label(phases[i]);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.project_quick_phase_shift)
                .setItems(labels, (d, which) -> {
                    Snackbar.make(binding.getRoot(), R.string.assistant_thinking,
                            Snackbar.LENGTH_SHORT).show();
                    repository.phaseShift(projectId, phases[which], result -> {
                        if (binding == null) return;
                        if (result.isSuccess()) {
                            Snackbar.make(binding.getRoot(), R.string.project_phase_shift_done,
                                    Snackbar.LENGTH_LONG).show();
                            load();
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private Chip actionChip(@NonNull String label, @NonNull Runnable action) {
        Chip chip = new Chip(requireContext(), null,
                com.google.android.material.R.attr.chipStyle);
        chip.setText(label);
        chip.setCheckable(false);
        chip.setOnClickListener(v -> action.run());
        return chip;
    }

    private void catchMeUp() {
        Snackbar.make(binding.getRoot(), R.string.assistant_thinking, Snackbar.LENGTH_SHORT)
                .show();
        repository.brief(projectId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                new MaterialAlertDialogBuilder(requireContext())
                        .setTitle(R.string.project_brief_title)
                        .setMessage(result.data.brief)
                        .setPositiveButton(android.R.string.ok, null)
                        .show();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message, Snackbar.LENGTH_LONG)
                        .show();
            }
        });
    }

    private void draftMessageFlow() {
        if (project.leadId == null) {
            Toast.makeText(requireContext(), R.string.project_no_lead, Toast.LENGTH_SHORT).show();
            return;
        }
        leadsRepository.detail(project.leadId, result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null) {
                    Snackbar.make(binding.getRoot(), result.error.message,
                            Snackbar.LENGTH_LONG).show();
                }
                return;
            }
            List<ContactDto> contacts = result.data.contacts;
            if (contacts == null || contacts.isEmpty()) {
                Toast.makeText(requireContext(), R.string.project_people_no_contacts,
                        Toast.LENGTH_LONG).show();
                return;
            }
            if (contacts.size() == 1) {
                draftMessageInstructionDialog(contacts.get(0));
                return;
            }
            String[] names = new String[contacts.size()];
            for (int i = 0; i < contacts.size(); i++) names[i] = contacts.get(i).name;
            new MaterialAlertDialogBuilder(requireContext())
                    .setTitle(R.string.project_people_pick_contact)
                    .setItems(names, (d, which) -> draftMessageInstructionDialog(contacts.get(which)))
                    .setNegativeButton(android.R.string.cancel, null)
                    .show();
        });
    }

    private void draftMessageInstructionDialog(@NonNull ContactDto contact) {
        EditText input = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        input.setHint(R.string.message_draft_instruction_hint);
        input.setMinLines(2);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(getString(R.string.project_quick_draft_message) + " — " + contact.name)
                .setView(pad(input))
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    MessageRequests.Draft body = new MessageRequests.Draft();
                    body.contactId = contact.id;
                    body.projectId = projectId;
                    body.instruction = input.getText().toString().trim();
                    repository.draftMessage(body, result -> {
                        if (binding == null) return;
                        if (result.isSuccess() && result.data != null) {
                            showDraftResult(result.data);
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void showDraftResult(@NonNull DraftMessageResponse response) {
        String message;
        if (Boolean.TRUE.equals(response.held)) {
            message = "Held: " + (response.reason == null ? "—" : response.reason);
        } else {
            message = (response.body == null ? "" : response.body)
                    + "\n\nStatus: " + response.status;
        }
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.project_quick_draft_message)
                .setMessage(message)
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    // ── Tabs ─────────────────────────────────────────────────────────

    private void renderTab() {
        if (project == null || binding == null) return;
        binding.stateView.hide();
        binding.actionPrimary.setVisibility(View.GONE);
        binding.actionSecondary.setVisibility(View.GONE);

        switch (currentTab) {
            case TAB_PLAN: renderPlan(); break;
            case TAB_TASKS: renderTasks(); break;
            case TAB_TIMELINE: renderTimeline(); break;
            case TAB_PEOPLE: renderPeople(); break;
            case TAB_TEAM: renderTeam(); break;
            case TAB_CONFLICTS: renderConflicts(); break;
            case TAB_REPORTS: renderReports(); break;
            case TAB_OVERVIEW:
            default: renderOverview(); break;
        }
    }

    private void showActions(@NonNull String primaryLabel, @NonNull Runnable primary) {
        binding.actionPrimary.setText(primaryLabel);
        binding.actionPrimary.setVisibility(View.VISIBLE);
        binding.actionPrimary.setOnClickListener(v -> primary.run());
    }

    private void renderOverview() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        if (project.statusReason != null && !project.statusReason.isEmpty()) {
            rows.add(new RowAdapter.Row(getString(R.string.project_change_status),
                    project.statusReason, null, null, null));
        }
        if (project.targetEndDate != null) {
            rows.add(new RowAdapter.Row("Target end date", project.targetEndDate,
                    null, null, null));
        }
        List<TaskDto> nextTasks = new ArrayList<>();
        if (project.tasks != null) {
            for (TaskDto t : project.tasks) {
                if ("open".equals(t.status) || "in_progress".equals(t.status)) {
                    nextTasks.add(t);
                }
            }
            nextTasks.sort(Comparator.comparing(t -> t.dueDate == null ? "9999" : t.dueDate));
        }
        for (int i = 0; i < Math.min(3, nextTasks.size()); i++) {
            TaskDto t = nextTasks.get(i);
            rows.add(new RowAdapter.Row(t.title,
                    LeadStates.label(t.phase == null ? "" : t.phase),
                    taskMeta(t), t.blocked ? "Blocked" : null,
                    () -> openTask(t)));
        }
        if (project.commitments != null) {
            for (ProjectDetailDto.Commitment c : project.commitments) {
                if (!"open".equals(c.status)) continue;
                String label = "ours".equals(c.direction)
                        ? getString(R.string.project_commitment_ours)
                        : getString(R.string.project_commitment_theirs);
                rows.add(new RowAdapter.Row(c.text, label,
                        c.dueDate == null ? null : "Due " + Times.dateLabel(c.dueDate),
                        null, null));
            }
        }
        submitOrEmpty(rows, getString(R.string.project_overview_empty));
    }

    private String taskMeta(@NonNull TaskDto t) {
        StringBuilder sb = new StringBuilder();
        if (t.priority != null) sb.append(t.priority);
        if (t.dueDate != null) {
            if (sb.length() > 0) sb.append(" · ");
            sb.append("due ").append(Times.dateLabel(t.dueDate));
        }
        return sb.toString();
    }

    private void openTask(@NonNull TaskDto t) {
        pushFragment(TaskDetailFragment.create(projectId, t.id));
    }

    private void renderPlan() {
        if (plans == null) {
            binding.stateView.showLoading();
            repository.plans(projectId, result -> {
                if (binding == null || currentTab != TAB_PLAN) return;
                if (result.isSuccess() && result.data != null) {
                    plans = result.data;
                    renderPlan();
                } else if (result.error != null) {
                    binding.stateView.showError(result.error.message, this::renderPlan);
                }
            });
            return;
        }
        List<RowAdapter.Row> rows = new ArrayList<>();
        for (PlanVersionDto p : plans) {
            boolean active = p.version == (project.currentPlanVersion == null
                    ? -1 : project.currentPlanVersion);
            String title = getString(R.string.project_plan_version, p.version)
                    + (active ? " (" + getString(R.string.project_plan_active) + ")" : "");
            String meta = LeadStates.label(p.status)
                    + (p.trigger == null ? "" : " · " + p.trigger);
            rows.add(new RowAdapter.Row(title, p.summary, meta, null,
                    p.changesFromPrevious == null ? null : () -> showDiff(p)));
        }
        submitOrEmpty(rows, getString(R.string.project_plan_empty));
    }

    private void showDiff(@NonNull PlanVersionDto p) {
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(getString(R.string.project_plan_version, p.version))
                .setMessage(Pretty.value(p.changesFromPrevious))
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    private void renderTasks() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        if (project.tasks != null) {
            List<TaskDto> sorted = new ArrayList<>(project.tasks);
            sorted.sort(Comparator.comparingInt(this::phaseRank));
            for (TaskDto t : sorted) {
                String badge = t.blocked ? "Blocked" : ("P1".equals(t.priority) ? "P1" : null);
                rows.add(new RowAdapter.Row(t.title, LeadStates.label(t.status),
                        LeadStates.label(t.phase == null ? "" : t.phase) + " · " + taskMeta(t),
                        badge, () -> openTask(t)));
            }
        }
        submitOrEmpty(rows, getString(R.string.project_tasks_empty));
    }

    private int phaseRank(@NonNull TaskDto t) {
        for (int i = 0; i < PHASE_ORDER.length; i++) {
            if (PHASE_ORDER[i].equals(t.phase)) return i;
        }
        return PHASE_ORDER.length;
    }

    private void renderTimeline() {
        if (timeline == null) {
            binding.stateView.showLoading();
            repository.timeline(projectId, result -> {
                if (binding == null || currentTab != TAB_TIMELINE) return;
                if (result.isSuccess() && result.data != null) {
                    timeline = result.data;
                    renderTimeline();
                } else if (result.error != null) {
                    binding.stateView.showError(result.error.message, this::renderTimeline);
                }
            });
            return;
        }
        List<RowAdapter.Row> rows = new ArrayList<>();
        for (TimelineEventDto e : timeline) {
            String body = e.details == null ? null : Pretty.value(e.details);
            rows.add(new RowAdapter.Row(LeadStates.label(e.event), body,
                    (e.actor == null ? "" : e.actor + " · ")
                            + Times.ago(Times.parseUtc(e.at)), null, null));
        }
        submitOrEmpty(rows, getString(R.string.project_timeline_empty));
    }

    private void renderPeople() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        if (project.stakeholders != null) {
            for (ProjectDetailDto.Stakeholder s : project.stakeholders) {
                String body = s.roleAtClient == null ? null : LeadStates.label(s.roleAtClient);
                StringBuilder meta = new StringBuilder();
                if (s.influence != null) meta.append(LeadStates.label(s.influence));
                if (meta.length() > 0) meta.append(" · ");
                meta.append(s.preferredChannel);
                if (s.receivesProgressUpdates) meta.append(" · gets updates");
                rows.add(new RowAdapter.Row(s.name, body, meta.toString(), null,
                        () -> WhySheet.open(getParentFragmentManager(), "stakeholder", s.id)));
            }
        }
        submitOrEmpty(rows, getString(R.string.project_people_empty));
        boolean canManage = RoleGate.has(tokenStore.getRole(), RoleGate.MANAGE_LEADS);
        if (canManage) {
            showActions(getString(R.string.project_people_add), this::addStakeholderFlow);
        }
    }

    private void addStakeholderFlow() {
        if (project.leadId == null) {
            Toast.makeText(requireContext(), R.string.project_no_lead, Toast.LENGTH_SHORT).show();
            return;
        }
        leadsRepository.detail(project.leadId, result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null || result.data.contacts == null
                    || result.data.contacts.isEmpty()) {
                Toast.makeText(requireContext(), R.string.project_people_no_contacts,
                        Toast.LENGTH_LONG).show();
                return;
            }
            List<ContactDto> contacts = result.data.contacts;
            String[] names = new String[contacts.size()];
            for (int i = 0; i < contacts.size(); i++) names[i] = contacts.get(i).name;
            new MaterialAlertDialogBuilder(requireContext())
                    .setTitle(R.string.project_people_pick_contact)
                    .setItems(names, (d, which) -> stakeholderFieldsDialog(contacts.get(which)))
                    .setNegativeButton(android.R.string.cancel, null)
                    .show();
        });
    }

    private void stakeholderFieldsDialog(@NonNull ContactDto contact) {
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);

        EditText role = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        role.setHint(R.string.stakeholder_role_hint);
        wrapper.addView(role);

        EditText influence = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        influence.setHint(R.string.stakeholder_influence_hint);
        wrapper.addView(influence);

        CheckBox receivesUpdates = new CheckBox(requireContext());
        receivesUpdates.setText(R.string.stakeholder_receives_updates);
        wrapper.addView(receivesUpdates);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(contact.name)
                .setView(wrapper)
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    ProjectRequests.Stakeholder body = new ProjectRequests.Stakeholder();
                    body.contactId = contact.id;
                    body.roleAtClient = emptyToNull(role.getText().toString());
                    body.influence = emptyToNull(influence.getText().toString());
                    body.receivesProgressUpdates = receivesUpdates.isChecked();
                    repository.addStakeholder(projectId, body, result -> {
                        if (binding == null) return;
                        if (result.isSuccess()) {
                            Snackbar.make(binding.getRoot(), R.string.project_people_saved,
                                    Snackbar.LENGTH_SHORT).show();
                            load();
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void renderTeam() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        boolean canManage = RoleGate.has(tokenStore.getRole(), RoleGate.MANAGE_STAFF)
                || RoleGate.has(tokenStore.getRole(), RoleGate.MANAGE_TEAMS);
        if (project.members != null) {
            for (ProjectDetailDto.Member m : project.members) {
                rows.add(new RowAdapter.Row(m.name,
                        m.roleInProject == null ? null : LeadStates.label(m.roleInProject),
                        null, null,
                        canManage ? () -> removeMemberConfirm(m) : null));
            }
        }
        submitOrEmpty(rows, getString(R.string.project_team_empty));
        showActions(getString(R.string.project_team_add), this::addMemberFlow);
    }

    private void removeMemberConfirm(@NonNull ProjectDetailDto.Member m) {
        new MaterialAlertDialogBuilder(requireContext())
                .setMessage(getString(R.string.project_team_remove_confirm, m.name))
                .setPositiveButton(R.string.project_team_remove, (d, w) ->
                        repository.removeMember(projectId, m.userId, result -> {
                            if (binding == null) return;
                            if (result.isSuccess()) {
                                load();
                            } else if (result.error != null) {
                                Snackbar.make(binding.getRoot(), result.error.message,
                                        Snackbar.LENGTH_LONG).show();
                            }
                        }))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void addMemberFlow() {
        if (!RoleGate.has(tokenStore.getRole(), RoleGate.MANAGE_STAFF)) {
            Toast.makeText(requireContext(), R.string.project_team_no_permission,
                    Toast.LENGTH_LONG).show();
            return;
        }
        workflowRepository.orgUsers(result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null || result.data.isEmpty()) {
                if (result.error != null) {
                    Snackbar.make(binding.getRoot(), result.error.message,
                            Snackbar.LENGTH_LONG).show();
                }
                return;
            }
            List<OrgUserDto> users = result.data;
            String[] names = new String[users.size()];
            for (int i = 0; i < users.size(); i++) {
                names[i] = users.get(i).name + " (" + LeadStates.label(users.get(i).role) + ")";
            }
            new MaterialAlertDialogBuilder(requireContext())
                    .setTitle(R.string.project_team_add)
                    .setItems(names, (d, which) -> {
                        OrgUserDto picked = users.get(which);
                        repository.addMember(projectId, picked.id, picked.role, addResult -> {
                            if (binding == null) return;
                            if (addResult.isSuccess()) {
                                Snackbar.make(binding.getRoot(),
                                        getString(R.string.project_team_added, picked.name),
                                        Snackbar.LENGTH_SHORT).show();
                                load();
                            } else if (addResult.error != null) {
                                Snackbar.make(binding.getRoot(), addResult.error.message,
                                        Snackbar.LENGTH_LONG).show();
                            }
                        });
                    })
                    .setNegativeButton(android.R.string.cancel, null)
                    .show();
        });
    }

    private void renderConflicts() {
        if (conflicts == null) {
            binding.stateView.showLoading();
            repository.conflicts(projectId, result -> {
                if (binding == null || currentTab != TAB_CONFLICTS) return;
                if (result.isSuccess() && result.data != null) {
                    conflicts = result.data;
                    renderConflicts();
                } else if (result.error != null) {
                    binding.stateView.showError(result.error.message, this::renderConflicts);
                }
            });
            return;
        }
        List<RowAdapter.Row> rows = new ArrayList<>();
        for (ConflictDto c : conflicts) {
            boolean open = "open".equals(c.status);
            rows.add(new RowAdapter.Row(
                    open ? getString(R.string.project_conflict_resolve_title)
                            : LeadStates.label(c.status),
                    c.description,
                    open ? null : c.resolutionNote,
                    open ? null : "Resolved",
                    open ? () -> resolveConflictDialog(c) : null));
        }
        submitOrEmpty(rows, getString(R.string.project_conflicts_empty));
    }

    private void resolveConflictDialog(@NonNull ConflictDto c) {
        EditText input = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        input.setHint(R.string.project_conflict_resolution_hint);
        input.setMinLines(2);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.project_conflict_resolve_title)
                .setMessage(c.description)
                .setView(pad(input))
                .setPositiveButton(R.string.project_conflict_resolve, (d, w) -> {
                    String note = input.getText().toString().trim();
                    if (note.length() < 2) {
                        Toast.makeText(requireContext(),
                                R.string.project_conflict_resolution_too_short,
                                Toast.LENGTH_SHORT).show();
                        return;
                    }
                    repository.resolveConflict(projectId, c.id, note, result -> {
                        if (binding == null) return;
                        if (result.isSuccess()) {
                            Snackbar.make(binding.getRoot(), R.string.project_conflict_resolved,
                                    Snackbar.LENGTH_SHORT).show();
                            conflicts = null;
                            renderConflicts();
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void renderReports() {
        submitOrEmpty(new ArrayList<>(), getString(R.string.project_reports_none));
        showActions(getString(R.string.project_reports_generate), () -> generateReport("client"));
        binding.actionSecondary.setText(R.string.project_reports_generate_internal);
        binding.actionSecondary.setVisibility(View.VISIBLE);
        binding.actionSecondary.setOnClickListener(v -> generateReport("internal"));
    }

    private void generateReport(@NonNull String kind) {
        Snackbar.make(binding.getRoot(), R.string.assistant_thinking, Snackbar.LENGTH_SHORT).show();
        repository.weeklyReport(projectId, kind, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                ProjectResponses.WeeklyReport report = result.data;
                if (Boolean.TRUE.equals(report.skipped)) {
                    Snackbar.make(binding.getRoot(),
                            report.reason == null
                                    ? getString(R.string.project_reports_none) : report.reason,
                            Snackbar.LENGTH_LONG).show();
                    return;
                }
                String message = report.contentMd
                        + (report.sentMessageId == null ? ""
                                : "\n\n" + getString(R.string.project_reports_sent_note));
                new MaterialAlertDialogBuilder(requireContext())
                        .setTitle(R.string.project_reports_preview_title)
                        .setMessage(message)
                        .setPositiveButton(android.R.string.ok, null)
                        .show();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message, Snackbar.LENGTH_LONG)
                        .show();
            }
        });
    }

    // ── Helpers ──────────────────────────────────────────────────────

    private void submitOrEmpty(List<RowAdapter.Row> rows, String emptyText) {
        adapter.submit(rows);
        if (rows.isEmpty()) {
            binding.stateView.showEmpty(emptyText, null, R.drawable.ic_tab_folder, null, null);
        } else {
            binding.stateView.hide();
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

    private void pushFragment(@NonNull Fragment fragment) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(fragment);
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
