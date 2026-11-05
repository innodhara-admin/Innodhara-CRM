package com.yuvipep.app.feature.followups;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.chip.Chip;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.snackbar.Snackbar;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.ContactDto;
import com.yuvipep.app.core.net.dto.DraftMessageResponse;
import com.yuvipep.app.core.net.dto.FollowUpDto;
import com.yuvipep.app.core.net.dto.MessageRequests;
import com.yuvipep.app.core.voice.VoiceEditText;
import com.yuvipep.app.databinding.FragmentFollowupsBinding;
import com.yuvipep.app.feature.leads.LeadStates;
import com.yuvipep.app.feature.leads.LeadsRepository;
import com.yuvipep.app.feature.leads.RowAdapter;
import com.yuvipep.app.feature.projects.ProjectsRepository;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The follow-up queue (03 §12): due follow-ups grouped by urgency, each
 * completable (the backend auto-schedules the next reminder and says so),
 * or answered with an AI-drafted message (approval-gated like every other
 * outward message).
 */
@AndroidEntryPoint
public class FollowUpQueueFragment extends Fragment {

    @Inject FollowupsRepository repository;
    @Inject LeadsRepository leadsRepository;
    @Inject ProjectsRepository projectsRepository;

    private FragmentFollowupsBinding binding;
    private RowAdapter adapter;
    private String due = "today";
    private final String[] dueValues = {"today", "overdue", "this_week", "all_pending"};

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentFollowupsBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());

        String[] labels = {getString(R.string.followups_today),
                getString(R.string.followups_overdue),
                getString(R.string.followups_week),
                getString(R.string.followups_all_pending)};
        for (int i = 0; i < labels.length; i++) {
            Chip chip = new Chip(requireContext(), null,
                    com.google.android.material.R.attr.chipStyle);
            chip.setText(labels[i]);
            chip.setCheckable(true);
            chip.setChecked(i == 0);
            final int index = i;
            chip.setOnClickListener(v -> {
                due = dueValues[index];
                load();
            });
            binding.filterChips.addView(chip);
        }
        binding.mineSwitch.setOnCheckedChangeListener((v, checked) -> load());

        adapter = new RowAdapter();
        binding.list.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.list.setAdapter(adapter);
        load();
    }

    private void load() {
        binding.stateView.showLoading();
        repository.list(due, binding.mineSwitch.isChecked(), result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                render(result.data);
            } else if (result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    private void render(@NonNull List<FollowUpDto> followups) {
        List<RowAdapter.Row> rows = new ArrayList<>();
        LocalDate today = LocalDate.now();
        for (FollowUpDto f : followups) {
            boolean overdue = false;
            try {
                overdue = LocalDate.parse(f.dueDate).isBefore(today);
            } catch (RuntimeException ignored) {
            }
            String meta = getString(R.string.followups_due_meta,
                    com.yuvipep.app.core.util.Times.dateLabel(f.dueDate),
                    LeadStates.label(f.channel));
            rows.add(new RowAdapter.Row(
                    f.clientName == null ? getString(R.string.followups_title) : f.clientName,
                    f.note, meta,
                    overdue ? getString(R.string.followups_overdue) : null,
                    () -> followupDialog(f)));
        }
        adapter.submit(rows);
        if (rows.isEmpty()) {
            binding.stateView.showEmpty(getString(R.string.followups_empty_title),
                    getString(R.string.followups_empty_body),
                    R.drawable.ic_check, null, null);
        } else {
            binding.stateView.hide();
        }
    }

    private void followupDialog(@NonNull FollowUpDto followup) {
        String[] actions = {getString(R.string.followups_done),
                getString(R.string.followups_draft),
                getString(R.string.followups_open_lead)};
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(followup.clientName == null
                        ? getString(R.string.followups_title) : followup.clientName)
                .setItems(actions, (d, which) -> {
                    if (which == 0) completeDialog(followup);
                    else if (which == 1) draftFlow(followup);
                    else openLead(followup);
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void completeDialog(@NonNull FollowUpDto followup) {
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);

        EditText note = new VoiceEditText(requireContext());
        note.setHint(R.string.followups_complete_note_hint);
        wrapper.addView(note);
        CheckBox next = new CheckBox(requireContext());
        next.setText(R.string.followups_schedule_next);
        next.setChecked(true);
        wrapper.addView(next);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.followups_done)
                .setView(wrapper)
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    String text = note.getText() == null ? ""
                            : note.getText().toString().trim();
                    repository.complete(followup.id, text.isEmpty() ? null : text,
                            next.isChecked(), result -> {
                                if (binding == null) return;
                                if (result.isSuccess() && result.data != null) {
                                    Object nextDue = result.data.get("next_followup_due");
                                    Snackbar.make(binding.getRoot(), nextDue instanceof String
                                            ? getString(R.string.followups_done_next,
                                                    (String) nextDue)
                                            : getString(R.string.followups_done_no_next),
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

    /** AI drafts the follow-up message; it lands in Approvals, never sends
     * directly — same contract as everywhere else. */
    private void draftFlow(@NonNull FollowUpDto followup) {
        leadsRepository.detail(followup.leadId, result -> {
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
                draftInstructionDialog(followup, contacts.get(0));
                return;
            }
            String[] names = new String[contacts.size()];
            for (int i = 0; i < contacts.size(); i++) names[i] = contacts.get(i).name;
            new MaterialAlertDialogBuilder(requireContext())
                    .setTitle(R.string.project_people_pick_contact)
                    .setItems(names, (d, which) ->
                            draftInstructionDialog(followup, contacts.get(which)))
                    .setNegativeButton(android.R.string.cancel, null)
                    .show();
        });
    }

    private void draftInstructionDialog(@NonNull FollowUpDto followup,
                                        @NonNull ContactDto contact) {
        EditText input = new VoiceEditText(requireContext());
        input.setHint(R.string.message_draft_instruction_hint);
        input.setMinLines(2);
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);
        wrapper.addView(input);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(getString(R.string.followups_draft) + " — " + contact.name)
                .setView(wrapper)
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    MessageRequests.Draft body = new MessageRequests.Draft();
                    body.contactId = contact.id;
                    body.purpose = followup.note == null
                            ? "follow-up" : "follow-up: " + followup.note;
                    String instruction = input.getText() == null ? ""
                            : input.getText().toString().trim();
                    if (!instruction.isEmpty()) body.instruction = instruction;
                    projectsRepository.draftMessage(body, result -> {
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
                .setTitle(R.string.followups_draft)
                .setMessage(message)
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    private void openLead(@NonNull FollowUpDto followup) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).openEntity("lead", followup.leadId);
        }
    }
}
