package com.yuvipep.app.feature.assistant.voice;

import android.animation.ObjectAnimator;
import android.animation.ValueAnimator;
import android.app.Dialog;
import android.content.res.ColorStateList;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.GestureDetector;
import android.view.LayoutInflater;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.ImageView;
import android.widget.PopupMenu;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.DialogFragment;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.voice.VoicePlayer;
import com.yuvipep.app.databinding.DialogVoiceStageBinding;
import com.yuvipep.app.feature.assistant.AssistantRepository;
import com.yuvipep.app.feature.assistant.ChatAdapter;
import com.yuvipep.app.feature.assistant.ChatItem;

import java.util.List;

import ai.guiji.duix.sdk.client.DUIX;
import ai.guiji.duix.sdk.client.render.DUIXRenderer;
import ai.guiji.duix.sdk.client.render.DUIXTextureView;
import io.noties.markwon.Markwon;

/**
 * Jarvis's voice screen: a full-screen conversation with the talking avatar
 * (Duix, lip-synced to Jarvis's own voice), live captions of what each side
 * says, and the conversation's cards underneath — the same cards as the chat,
 * so a client draft's chips and an approval work here too.
 *
 * <p>The screen is only a face. The conversation — the voice session, the
 * transcript, the answers and approvals — belongs to the assistant screen
 * that opened it ({@link Host}); this dialog is its child and forwards to it.
 * Closing the screen ends voice mode; the chat carries on underneath.
 */
public class VoiceStageDialog extends DialogFragment {

    public static final String TAG = "jarvis-voice-stage";

    /** DUIXRenderer's SCALE_TYPE_INSIDE (its constants are private). */
    private static final int AVATAR_SCALE_FIT = 1;

    /** The assistant screen hosting the conversation. */
    public interface Host {
        @NonNull VoiceModeController voice();

        @NonNull List<ChatItem> transcript();

        /** For avatar voice samples. */
        @NonNull AssistantRepository repository();

        @NonNull ChatAdapter.Listener chatListener();

        /** Voice mode, (re)started from the screen. */
        void startVoiceFromStage();

        /** A typed turn from the screen's keyboard. */
        void sendFromStage(@NonNull String text);

        /** Who "this" is, for the subtitle; null for nothing. */
        @Nullable String contextTitle();

        void onStageShown(@NonNull VoiceStageDialog stage);

        void onStageGone(@NonNull VoiceStageDialog stage);
    }

    private DialogVoiceStageBinding binding;
    @Nullable private Host host;
    @Nullable private ChatAdapter adapter;

    @Nullable private DUIXRenderer renderer;
    @Nullable private JarvisAvatar.Session avatarSession;
    @Nullable private AvatarSpeechOutput avatarOutput;
    private boolean avatarReady;
    /** The face on screen (and whose voice Jarvis speaks with). */
    @NonNull private AvatarCatalog.Avatar current = AvatarCatalog.byId(null);
    private int videoWidth;
    private int videoHeight;
    /** Plays voice samples when no voice session is running. */
    @Nullable private VoicePlayer samplePlayer;
    private final Handler main = new Handler(Looper.getMainLooper());

    @NonNull private VoiceModeController.State state = VoiceModeController.State.OFF;
    @Nullable private ObjectAnimator dotPulse;

    public static VoiceStageDialog newInstance() {
        return new VoiceStageDialog();
    }

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setStyle(STYLE_NO_FRAME, R.style.Theme_YuviPep_VoiceStage);
    }

    @NonNull
    @Override
    public Dialog onCreateDialog(@Nullable Bundle savedInstanceState) {
        Dialog dialog = super.onCreateDialog(savedInstanceState);
        dialog.setOnKeyListener((d, keyCode, event) -> {
            if (keyCode == android.view.KeyEvent.KEYCODE_BACK
                    && event.getAction() == android.view.KeyEvent.ACTION_UP) {
                endAndClose();
                return true;
            }
            return false;
        });
        return dialog;
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = DialogVoiceStageBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onStart() {
        super.onStart();
        Dialog dialog = getDialog();
        Window window = dialog == null ? null : dialog.getWindow();
        if (window != null) {
            window.setLayout(ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT);
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        }
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        Fragment parent = getParentFragment();
        if (!(parent instanceof Host) || savedInstanceState != null) {
            // Recreated after the process or configuration changed: the voice
            // session did not survive, so neither does its screen.
            dismissAllowingStateLoss();
            return;
        }
        host = (Host) parent;

        adapter = new ChatAdapter(host.transcript(), host.chatListener(),
                Markwon.create(requireContext()));
        LinearLayoutManager layout = new LinearLayoutManager(requireContext());
        layout.setStackFromEnd(true);
        binding.stageTranscript.setLayoutManager(layout);
        binding.stageTranscript.setAdapter(adapter);
        scrollTranscriptToEnd();

        binding.micHalo.setDrawCore(false);
        current = JarvisAvatar.selected(requireContext());
        setCaption(getString(R.string.stage_speaker_jarvis), getString(R.string.stage_hello));

        binding.stageClose.setOnClickListener(v -> endAndClose());
        binding.stageEnd.setOnClickListener(v -> endAndClose());
        binding.stageMic.setOnClickListener(v -> onMicButton());
        binding.stageKeyboard.setOnClickListener(v -> toggleKeyboard());
        binding.stageSend.setOnClickListener(v -> sendTyped());
        binding.stageInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendTyped();
                return true;
            }
            return false;
        });
        binding.stageMenu.setOnClickListener(this::showMenu);
        binding.stageOrb.setOnClickListener(v -> onMicButton());

        host.onStageShown(this);
        setUpPicker();
        showAvatar(current, 0);
        renderState(host.voice().state(), null);
        host.startVoiceFromStage();
    }

    // ── What the host tells the screen ───────────────────────────────

    public void onVoiceState(@NonNull VoiceModeController.State next, @Nullable String detail) {
        if (binding == null) return;
        renderState(next, detail);
    }

    public void onVoiceLevel(float level) {
        if (binding == null) return;
        binding.micHalo.setLevel(level);
        if (binding.stageOrb.getVisibility() == View.VISIBLE) binding.stageOrb.setLevel(level);
    }

    public void onHeard(@NonNull String text) {
        setCaption(getString(R.string.stage_speaker_you), text);
    }

    public void onJarvisSays(@NonNull String text) {
        setCaption(getString(R.string.stage_speaker_jarvis), text);
    }

    /** Jarvis did not act on what it heard: offer the words for editing. */
    public void offerEdit(@NonNull String heard) {
        if (binding == null) return;
        binding.stageTypeRow.setVisibility(View.VISIBLE);
        binding.stageInput.setText(heard);
        binding.stageInput.setSelection(heard.length());
    }

    /**
     * Voice mode ended. Ended by the person (no reason) closes the screen;
     * ended by a problem keeps it open with the reason and a restart button.
     */
    public void onVoiceEnded(@Nullable String reason) {
        if (binding == null) return;
        if (reason == null) {
            dismissAllowingStateLoss();
            return;
        }
        renderState(VoiceModeController.State.OFF, null);
        setCaption(getString(R.string.stage_ended), reason);
    }

    public void transcriptInserted(int position) {
        if (adapter == null) return;
        adapter.notifyItemInserted(position);
        scrollTranscriptToEnd();
    }

    public void transcriptItemChanged(int position) {
        if (adapter != null) adapter.notifyItemChanged(position);
    }

    public void transcriptChanged() {
        if (adapter == null) return;
        adapter.notifyDataSetChanged();
        scrollTranscriptToEnd();
    }

    // ── Controls ─────────────────────────────────────────────────────

    private void onMicButton() {
        if (host == null) return;
        VoiceModeController voice = host.voice();
        switch (state) {
            case OFF:
                host.startVoiceFromStage();
                // A new session starts on the app's own player; the face
                // takes over again once it is running.
                if (avatarOutput != null) voice.useSpeechOutput(avatarOutput);
                break;
            case SPEAKING:
                voice.interrupt();
                break;
            case PAUSED:
                if (voice.isMuted()) voice.setMuted(false);
                else voice.resumeListening();
                break;
            case CONNECTING:
            case RECONNECTING:
                break;
            default:
                voice.setMuted(!voice.isMuted());
                break;
        }
        renderState(voice.state(), null);
    }

    private void toggleKeyboard() {
        boolean show = binding.stageTypeRow.getVisibility() != View.VISIBLE;
        binding.stageTypeRow.setVisibility(show ? View.VISIBLE : View.GONE);
        android.view.inputmethod.InputMethodManager imm =
                (android.view.inputmethod.InputMethodManager) requireContext()
                        .getSystemService(android.content.Context.INPUT_METHOD_SERVICE);
        if (show) {
            binding.stageInput.requestFocus();
            if (imm != null) {
                imm.showSoftInput(binding.stageInput,
                        android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);
            }
        } else if (imm != null) {
            imm.hideSoftInputFromWindow(binding.stageInput.getWindowToken(), 0);
        }
    }

    private void sendTyped() {
        if (host == null || binding.stageInput.getText() == null) return;
        String text = binding.stageInput.getText().toString().trim();
        if (text.isEmpty()) return;
        binding.stageInput.setText("");
        setCaption(getString(R.string.stage_speaker_you), text);
        host.sendFromStage(text);
    }

    private void endAndClose() {
        if (host != null && host.voice().isActive()) host.voice().stop();
        dismissAllowingStateLoss();
    }

    private void showMenu(@NonNull View anchor) {
        PopupMenu menu = new PopupMenu(requireContext(), anchor);
        boolean supported = JarvisAvatar.deviceSupported();
        boolean hidden = JarvisAvatar.hidden(requireContext());
        if (supported) {
            menu.getMenu().add(0, 1, 0, hidden
                    ? R.string.stage_menu_show_faces : R.string.stage_menu_voice_only);
            if (JarvisAvatar.downloaded(requireContext(), current)) {
                menu.getMenu().add(0, 2, 1, getString(R.string.stage_menu_delete_face,
                        current.name, current.sizeMb));
            }
        }
        if (host != null && VoiceModeController.bargeInSupported() && !avatarReady) {
            menu.getMenu().add(0, 3, 2, R.string.voice_mode_barge_in)
                    .setCheckable(true)
                    .setChecked(host.voice().bargeInPreferred());
        }
        if (com.yuvipep.app.BuildConfig.DEBUG) {
            menu.getMenu().add(0, 4, 3, "Speech test recorder");
        }
        menu.setOnMenuItemClickListener(item -> {
            switch (item.getItemId()) {
                case 1:
                    JarvisAvatar.setHidden(requireContext(), !hidden);
                    showAvatar(current, 0);
                    return true;
                case 2:
                    releaseAvatar();
                    JarvisAvatar.deleteDownload(requireContext(), current);
                    Toast.makeText(requireContext(),
                            getString(R.string.stage_avatar_deleted_named, current.name),
                            Toast.LENGTH_SHORT).show();
                    showAvatar(current, 0);
                    return true;
                case 3:
                    if (host != null) {
                        boolean on = !host.voice().bargeInPreferred();
                        host.voice().setBargeInPreferred(on);
                        Toast.makeText(requireContext(), on ? R.string.voice_mode_barge_in_on
                                : R.string.voice_mode_barge_in_off, Toast.LENGTH_LONG).show();
                    }
                    return true;
                case 4:
                    // The recorder needs the microphone to itself: voice mode ends.
                    SpeechEvalDialog.newInstance()
                            .show(getParentFragmentManager(), SpeechEvalDialog.TAG);
                    endAndClose();
                    return true;
                default:
                    return false;
            }
        });
        menu.show();
    }

    // ── Avatar picker ────────────────────────────────────────────────

    /** Swipes on the face area move between avatars. */
    @SuppressWarnings("ClickableViewAccessibility")
    private void setUpPicker() {
        GestureDetector swipe = new GestureDetector(requireContext(),
                new GestureDetector.SimpleOnGestureListener() {
                    @Override
                    public boolean onDown(@NonNull MotionEvent e) {
                        return true;
                    }

                    @Override
                    public boolean onFling(@Nullable MotionEvent e1, @NonNull MotionEvent e2,
                                           float vx, float vy) {
                        if (e1 == null) return false;
                        float dx = e2.getX() - e1.getX();
                        float dy = e2.getY() - e1.getY();
                        if (Math.abs(dx) < dp(48) || Math.abs(dx) < Math.abs(dy)) return false;
                        // Swipe left = the next face, like turning a page.
                        stepAvatar(dx < 0 ? 1 : -1);
                        return true;
                    }

                    @Override
                    public boolean onSingleTapUp(@NonNull MotionEvent e) {
                        if (state == VoiceModeController.State.SPEAKING
                                || state == VoiceModeController.State.PAUSED
                                || state == VoiceModeController.State.OFF) {
                            onMicButton();
                            return true;
                        }
                        return false;
                    }
                });
        binding.stageFace.setOnTouchListener((v, event) -> swipe.onTouchEvent(event));
        binding.avatarPrev.setOnClickListener(v -> stepAvatar(-1));
        binding.avatarNext.setOnClickListener(v -> stepAvatar(1));
        binding.avatarHear.setOnClickListener(v -> playSample(current));

        binding.avatarDots.removeAllViews();
        for (int i = 0; i < AvatarCatalog.ALL.size(); i++) {
            View dot = new View(requireContext());
            android.widget.LinearLayout.LayoutParams lp =
                    new android.widget.LinearLayout.LayoutParams(dp(6), dp(6));
            lp.setMargins(dp(3), 0, dp(3), 0);
            dot.setBackgroundResource(R.drawable.bg_stage_dot);
            binding.avatarDots.addView(dot, lp);
        }
        // Re-shape the frame once the face area has its real size.
        binding.stageFace.addOnLayoutChangeListener((v, l, t, r, b, ol, ot, orr, ob) -> {
            if (r - l != orr - ol || b - t != ob - ot) layoutFrame();
        });
    }

    private void stepAvatar(int step) {
        showAvatar(AvatarCatalog.step(current, step), step);
    }

    /**
     * Put {@code avatar} on screen: its voice at once, its face live if it is
     * on the phone, otherwise its picture, a sample of its voice and a
     * Download button. {@code direction} is where it slides in from.
     */
    private void showAvatar(@NonNull AvatarCatalog.Avatar avatar, int direction) {
        if (binding == null || host == null) return;
        main.removeCallbacks(pendingSample);
        boolean changed = avatar != current;
        current = avatar;
        JarvisAvatar.select(requireContext(), avatar);
        host.voice().setVoice(avatar.voice);
        if (changed && state == VoiceModeController.State.SPEAKING) host.voice().interrupt();
        releaseAvatar();

        binding.stageSubtitle.setText(getString(R.string.stage_avatar_subtitle,
                avatar.name, avatar.voiceLabel));
        for (int i = 0; i < binding.avatarDots.getChildCount(); i++) {
            binding.avatarDots.getChildAt(i)
                    .setAlpha(i == AvatarCatalog.indexOf(avatar.id) ? 1f : 0.3f);
        }
        binding.avatarNameTagText.setText(avatar.name);
        binding.avatarLiveDot.setVisibility(View.GONE);
        binding.avatarPreview.setImageResource(avatar.preview);
        binding.avatarPreview.setScaleType(avatar.cutout
                ? ImageView.ScaleType.FIT_CENTER : ImageView.ScaleType.CENTER_CROP);
        binding.avatarPreview.setAlpha(1f);
        videoWidth = 0;
        videoHeight = 0;
        layoutFrame();

        if (direction != 0) {
            View frame = binding.avatarFrame;
            frame.setTranslationX(direction * frame.getWidth() * 0.35f);
            frame.setAlpha(0f);
            frame.animate().translationX(0f).alpha(1f).setDuration(260)
                    .setInterpolator(new android.view.animation.DecelerateInterpolator()).start();
        }

        boolean supported = JarvisAvatar.deviceSupported();
        boolean hidden = JarvisAvatar.hidden(requireContext());
        binding.avatarFrame.setVisibility(hidden ? View.GONE : View.VISIBLE);
        binding.stageOrb.setVisibility(hidden ? View.VISIBLE : View.GONE);
        if (hidden) {
            showAvatarSetup(false);
            return;
        }
        if (!supported) {
            showAvatarCard(avatar.name, getString(R.string.stage_avatar_unsupported_body,
                    avatar.name), false, false);
            if (changed && direction != 0) schedulePendingSample(avatar);
            return;
        }
        String downloading = JarvisAvatar.downloadingId();
        if (JarvisAvatar.downloaded(requireContext(), avatar) || avatar.id.equals(downloading)) {
            loadAvatar(avatar);
            return;
        }
        showAvatarCard(avatar.name, getString(R.string.stage_avatar_offer_body2,
                avatar.voiceLabel), true, downloading == null);
        if (changed && direction != 0) schedulePendingSample(avatar);
    }

    /** The picture-and-buttons card for a face that is not running. */
    private void showAvatarCard(@NonNull String title, @NonNull String body,
                                boolean offerDownload, boolean downloadEnabled) {
        showAvatarSetup(true);
        binding.avatarSetupTitle.setText(title);
        binding.avatarSetupBody.setText(body);
        binding.avatarProgress.setVisibility(View.GONE);
        binding.avatarSetupButtons.setVisibility(View.VISIBLE);
        binding.avatarDownload.setVisibility(offerDownload ? View.VISIBLE : View.GONE);
        binding.avatarDownload.setEnabled(downloadEnabled);
        binding.avatarDownload.setText(getString(R.string.stage_avatar_download_mb,
                JarvisAvatar.remainingMb(requireContext(), current)));
        AvatarCatalog.Avatar avatar = current;
        binding.avatarDownload.setOnClickListener(v -> {
            if (JarvisAvatar.downloadingId() != null) {
                Toast.makeText(requireContext(), R.string.stage_avatar_busy,
                        Toast.LENGTH_SHORT).show();
                return;
            }
            loadAvatar(avatar);
        });
    }

    private final Runnable pendingSample = () -> {
        if (binding != null) playSample(current);
    };

    /** A face you have just swiped to says hello, once you stop on it. */
    private void schedulePendingSample(@NonNull AvatarCatalog.Avatar avatar) {
        main.removeCallbacks(pendingSample);
        main.postDelayed(pendingSample, 700);
    }

    private void playSample(@NonNull AvatarCatalog.Avatar avatar) {
        if (host == null) return;
        setCaption(avatar.name, avatar.sample);
        host.repository().voiceSample(requireContext().getCacheDir(), avatar.sample,
                avatar.voice, result -> {
                    if (binding == null || host == null || current != avatar) return;
                    VoicePlayer.Pcm pcm = result.isSuccess() && result.data != null
                            ? VoicePlayer.decodeWav(result.data) : null;
                    if (pcm == null) {
                        if (result.error != null) {
                            Toast.makeText(requireContext(), result.error.message,
                                    Toast.LENGTH_SHORT).show();
                        }
                        return;
                    }
                    if (host.voice().isActive()) {
                        host.voice().playClip(pcm);
                    } else {
                        if (samplePlayer == null) samplePlayer = new VoicePlayer(null);
                        samplePlayer.stopNow();
                        samplePlayer.setSampleRate(pcm.sampleRate);
                        samplePlayer.play(pcm.data);
                        samplePlayer.endOfSpeech();
                    }
                });
    }

    private void loadAvatar(@NonNull AvatarCatalog.Avatar avatar) {
        if (binding == null || avatarSession != null) return;
        main.removeCallbacks(pendingSample);
        showAvatarSetup(true);
        binding.avatarSetupTitle.setText(getString(R.string.stage_avatar_getting_ready,
                avatar.name));
        binding.avatarSetupBody.setText("");
        binding.avatarSetupButtons.setVisibility(View.GONE);
        binding.avatarProgress.setVisibility(View.VISIBLE);
        binding.avatarProgress.setIndeterminate(true);

        if (renderer == null) {
            // A fresh view each time: Duix takes one renderer per view, and
            // the renderer must be set before the view gets a surface.
            DUIXTextureView view = new DUIXTextureView(requireContext());
            renderer = new DUIXRenderer(requireContext(), view);
            // Fit, not Duix's default centre-crop: the frame is already shaped
            // to the video, and a cut-out must never lose the top of its head.
            renderer.setScaleType(AVATAR_SCALE_FIT);
            view.setEGLContextClientVersion(2);
            view.setEGLConfigChooser(8, 8, 8, 8, 16, 0);
            view.setOpaque(false);
            view.setRenderer(renderer);
            view.setRenderMode(DUIXTextureView.RENDERMODE_WHEN_DIRTY);
            binding.avatarHolder.addView(view, new android.widget.FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }
        avatarSession = JarvisAvatar.load(requireContext(), renderer, avatar,
                new JarvisAvatar.Listener() {
            @Override
            public void onAvatarProgress(@NonNull String step, int percent) {
                if (binding == null || current != avatar) return;
                binding.avatarSetupBody.setText(step.isEmpty() ? "" : step + "  " + percent + "%");
                binding.avatarProgress.setIndeterminate(percent <= 0 || percent >= 100);
                if (percent > 0 && percent < 100) {
                    binding.avatarProgress.setProgressCompat(percent, true);
                }
            }

            @Override
            public void onAvatarReady(@NonNull DUIX duix, int width, int height) {
                if (binding == null || host == null || current != avatar) return;
                avatarReady = true;
                videoWidth = width;
                videoHeight = height;
                layoutFrame();
                avatarOutput = new AvatarSpeechOutput(requireContext(), duix);
                host.voice().useSpeechOutput(avatarOutput);
                showAvatarSetup(false);
                binding.avatarLiveDot.setVisibility(View.VISIBLE);
                binding.avatarHolder.animate().alpha(1f).setDuration(450).start();
                binding.avatarPreview.animate().alpha(0f).setDuration(450).start();
            }

            @Override
            public void onAvatarFailed(@NonNull String message) {
                if (binding == null || current != avatar) return;
                releaseAvatar();
                showAvatarCard(getString(R.string.stage_avatar_failed_title, avatar.name),
                        message, true, JarvisAvatar.downloadingId() == null);
                binding.avatarDownload.setText(R.string.stage_avatar_retry);
            }

            @Override
            public void onAvatarPlayEnd() {
                AvatarSpeechOutput output = avatarOutput;
                if (output != null) output.onDuixPlayEnd();
            }
        });
    }

    private void releaseAvatar() {
        avatarReady = false;
        if (avatarOutput != null) {
            if (host != null) host.voice().useDefaultSpeechOutput(avatarOutput);
            avatarOutput.release();
            avatarOutput = null;
        }
        if (avatarSession != null) {
            avatarSession.release();
            avatarSession = null;
        }
        renderer = null;
        if (binding != null) {
            binding.avatarHolder.animate().cancel();
            binding.avatarHolder.setAlpha(0f);
            binding.avatarHolder.removeAllViews();
            binding.avatarPreview.animate().cancel();
            binding.avatarPreview.setAlpha(1f);
            binding.avatarLiveDot.setVisibility(View.GONE);
        }
    }

    private void showAvatarSetup(boolean show) {
        if (binding == null) return;
        binding.avatarSetup.setVisibility(show ? View.VISIBLE : View.GONE);
        // Always above the face (which casts a shadow, so sits higher by default).
        binding.avatarSetup.setElevation(dp(16));
        // A video window makes room for the card rather than hiding under it.
        binding.avatarSetup.post(this::layoutFrame);
    }

    /**
     * Shape the face: the whole area for a cut-out; for a video, a rounded
     * window with the video's own proportions, clear of the top bar and the
     * status pill, like the other side of a video call.
     */
    private void layoutFrame() {
        if (binding == null) return;
        View face = binding.stageFace;
        View frame = binding.avatarFrame;
        int fw = face.getWidth();
        int fh = face.getHeight();
        if (fw == 0 || fh == 0) return;
        android.widget.FrameLayout.LayoutParams lp =
                (android.widget.FrameLayout.LayoutParams) frame.getLayoutParams();
        if (current.cutout) {
            lp.width = ViewGroup.LayoutParams.MATCH_PARENT;
            lp.height = ViewGroup.LayoutParams.MATCH_PARENT;
            lp.topMargin = 0;
            lp.gravity = android.view.Gravity.TOP | android.view.Gravity.CENTER_HORIZONTAL;
            frame.setClipToOutline(false);
            frame.setForeground(null);
            frame.setElevation(0f);
            binding.avatarNameTag.setVisibility(View.GONE);
        } else {
            float aspect;
            if (videoWidth > 0 && videoHeight > 0) {
                aspect = (float) videoWidth / videoHeight;
            } else {
                android.graphics.drawable.Drawable d = binding.avatarPreview.getDrawable();
                aspect = d != null && d.getIntrinsicHeight() > 0
                        ? (float) d.getIntrinsicWidth() / d.getIntrinsicHeight() : 9f / 16f;
            }
            int top = binding.stageTopBar.getBottom() + dp(4);
            int availW = fw - dp(64);
            int bottom = fh - dp(60);   // clear of the status pill
            View card = binding.avatarSetup;
            if (card.getVisibility() == View.VISIBLE && card.getHeight() > 0) {
                bottom = Math.min(bottom, card.getTop() - dp(10));
            }
            int availH = Math.max(bottom - top, dp(120));
            int h = availH;
            int w = Math.round(h * aspect);
            if (w > availW) {
                w = availW;
                h = Math.round(w / aspect);
            }
            lp.width = w;
            lp.height = h;
            lp.topMargin = top + (availH - h) / 2;
            lp.gravity = android.view.Gravity.TOP | android.view.Gravity.CENTER_HORIZONTAL;
            frame.setOutlineProvider(new android.view.ViewOutlineProvider() {
                @Override
                public void getOutline(View view, android.graphics.Outline outline) {
                    outline.setRoundRect(0, 0, view.getWidth(), view.getHeight(), dp(28));
                }
            });
            frame.setClipToOutline(true);
            frame.setForeground(androidx.core.content.ContextCompat.getDrawable(
                    requireContext(), R.drawable.bg_avatar_call_frame));
            frame.setElevation(dp(8));
            binding.avatarNameTag.setVisibility(View.VISIBLE);
        }
        frame.setLayoutParams(lp);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    // ── Rendering ────────────────────────────────────────────────────

    private void renderState(@NonNull VoiceModeController.State next, @Nullable String detail) {
        state = next;
        boolean muted = host != null && host.voice().isMuted();
        binding.micHalo.setState(muted ? VoiceModeController.State.PAUSED : next);
        binding.stageOrb.setState(next);

        int label;
        int dot;
        int icon;
        int description;
        switch (next) {
            case CONNECTING:
                label = R.string.voice_state_connecting;
                dot = R.color.stage_on_faint;
                icon = R.drawable.ic_mic;
                description = R.string.stage_mic_listening;
                break;
            case RECONNECTING:
                label = R.string.voice_state_reconnecting;
                dot = R.color.stage_on_faint;
                icon = R.drawable.ic_cloud_off;
                description = R.string.stage_mic_listening;
                break;
            case HEARING:
                label = R.string.voice_state_hearing;
                dot = R.color.brand_accent;
                icon = R.drawable.ic_mic;
                description = R.string.stage_mic_listening;
                if (host != null) setCaption(getString(R.string.stage_speaker_you),
                        getString(R.string.stage_hearing));
                break;
            case TRANSCRIBING:
                label = R.string.voice_state_transcribing;
                dot = R.color.brand_accent;
                icon = R.drawable.ic_mic;
                description = R.string.stage_mic_listening;
                break;
            case THINKING:
                label = R.string.voice_state_thinking;
                dot = R.color.stage_accent;
                icon = R.drawable.ic_mic;
                description = R.string.stage_mic_listening;
                break;
            case SPEAKING:
                label = R.string.voice_state_speaking;
                dot = R.color.stage_accent;
                icon = R.drawable.ic_stop;
                description = R.string.stage_mic_stop;
                break;
            case PAUSED:
                label = muted ? R.string.stage_muted : R.string.voice_state_paused;
                dot = R.color.stage_on_faint;
                icon = muted ? R.drawable.ic_mic_off : R.drawable.ic_play;
                description = muted ? R.string.stage_mic_muted : R.string.stage_mic_resume;
                break;
            case OFF:
                label = R.string.stage_ended;
                dot = R.color.stage_end;
                icon = R.drawable.ic_play;
                description = R.string.stage_mic_restart;
                break;
            case LISTENING:
            default:
                label = muted ? R.string.stage_muted : R.string.voice_state_listening;
                dot = muted ? R.color.stage_on_faint : R.color.stage_accent;
                icon = muted ? R.drawable.ic_mic_off : R.drawable.ic_mic;
                description = muted ? R.string.stage_mic_muted : R.string.stage_mic_listening;
                break;
        }
        binding.statusText.setText(label);
        if (detail != null && next == VoiceModeController.State.THINKING) {
            binding.statusText.setText(detail);
        }
        int dotColor = androidx.core.content.ContextCompat.getColor(requireContext(), dot);
        binding.statusDot.setBackgroundTintList(ColorStateList.valueOf(dotColor));
        binding.stageMic.setIconResource(icon);
        binding.stageMic.setContentDescription(getString(description));
        // A muted mic reads as "off": dim button, slashed meaning in words.
        binding.stageMic.setAlpha(muted ? 0.55f : 1f);

        boolean pulse = next == VoiceModeController.State.LISTENING && !muted
                || next == VoiceModeController.State.HEARING
                || next == VoiceModeController.State.SPEAKING;
        if (pulse) startDotPulse();
        else stopDotPulse();
    }

    private void setCaption(@NonNull String speaker, @NonNull String text) {
        if (binding == null) return;
        binding.captionSpeaker.setText(speaker);
        if (!text.contentEquals(binding.captionText.getText())) {
            binding.captionText.setAlpha(0f);
            binding.captionText.setText(stripMarkdown(text));
            binding.captionText.animate().alpha(1f).setDuration(220).start();
        }
    }

    /** Captions are read at a glance: no asterisks or link syntax. */
    @NonNull
    static String stripMarkdown(@NonNull String text) {
        return text.replaceAll("\\[([^\\]]+)]\\([^)]*\\)", "$1")
                .replaceAll("[*_`#>]+", "")
                .replaceAll("\\s+", " ")
                .trim();
    }

    private void scrollTranscriptToEnd() {
        if (binding == null || host == null) return;
        int count = host.transcript().size();
        if (count > 0) binding.stageTranscript.scrollToPosition(count - 1);
    }

    private void startDotPulse() {
        if (dotPulse != null) return;
        dotPulse = ObjectAnimator.ofFloat(binding.statusDot, View.ALPHA, 1f, 0.25f);
        dotPulse.setDuration(700);
        dotPulse.setRepeatMode(ValueAnimator.REVERSE);
        dotPulse.setRepeatCount(ValueAnimator.INFINITE);
        dotPulse.start();
    }

    private void stopDotPulse() {
        if (dotPulse != null) {
            dotPulse.cancel();
            dotPulse = null;
        }
        if (binding != null) binding.statusDot.setAlpha(1f);
    }

    @Override
    public void onDestroyView() {
        stopDotPulse();
        main.removeCallbacksAndMessages(null);
        if (samplePlayer != null) {
            samplePlayer.release();
            samplePlayer = null;
        }
        Host leaving = host;
        if (leaving != null) {
            // Forget the screen first, so ending voice mode does not call back
            // into a screen that is going away.
            leaving.onStageGone(this);
            if (leaving.voice().isActive()) leaving.voice().stop();
        }
        releaseAvatar();
        host = null;
        adapter = null;
        binding = null;
        super.onDestroyView();
    }
}
