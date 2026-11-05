package com.yuvipep.app.feature.meetings;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.dto.MeetingNotesRequest;
import com.yuvipep.app.databinding.FragmentNotesComposerBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import java.util.Map;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Typed meeting notes (03 §5): the manual path into the same Planner
 * pipeline. The Planner runs synchronously (LLM latency — 120s timeout),
 * so the screen narrates instead of freezing, then shows what the Planner
 * actually did — including a held-for-human outcome, honestly.
 */
@AndroidEntryPoint
public class NotesComposerFragment extends Fragment {

    private static final String ARG_LEAD = "lead_id";
    private static final String ARG_LEAD_NAME = "lead_name";

    /** Backend MeetingType vocabulary (app/core/constants.py). */
    private static final String[] MEETING_TYPES = {
            "first_visit", "negotiation", "kickoff", "review", "closure",
    };

    public static NotesComposerFragment create(@NonNull String leadId,
                                               @NonNull String leadName) {
        NotesComposerFragment fragment = new NotesComposerFragment();
        Bundle args = new Bundle();
        args.putString(ARG_LEAD, leadId);
        args.putString(ARG_LEAD_NAME, leadName);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject MeetingsRepository repository;

    private FragmentNotesComposerBinding binding;
    private String meetingType = MEETING_TYPES[0];

    @javax.inject.Inject com.yuvipep.app.core.net.TokenStore tokenStore;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentNotesComposerBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.leadName.setText(requireArguments().getString(ARG_LEAD_NAME, ""));
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());

        // A relationship manager only ever has one kind of meeting, so they
        // get told what this is rather than asked. Every listed type is a
        // stage of selling, and an RM holds neither `manage_leads` nor
        // `send_proposal` — offering the picker would be offering five wrong
        // answers.
        if (RoleGate.RELATIONSHIP_MANAGER.equals(tokenStore.getRole())) {
            meetingType = "relationship";
            binding.typeInput.setText(getString(R.string.meeting_type_catch_up), false);
            binding.typeInput.setEnabled(false);
        } else {
            String[] labels = new String[MEETING_TYPES.length];
            for (int i = 0; i < MEETING_TYPES.length; i++) {
                labels[i] = LeadStates.label(MEETING_TYPES[i]);
            }
            binding.typeInput.setAdapter(new ArrayAdapter<>(requireContext(),
                    android.R.layout.simple_list_item_1, labels));
            binding.typeInput.setText(labels[0], false);
            binding.typeInput.setOnItemClickListener((parent, v, position, id) ->
                    meetingType = MEETING_TYPES[position]);
        }

        binding.sendButton.setOnClickListener(v -> send());
    }

    private void send() {
        String text = binding.notesInput.getText() == null ? ""
                : binding.notesInput.getText().toString().trim();
        if (text.length() < 10) {
            Toast.makeText(requireContext(), R.string.notes_too_short,
                    Toast.LENGTH_SHORT).show();
            return;
        }
        String title = binding.titleInput.getText() == null ? null
                : binding.titleInput.getText().toString().trim();
        binding.sendButton.setVisibility(View.GONE);
        binding.processingRow.setVisibility(View.VISIBLE);

        MeetingNotesRequest body = new MeetingNotesRequest(
                requireArguments().getString(ARG_LEAD, ""), text,
                title == null || title.isEmpty() ? null : title, meetingType);
        repository.notes(body, result -> {
            if (binding == null) return;
            binding.processingRow.setVisibility(View.GONE);
            binding.sendButton.setVisibility(View.VISIBLE);
            if (result.isSuccess() && result.data != null) {
                String meetingId = result.data.meeting == null
                        ? null : result.data.meeting.id;
                // A catch-up has no plan, and saying "no detail" about it
                // would read as a failure. Report what actually happened.
                if (result.data.relationship != null) {
                    showCatchUpResult(result.data.relationship, meetingId);
                } else {
                    showPlannerResult(result.data.planner, meetingId);
                }
            } else if (result.isError() && result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
            }
        });
    }

    /** What a catch-up produced: a summary saved, and the next conversation
     *  suggested. No plan, because there is no project. */
    private void showCatchUpResult(@NonNull Map<String, Object> relationship,
                                   @Nullable String meetingId) {
        Object next = relationship.get("next_touch");
        String body = next == null
                ? getString(R.string.catch_up_saved_body)
                : getString(R.string.catch_up_saved_next, String.valueOf(next));
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.catch_up_saved_title)
                .setMessage(body)
                .setPositiveButton(R.string.notes_open_meeting, (d, w) -> {
                    requireActivity().getOnBackPressedDispatcher().onBackPressed();
                    if (meetingId != null && getActivity() instanceof MainActivity) {
                        ((MainActivity) getActivity()).push(
                                MeetingDetailFragment.create(meetingId));
                    }
                })
                .setNegativeButton(R.string.action_done, (d, w) ->
                        requireActivity().getOnBackPressedDispatcher().onBackPressed())
                .setCancelable(false)
                .show();
    }

    /** Renders whatever the Planner reported, generically — no invented
     *  fields, no fake success (the result sheet of 03 §5). */
    private void showPlannerResult(@Nullable Map<String, Object> planner,
                                   @Nullable String meetingId) {
        StringBuilder message = new StringBuilder();
        if (planner == null || planner.isEmpty()) {
            message.append(getString(R.string.notes_planner_no_detail));
        } else {
            for (Map.Entry<String, Object> entry : planner.entrySet()) {
                Object value = entry.getValue();
                if (value == null) continue;
                String rendered = value instanceof Double
                        && ((Double) value) == Math.floor((Double) value)
                        ? String.valueOf(((Double) value).longValue())
                        : String.valueOf(value);
                if (rendered.isEmpty() || "[]".equals(rendered)
                        || "{}".equals(rendered)) continue;
                message.append(LeadStates.label(entry.getKey()))
                        .append(": ").append(rendered).append("\n\n");
            }
            if (message.length() == 0) {
                message.append(getString(R.string.notes_planner_no_detail));
            }
        }
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.notes_planner_title)
                .setMessage(message.toString().trim())
                .setPositiveButton(R.string.notes_open_meeting, (d, w) -> {
                    requireActivity().getOnBackPressedDispatcher().onBackPressed();
                    if (meetingId != null && getActivity() instanceof MainActivity) {
                        ((MainActivity) getActivity()).push(
                                MeetingDetailFragment.create(meetingId));
                    }
                })
                .setNegativeButton(R.string.action_done, (d, w) ->
                        requireActivity().getOnBackPressedDispatcher().onBackPressed())
                .setCancelable(false)
                .show();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
