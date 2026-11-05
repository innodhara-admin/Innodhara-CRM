package com.yuvipep.app.feature.meetings;

import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.work.WorkInfo;
import androidx.work.WorkManager;

import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.MeetingDto;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentMeetingDetailBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import java.util.UUID;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Pipeline progress (03 §5): Uploading → Uploaded → Transcribing →
 * Extracting → Review → Done, polled from GET /meetings/{id} every 5s.
 * FAILED shows the backend reason verbatim with Retry; review_pending
 * routes to the review gate; completed shows the result summary.
 * Opened either with a meeting id (from lists/notifications) or an upload
 * work id (fresh recording — the meeting id arrives when upload finishes).
 */
@AndroidEntryPoint
public class MeetingDetailFragment extends Fragment {

    private static final String ARG_MEETING = "meeting_id";
    private static final String ARG_WORK = "work_id";
    private static final long POLL_MS = 5000;

    public static MeetingDetailFragment create(@NonNull String meetingId) {
        MeetingDetailFragment fragment = new MeetingDetailFragment();
        Bundle args = new Bundle();
        args.putString(ARG_MEETING, meetingId);
        fragment.setArguments(args);
        return fragment;
    }

    public static MeetingDetailFragment createForUpload(@NonNull String workId) {
        MeetingDetailFragment fragment = new MeetingDetailFragment();
        Bundle args = new Bundle();
        args.putString(ARG_WORK, workId);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject MeetingsRepository repository;
    @Inject com.yuvipep.app.feature.assistant.ContextBus contextBus;

    private FragmentMeetingDetailBinding binding;
    private String meetingId;
    private MeetingDto meeting;
    private String uploadError;
    private boolean uploading;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable poller = this::poll;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentMeetingDetailBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.retryButton.setOnClickListener(v -> retry());
        binding.reviewButton.setOnClickListener(v -> {
            if (meetingId != null && getActivity() instanceof MainActivity) {
                ((MainActivity) getActivity()).push(
                        MeetingReviewFragment.create(meetingId));
            }
        });

        meetingId = requireArguments().getString(ARG_MEETING);
        String workId = requireArguments().getString(ARG_WORK);
        if (meetingId == null && workId != null) {
            uploading = true;
            WorkManager.getInstance(requireContext())
                    .getWorkInfoByIdLiveData(UUID.fromString(workId))
                    .observe(getViewLifecycleOwner(), this::onUploadInfo);
        }
        renderSteps();
    }

    private void onUploadInfo(@Nullable WorkInfo info) {
        if (info == null || binding == null) return;
        if (info.getState() == WorkInfo.State.SUCCEEDED) {
            uploading = false;
            meetingId = info.getOutputData()
                    .getString(UploadMeetingWorker.OUT_MEETING_ID);
            poll();
        } else if (info.getState() == WorkInfo.State.FAILED) {
            uploading = false;
            uploadError = info.getOutputData().getString(UploadMeetingWorker.OUT_ERROR);
            if (uploadError == null) uploadError = getString(R.string.upload_failed_generic);
            renderSteps();
        } else {
            renderSteps();
        }
    }

    @Override
    public void onResume() {
        super.onResume();
        if (meetingId != null) poll();
    }

    @Override
    public void onPause() {
        super.onPause();
        handler.removeCallbacks(poller);
    }

    private void poll() {
        if (binding == null || meetingId == null) return;
        repository.meeting(meetingId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                meeting = result.data;
                contextBus.set("meeting", meetingId,
                        getString(R.string.meeting_title_fallback));
                renderSteps();
                if (!isTerminal(meeting.status)) {
                    handler.removeCallbacks(poller);
                    handler.postDelayed(poller, POLL_MS);
                }
            } else if (result.isError() && result.error != null) {
                if (meeting == null) {
                    binding.stateView.showError(result.error.message, this::poll);
                } else {
                    // Keep the last good render; try again on the next tick.
                    handler.removeCallbacks(poller);
                    handler.postDelayed(poller, POLL_MS);
                }
            }
        });
    }

    private static boolean isTerminal(@Nullable String status) {
        return "completed".equals(status) || "failed".equals(status)
                || "review_pending".equals(status);
    }

    private void retry() {
        if (meetingId == null) return;
        binding.retryButton.setEnabled(false);
        repository.retry(meetingId, result -> {
            if (binding == null) return;
            binding.retryButton.setEnabled(true);
            if (result.isSuccess()) {
                binding.errorCard.setVisibility(View.GONE);
                poll();
            } else if (result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
            }
        });
    }

    // ── Rendering ────────────────────────────────────────────────────

    /** step index reached per status; -1 = failed. */
    private int stageIndex() {
        if (uploading || uploadError != null) return 0;
        if (meeting == null) return 1;
        switch (meeting.status) {
            case "uploaded": return 1;
            case "transcribing": return 2;
            case "transcribed":
            case "extracting": return 3;
            case "review_pending": return 4;
            case "completed": return 5;
            case "failed": return -1;
            default: return 1;
        }
    }

    private void renderSteps() {
        if (binding == null) return;
        binding.stateView.hide();
        binding.stepsContainer.removeAllViews();
        String[] labels = {
                getString(R.string.meeting_step_uploading),
                getString(R.string.meeting_step_uploaded),
                getString(R.string.meeting_step_transcribing),
                getString(R.string.meeting_step_extracting),
                getString(R.string.meeting_step_review),
                getString(R.string.meeting_step_done),
        };
        int stage = stageIndex();
        for (int i = 0; i < labels.length; i++) {
            boolean done;
            boolean active;
            if (stage == -1) {
                // Failure: everything before transcribing counts as done.
                done = i <= 1;
                active = false;
            } else {
                done = i < stage || stage == 5;
                active = i == stage && stage != 5;
            }
            binding.stepsContainer.addView(stepRow(labels[i], done, active));
        }

        if (uploadError != null) {
            binding.errorCard.setVisibility(View.VISIBLE);
            binding.errorText.setText(uploadError);
            binding.retryButton.setVisibility(View.GONE);
        } else if (meeting != null && "failed".equals(meeting.status)) {
            binding.errorCard.setVisibility(View.VISIBLE);
            binding.errorText.setText(meeting.error == null
                    ? getString(R.string.meeting_failed_generic) : meeting.error);
            binding.retryButton.setVisibility(View.VISIBLE);
        } else {
            binding.errorCard.setVisibility(View.GONE);
        }

        binding.reviewButton.setVisibility(meeting != null
                && "review_pending".equals(meeting.status) ? View.VISIBLE : View.GONE);

        renderResult();
    }

    private View stepRow(String label, boolean done, boolean active) {
        LinearLayout row = new LinearLayout(requireContext());
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, 14, 0, 14);

        TextView icon = new TextView(requireContext());
        icon.setText(done ? "✓" : active ? "●" : "○");
        icon.setTextColor(done
                ? ContextCompat.getColor(requireContext(), R.color.health_on_track)
                : active ? ContextCompat.getColor(requireContext(), R.color.brand_accent)
                        : com.google.android.material.color.MaterialColors.getColor(
                                binding.getRoot(),
                                com.google.android.material.R.attr.colorOutline));
        icon.setTextSize(18);
        icon.setWidth((int) (32 * getResources().getDisplayMetrics().density));

        TextView text = new TextView(requireContext());
        text.setText(label);
        text.setTextSize(16);
        int onSurface = com.google.android.material.color.MaterialColors.getColor(
                binding.getRoot(), com.google.android.material.R.attr.colorOnSurface);
        int outline = com.google.android.material.color.MaterialColors.getColor(
                binding.getRoot(), com.google.android.material.R.attr.colorOutline);
        text.setTextColor(done || active ? onSurface : outline);
        if (active) text.setTypeface(null, Typeface.BOLD);

        row.addView(icon);
        row.addView(text);
        return row;
    }

    private void renderResult() {
        if (meeting == null || !"completed".equals(meeting.status)
                && !"review_pending".equals(meeting.status)) {
            binding.resultContainer.setVisibility(View.GONE);
            return;
        }
        binding.resultContainer.setVisibility(View.VISIBLE);
        binding.resultContainer.removeAllViews();

        if (meeting.transcript != null && meeting.transcript.summary != null
                && !meeting.transcript.summary.isEmpty()) {
            addResult(getString(R.string.meeting_result_summary),
                    meeting.transcript.summary);
        }
        if (meeting.transcript != null && meeting.transcript.lowConfidence) {
            addResult(getString(R.string.meeting_result_low_confidence_title),
                    getString(R.string.meeting_result_low_confidence));
        }
        if (meeting.actionItems != null && !meeting.actionItems.isEmpty()) {
            StringBuilder items = new StringBuilder();
            for (MeetingDto.Item item : meeting.actionItems) {
                if (items.length() > 0) items.append("\n");
                items.append("• ").append(item.title);
                // The date the meeting agreed on belongs next to the task:
                // without it the list read as four undated intentions.
                String due = Times.dateLabel(item.dueDate);
                if (!due.isEmpty()) {
                    items.append("  ").append(getString(R.string.meeting_result_item_due, due));
                }
                items.append("  (").append(LeadStates.label(item.status)).append(")");
            }
            addResult(getString(R.string.meeting_result_items,
                    meeting.actionItems.size()), items.toString());
        }
        if (meeting.stateSuggestion != null && !meeting.stateSuggestion.isEmpty()) {
            addResult(getString(R.string.meeting_result_suggestion_title),
                    getString(R.string.meeting_result_suggestion,
                            meeting.stateSuggestion));
        }
        if (binding.resultContainer.getChildCount() == 0) {
            addResult(getString(R.string.meeting_result_none_title),
                    getString(R.string.meeting_result_none));
        }
    }

    private void addResult(String title, String body) {
        TextView heading = new TextView(requireContext());
        heading.setText(title);
        heading.setTypeface(null, Typeface.BOLD);
        heading.setTextColor(com.google.android.material.color.MaterialColors.getColor(
                binding.getRoot(), com.google.android.material.R.attr.colorOnSurface));
        heading.setPadding(0, 16, 0, 4);
        TextView text = new TextView(requireContext());
        text.setText(body);
        text.setTextColor(com.google.android.material.color.MaterialColors.getColor(
                binding.getRoot(),
                com.google.android.material.R.attr.colorOnSurfaceVariant));
        binding.resultContainer.addView(heading);
        binding.resultContainer.addView(text);
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        handler.removeCallbacks(poller);
        binding = null;
    }
}
