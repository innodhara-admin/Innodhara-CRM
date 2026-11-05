package com.yuvipep.app.feature.meetings;

import android.Manifest;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.yuvipep.app.MainActivity;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.R;
import com.yuvipep.app.databinding.FragmentRecorderBinding;

import java.io.File;
import java.util.Locale;
import java.util.UUID;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The recorder screen (03 §5): big record button, elapsed timer, level
 * meter, pause/resume, then a post-stop panel (optional title → upload via
 * WorkManager). The consent sheet already ran before this screen opens.
 *
 * <p>A file made earlier can be sent instead (customer ask, 21 Sep 2026):
 * "Choose a recording file" copies it in ({@link PickedRecording}) and then
 * reuses the same title / Upload / Discard panel and the same worker. It sits
 * behind the same consent sheet, which is what the server requires anyway.
 */
@AndroidEntryPoint
public class RecorderFragment extends Fragment {

    @javax.inject.Inject TokenStore tokenStore;
    @javax.inject.Inject com.yuvipep.app.core.util.AppExecutors executors;

    private static final String ARG_LEAD = "lead_id";
    private static final String ARG_LEAD_NAME = "lead_name";
    private static final String STATE_PICKED_PATH = "picked_path";
    private static final String STATE_PICKED_NAME = "picked_name";
    private static final String STATE_PICKED_MIME = "picked_mime";
    private static final String STATE_PICKED_SECONDS = "picked_seconds";

    public static RecorderFragment create(@NonNull String leadId,
                                          @NonNull String leadName) {
        RecorderFragment fragment = new RecorderFragment();
        Bundle args = new Bundle();
        args.putString(ARG_LEAD, leadId);
        args.putString(ARG_LEAD_NAME, leadName);
        fragment.setArguments(args);
        return fragment;
    }

    private FragmentRecorderBinding binding;
    private ActivityResultLauncher<String> permissionLauncher;
    private ActivityResultLauncher<String[]> pickLauncher;
    private long lastElapsedMs;
    /** A chosen file waiting for Upload, or null when none. */
    @Nullable private PickedRecording picked;
    private boolean copying;

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        permissionLauncher = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(), granted -> {
                    if (granted) {
                        startRecording();
                    } else {
                        // Honest fallback: typed notes stay fully functional.
                        Toast.makeText(requireContext(),
                                R.string.recorder_mic_denied, Toast.LENGTH_LONG).show();
                    }
                });
        pickLauncher = registerForActivityResult(
                new ActivityResultContracts.OpenDocument(), this::onFilePicked);
        if (savedInstanceState != null) {
            String path = savedInstanceState.getString(STATE_PICKED_PATH);
            if (path != null && new File(path).exists()) {
                picked = new PickedRecording(path,
                        savedInstanceState.getString(STATE_PICKED_NAME, ""),
                        savedInstanceState.getString(STATE_PICKED_MIME, "audio/mp4"),
                        savedInstanceState.getLong(STATE_PICKED_SECONDS, 0));
            }
        }
    }

    @Override
    public void onSaveInstanceState(@NonNull Bundle outState) {
        super.onSaveInstanceState(outState);
        if (picked != null) {
            outState.putString(STATE_PICKED_PATH, picked.path);
            outState.putString(STATE_PICKED_NAME, picked.displayName);
            outState.putString(STATE_PICKED_MIME, picked.mime);
            outState.putLong(STATE_PICKED_SECONDS, picked.seconds);
        }
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentRecorderBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.leadName.setText(requireArguments().getString(ARG_LEAD_NAME, ""));
        binding.backButton.setOnClickListener(v -> confirmLeave());
        binding.recordButton.setOnClickListener(v -> onRecordTapped());
        // F39: this was hardcoded to ACTION_PAUSE, so once the recording was
        // paused the dedicated pause button could only ever pause again — a
        // no-op, since pause() requires RECORDING. It is a toggle now, like the
        // record button beside it.
        binding.pauseButton.setOnClickListener(v -> onRecordTapped());
        binding.stopButton.setOnClickListener(v -> RecorderService.send(
                requireContext(), RecorderService.ACTION_STOP));
        binding.discardButton.setOnClickListener(v -> discard());
        binding.uploadButton.setOnClickListener(v -> upload());
        binding.pickFileButton.setOnClickListener(v ->
                pickLauncher.launch(PickedRecording.PICKER_TYPES));

        RecorderService.state().observe(getViewLifecycleOwner(), this::render);
    }

    /**
     * A relationship manager's recording is a catch-up, not a sales meeting.
     *
     * <p>Decided from the role rather than from a picker: an RM does not hold
     * `manage_leads` or `send_proposal` and cannot run a sales meeting, so
     * asking them which kind this was would be a question with one answer.
     * Every other role sends null, which is the request the server has always
     * received.
     */
    @Nullable
    private String catchUpTypeOrNull() {
        return RoleGate.RELATIONSHIP_MANAGER.equals(tokenStore.getRole())
                ? "relationship" : null;
    }

    private void onRecordTapped() {
        RecorderService.State state = RecorderService.state().getValue();
        if (state != null && state.status == RecorderService.Status.PAUSED) {
            RecorderService.send(requireContext(), RecorderService.ACTION_RESUME);
            return;
        }
        if (state != null && state.status == RecorderService.Status.RECORDING) {
            RecorderService.send(requireContext(), RecorderService.ACTION_PAUSE);
            return;
        }
        if (ContextCompat.checkSelfPermission(requireContext(),
                Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            startRecording();
        } else {
            permissionLauncher.launch(Manifest.permission.RECORD_AUDIO);
        }
    }

    private void startRecording() {
        RecorderService.startRecording(requireContext(),
                requireArguments().getString(ARG_LEAD_NAME, ""));
    }

    private void onFilePicked(@Nullable Uri uri) {
        if (uri == null || binding == null) return;
        android.content.Context app = requireContext().getApplicationContext();
        copying = true;
        binding.pickFileButton.setEnabled(false);
        binding.recordButton.setEnabled(false);
        binding.statusLabel.setText(R.string.recorder_pick_copying);
        executors.io().execute(() -> {
            PickedRecording result = null;
            String refusal = null;
            try {
                result = PickedRecording.copyIn(app, uri);
            } catch (PickedRecording.Refused r) {
                refusal = r.getMessage();
            }
            PickedRecording done = result;
            String why = refusal;
            executors.main().execute(() -> {
                copying = false;
                if (binding == null) {
                    // Screen gone while copying: do not leave the copy behind.
                    if (done != null) {
                        //noinspection ResultOfMethodCallIgnored
                        new File(done.path).delete();
                    }
                    return;
                }
                binding.pickFileButton.setEnabled(true);
                binding.recordButton.setEnabled(true);
                if (done == null) {
                    Toast.makeText(requireContext(), why, Toast.LENGTH_LONG).show();
                } else {
                    picked = done;
                }
                RecorderService.State state = RecorderService.state().getValue();
                if (state != null) render(state);
            });
        });
    }

    private void render(RecorderService.State state) {
        if (binding == null) return;
        if (picked != null && state.status == RecorderService.Status.IDLE) {
            binding.recordPanel.setVisibility(View.GONE);
            binding.uploadPanel.setVisibility(View.VISIBLE);
            binding.recordedSummary.setText(picked.seconds > 0
                    ? getString(R.string.recorder_picked_summary, picked.displayName,
                            format(picked.seconds * 1000))
                    : getString(R.string.recorder_picked_summary_no_length, picked.displayName));
            return;
        }
        binding.pickFileButton.setVisibility(
                state.status == RecorderService.Status.IDLE ? View.VISIBLE : View.GONE);
        lastElapsedMs = state.elapsedMs;
        binding.elapsed.setText(format(state.elapsedMs));
        binding.amplitudeBar.setProgress(state.amplitude);
        switch (state.status) {
            case RECORDING:
                binding.statusLabel.setText(R.string.recorder_status_recording);
                binding.pauseButton.setVisibility(View.VISIBLE);
                binding.stopButton.setVisibility(View.VISIBLE);
                binding.recordButton.setImageResource(R.drawable.ic_pause);
                // F39: the icon changed but the content description never did,
                // so a screen-reader user was told "Pause" in both states — on
                // the one screen where knowing whether the mic is live matters.
                binding.recordButton.setContentDescription(getString(R.string.recorder_pause));
                binding.pauseButton.setContentDescription(getString(R.string.recorder_pause));
                binding.uploadPanel.setVisibility(View.GONE);
                binding.recordPanel.setVisibility(View.VISIBLE);
                break;
            case PAUSED:
                binding.statusLabel.setText(R.string.recorder_status_paused);
                binding.recordButton.setImageResource(R.drawable.ic_play);
                binding.recordButton.setContentDescription(getString(R.string.recorder_resume));
                binding.pauseButton.setContentDescription(getString(R.string.recorder_resume));
                break;
            case STOPPED:
                binding.recordPanel.setVisibility(View.GONE);
                binding.uploadPanel.setVisibility(View.VISIBLE);
                binding.recordedSummary.setText(getString(
                        R.string.recorder_recorded_summary, format(state.elapsedMs)));
                break;
            case IDLE:
            default:
                binding.statusLabel.setText(copying
                        ? R.string.recorder_pick_copying : R.string.recorder_status_idle);
                binding.pauseButton.setVisibility(View.INVISIBLE);
                binding.stopButton.setVisibility(View.INVISIBLE);
                binding.recordButton.setImageResource(R.drawable.ic_tab_mic);
                binding.uploadPanel.setVisibility(View.GONE);
                binding.recordPanel.setVisibility(View.VISIBLE);
                break;
        }
    }

    private void upload() {
        String title = binding.titleInput.getText() == null ? ""
                : binding.titleInput.getText().toString().trim();
        UUID workId;
        if (picked != null) {
            workId = UploadMeetingWorker.enqueue(requireContext(), picked.path,
                    requireArguments().getString(ARG_LEAD, ""), title,
                    picked.seconds, catchUpTypeOrNull(), picked.mime);
            picked = null;
        } else {
            RecorderService.State state = RecorderService.state().getValue();
            if (state == null || state.filePath == null) return;
            workId = UploadMeetingWorker.enqueue(requireContext(), state.filePath,
                    requireArguments().getString(ARG_LEAD, ""), title,
                    Math.max(1, state.elapsedMs / 1000),
                    catchUpTypeOrNull());
        }
        RecorderService.resetState();
        // Grab the activity BEFORE popping — the pop detaches this fragment.
        androidx.fragment.app.FragmentActivity activity = getActivity();
        if (activity instanceof MainActivity) {
            // Replace this screen with the pipeline view (back → lead).
            activity.getOnBackPressedDispatcher().onBackPressed();
            ((MainActivity) activity).push(
                    MeetingDetailFragment.createForUpload(workId.toString()));
        }
    }

    private void discard() {
        if (picked != null) {
            // Only our copy is deleted; the person's original file is untouched,
            // so there is nothing to confirm.
            //noinspection ResultOfMethodCallIgnored
            new File(picked.path).delete();
            picked = null;
            RecorderService.State now = RecorderService.state().getValue();
            if (now != null) render(now);
            return;
        }
        RecorderService.State state = RecorderService.state().getValue();
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.recorder_discard)
                .setMessage(R.string.recorder_discard_confirm)
                .setPositiveButton(R.string.recorder_discard, (d, w) -> {
                    if (state != null && state.filePath != null) {
                        //noinspection ResultOfMethodCallIgnored
                        new File(state.filePath).delete();
                    }
                    RecorderService.resetState();
                    requireActivity().getOnBackPressedDispatcher().onBackPressed();
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void confirmLeave() {
        if (picked != null) {
            // Leaving without uploading: drop the copy, keep the original.
            //noinspection ResultOfMethodCallIgnored
            new File(picked.path).delete();
            picked = null;
        }
        RecorderService.State state = RecorderService.state().getValue();
        boolean live = state != null
                && (state.status == RecorderService.Status.RECORDING
                        || state.status == RecorderService.Status.PAUSED);
        if (!live) {
            requireActivity().getOnBackPressedDispatcher().onBackPressed();
            return;
        }
        // Recording continues in the foreground service; leaving is safe.
        Toast.makeText(requireContext(), R.string.recorder_still_running,
                Toast.LENGTH_LONG).show();
        requireActivity().getOnBackPressedDispatcher().onBackPressed();
    }

    private static String format(long ms) {
        long totalSeconds = ms / 1000;
        return String.format(Locale.US, "%02d:%02d",
                totalSeconds / 60, totalSeconds % 60);
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        // Popped (system back included) with a chosen file never uploaded:
        // drop our copy. A rotation keeps it; onSaveInstanceState carries it.
        if (picked != null && (getActivity() == null
                || !requireActivity().isChangingConfigurations())) {
            //noinspection ResultOfMethodCallIgnored
            new File(picked.path).delete();
            picked = null;
        }
    }
}
