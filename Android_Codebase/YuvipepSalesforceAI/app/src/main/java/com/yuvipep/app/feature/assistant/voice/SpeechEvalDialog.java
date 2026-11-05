package com.yuvipep.app.feature.assistant.voice;

import android.Manifest;
import android.app.Dialog;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.DialogFragment;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.button.MaterialButtonToggleGroup;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.core.voice.MicStreamer;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * Debug builds only: records the {@link SpeechEvalPrompts} sentences, one WAV
 * per sentence and capture mode, so speech recognition can be measured on
 * real voices rather than synthetic ones.
 *
 * <p>Nothing leaves the phone from here. Files go to the app's private
 * storage ({@code files/speech_eval/<mode>/<id>.wav} plus
 * {@code manifest.jsonl}) and are pulled over adb with {@code run-as}; "Delete
 * all" removes them. The recording is the raw microphone stream, silence
 * included, so the server's end-of-turn detector can be replayed over it.
 */
public class SpeechEvalDialog extends DialogFragment {

    public static final String TAG = "speech-eval-recorder";
    public static final String DIR = "speech_eval";
    private static final int SAMPLE_RATE = 16_000;
    private static final long MAX_RECORD_MS = 20_000;

    private final Handler main = new Handler(Looper.getMainLooper());
    @NonNull private MicStreamer.CaptureMode mode = MicStreamer.CaptureMode.COMMUNICATION;
    private int index;

    @Nullable private MicStreamer mic;
    @Nullable private ByteArrayOutputStream buffer;
    private long startedAt;
    private volatile boolean capturing;

    private TextView progress;
    private TextView promptText;
    private TextView status;
    private TextView counts;
    private MaterialButton record;

    public static SpeechEvalDialog newInstance() {
        return new SpeechEvalDialog();
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
        }
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        Context c = requireContext();
        LinearLayout root = new LinearLayout(c);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(16);
        root.setPadding(pad, pad, pad, pad);

        TextView title = text(c, "Speech test recorder", 20);
        root.addView(title);
        root.addView(text(c, "Read each sentence the way you would say it to Jarvis, holding "
                + "the phone as you do in voice mode. Tap Record, wait a moment, speak, "
                + "wait a moment, tap Stop. Recordings stay on this phone until they are "
                + "pulled for testing. Delete all removes them.", 14));

        MaterialButtonToggleGroup modes = new MaterialButtonToggleGroup(c);
        modes.setSingleSelection(true);
        modes.setSelectionRequired(true);
        for (MicStreamer.CaptureMode m : MicStreamer.CaptureMode.values()) {
            MaterialButton b = new MaterialButton(c, null,
                    com.google.android.material.R.attr.materialButtonOutlinedStyle);
            b.setId(View.generateViewId());
            b.setText(label(m));
            b.setAllCaps(false);
            b.setTag(m);
            modes.addView(b);
            if (m == mode) modes.check(b.getId());
        }
        modes.addOnButtonCheckedListener((group, id, checked) -> {
            if (!checked || capturing) return;
            mode = (MicStreamer.CaptureMode) group.findViewById(id).getTag();
            index = firstMissing();
            render();
        });
        root.addView(modes, wrapWidth(dp(12)));

        progress = text(c, "", 14);
        root.addView(progress, wrapWidth(dp(16)));

        ScrollView promptScroll = new ScrollView(c);
        promptText = text(c, "", 28);
        promptText.setGravity(Gravity.CENTER);
        promptScroll.addView(promptText);
        root.addView(promptScroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        status = text(c, "", 14);
        status.setGravity(Gravity.CENTER);
        root.addView(status, wrapWidth(dp(8)));

        LinearLayout controls = new LinearLayout(c);
        controls.setGravity(Gravity.CENTER);
        MaterialButton back = new MaterialButton(c, null,
                com.google.android.material.R.attr.materialButtonOutlinedStyle);
        back.setText("Back");
        back.setOnClickListener(v -> move(-1));
        record = new MaterialButton(c);
        record.setOnClickListener(v -> toggleRecording());
        MaterialButton skip = new MaterialButton(c, null,
                com.google.android.material.R.attr.materialButtonOutlinedStyle);
        skip.setText("Skip");
        skip.setOnClickListener(v -> move(1));
        controls.addView(back);
        LinearLayout.LayoutParams mid = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        mid.setMargins(dp(12), 0, dp(12), 0);
        controls.addView(record, mid);
        controls.addView(skip);
        root.addView(controls, wrapWidth(dp(12)));

        counts = text(c, "", 12);
        root.addView(counts, wrapWidth(dp(16)));

        LinearLayout footer = new LinearLayout(c);
        footer.setGravity(Gravity.END);
        MaterialButton delete = new MaterialButton(c, null,
                com.google.android.material.R.attr.materialButtonOutlinedStyle);
        delete.setText("Delete all");
        delete.setOnClickListener(v -> confirmDeleteAll());
        MaterialButton close = new MaterialButton(c, null,
                com.google.android.material.R.attr.materialButtonOutlinedStyle);
        close.setText("Close");
        close.setOnClickListener(v -> dismissAllowingStateLoss());
        footer.addView(delete);
        footer.addView(close);
        root.addView(footer, wrapWidth(dp(4)));

        index = firstMissing();
        render();
        return root;
    }

    @Override
    public void onPause() {
        super.onPause();
        if (capturing) stopRecording(false);
    }

    // ── Recording ────────────────────────────────────────────────────

    private void toggleRecording() {
        if (capturing) {
            stopRecording(true);
            return;
        }
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(requireContext(), "Allow the microphone for Jarvis first "
                    + "(open voice mode once).", Toast.LENGTH_LONG).show();
            return;
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream(SAMPLE_RATE * 2 * 5);
        buffer = out;
        capturing = true;
        startedAt = SystemClock.elapsedRealtime();
        MicStreamer m = new MicStreamer(mode);
        mic = m;
        //noinspection MissingPermission — checked above
        m.start(new MicStreamer.Sink() {
            @Override
            public void onFrame(@NonNull byte[] frame) {
                synchronized (out) {
                    if (capturing) out.write(frame, 0, frame.length);
                }
            }

            @Override
            public void onLevel(float level) {
                if (!capturing || status == null) return;
                long ms = SystemClock.elapsedRealtime() - startedAt;
                status.setText(String.format(java.util.Locale.US, "Recording %.1f s  %s",
                        ms / 1000.0, bar(level)));
                if (ms > MAX_RECORD_MS) stopRecording(true);
            }

            @Override
            public void onMicError(@NonNull String message) {
                stopRecording(false);
                if (status != null) status.setText(message);
            }
        });
        render();
    }

    private void stopRecording(boolean keep) {
        if (!capturing) return;
        capturing = false;
        if (mic != null) mic.stop();
        mic = null;
        ByteArrayOutputStream out = buffer;
        buffer = null;
        if (!keep || out == null) {
            render();
            return;
        }
        byte[] pcm;
        synchronized (out) {
            pcm = out.toByteArray();
        }
        SpeechEvalPrompts.Prompt prompt = SpeechEvalPrompts.ALL.get(index);
        try {
            save(prompt, pcm);
            status.setText(String.format(java.util.Locale.US, "Saved %s (%.1f s)",
                    prompt.id, pcm.length / 2.0 / SAMPLE_RATE));
            if (index < SpeechEvalPrompts.ALL.size() - 1) index++;
        } catch (IOException | JSONException e) {
            status.setText("Could not save: " + e.getMessage());
        }
        render();
    }

    private void save(@NonNull SpeechEvalPrompts.Prompt prompt, @NonNull byte[] pcm)
            throws IOException, JSONException {
        File root = new File(requireContext().getFilesDir(), DIR);
        File dir = new File(root, mode.key);
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("no folder " + dir);
        File wav = new File(dir, prompt.id + ".wav");
        try (FileOutputStream f = new FileOutputStream(wav)) {
            f.write(SpeechEvalPrompts.wav(pcm, SAMPLE_RATE));
        }
        JSONObject line = new JSONObject()
                .put("id", prompt.id)
                .put("text", prompt.marked)
                .put("mode", mode.key)
                .put("file", mode.key + "/" + wav.getName())
                .put("seconds", pcm.length / 2.0 / SAMPLE_RATE)
                .put("device", Build.MANUFACTURER + " " + Build.MODEL)
                .put("sdk", Build.VERSION.SDK_INT)
                .put("recorded_at", System.currentTimeMillis());
        try (FileOutputStream f = new FileOutputStream(new File(root, "manifest.jsonl"), true)) {
            f.write((line + "\n").getBytes(StandardCharsets.UTF_8));
        }
    }

    private void confirmDeleteAll() {
        new MaterialAlertDialogBuilder(requireContext())
                .setMessage("Delete every speech test recording on this phone?")
                .setPositiveButton("Delete", (d, w) -> {
                    if (capturing) stopRecording(false);
                    deleteTree(new File(requireContext().getFilesDir(), DIR));
                    index = 0;
                    render();
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    // ── Rendering ────────────────────────────────────────────────────

    private void move(int step) {
        if (capturing) return;
        index = Math.max(0, Math.min(SpeechEvalPrompts.ALL.size() - 1, index + step));
        status.setText("");
        render();
    }

    private void render() {
        if (promptText == null) return;
        SpeechEvalPrompts.Prompt prompt = SpeechEvalPrompts.ALL.get(index);
        boolean done = recorded(mode, prompt);
        progress.setText(String.format(java.util.Locale.US, "%d / %d  ·  %s  ·  %s%s",
                index + 1, SpeechEvalPrompts.ALL.size(), prompt.id, label(mode),
                done ? "  ·  recorded (Record again replaces it)" : ""));
        promptText.setText(prompt.display());
        record.setText(capturing ? "Stop" : "Record");
        StringBuilder sb = new StringBuilder("Recorded: ");
        MicStreamer.CaptureMode[] all = MicStreamer.CaptureMode.values();
        for (int i = 0; i < all.length; i++) {
            if (i > 0) sb.append("  ·  ");
            sb.append(label(all[i])).append(' ').append(count(all[i]))
                    .append('/').append(SpeechEvalPrompts.ALL.size());
        }
        counts.setText(sb);
    }

    private int firstMissing() {
        for (int i = 0; i < SpeechEvalPrompts.ALL.size(); i++) {
            if (!recorded(mode, SpeechEvalPrompts.ALL.get(i))) return i;
        }
        return 0;
    }

    private boolean recorded(@NonNull MicStreamer.CaptureMode m,
                             @NonNull SpeechEvalPrompts.Prompt prompt) {
        return new File(new File(new File(requireContext().getFilesDir(), DIR), m.key),
                prompt.id + ".wav").isFile();
    }

    private int count(@NonNull MicStreamer.CaptureMode m) {
        int n = 0;
        for (SpeechEvalPrompts.Prompt prompt : SpeechEvalPrompts.ALL) {
            if (recorded(m, prompt)) n++;
        }
        return n;
    }

    @NonNull
    private static String label(@NonNull MicStreamer.CaptureMode m) {
        switch (m) {
            case COMMUNICATION_NO_NS:
                return "No noise filter";
            case RECOGNITION:
                return "Recognition";
            default:
                return "Current";
        }
    }

    @NonNull
    private static String bar(float level) {
        int n = Math.round(Math.max(0f, Math.min(1f, level)) * 10);
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 10; i++) sb.append(i < n ? '█' : '·');
        return sb.toString();
    }

    private static void deleteTree(@NonNull File file) {
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) deleteTree(child);
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
    }

    @NonNull
    private TextView text(@NonNull Context c, @NonNull String s, int sp) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        return t;
    }

    @NonNull
    private LinearLayout.LayoutParams wrapWidth(int topMargin) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = topMargin;
        return lp;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
