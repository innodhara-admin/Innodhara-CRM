package com.yuvipep.app.core.voice;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.MediaRecorder;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.DictationResponse;
import com.yuvipep.app.core.util.AppExecutors;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;

import dagger.hilt.EntryPoint;
import dagger.hilt.InstallIn;
import dagger.hilt.android.EntryPointAccessors;
import dagger.hilt.components.SingletonComponent;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.RequestBody;
import retrofit2.Response;

/**
 * Speech-to-text for commands and dictation (04 §3).
 *
 * <h3>Why this no longer uses Android's recognizer</h3>
 * It used to be {@link SpeechRecognizer} throughout. That is a fine API and a
 * poor transcriber for this app in particular: the words that matter here are
 * client names, company names and sales jargon, and a general-purpose acoustic
 * model mangles exactly those. The backend already runs open-source Whisper
 * and already gets them right on meeting audio — so dictation now records a
 * few seconds locally and posts them to {@code POST /api/v1/dictate}, which
 * runs Whisper at a small, fast size (DICTATION_WHISPER_MODEL, "tiny") chosen
 * for latency because a human is waiting with the keyboard open.
 *
 * <p>Still the COMMAND path only — meeting audio does not come through here.
 * It is recorded and uploaded to the pipeline's own Whisper (08 §3), and that
 * pipeline is untouched by any of this.
 *
 * <h3>Offline</h3>
 * Whisper lives on the server, so with no connection there is nothing to post
 * to. Rather than refuse, dictation falls back to the on-device recognizer —
 * less accurate, but a mic that still works beats a mic that apologises. The
 * choice is made once, at {@link #start}, from the live network state.
 *
 * <h3>Shape of a session</h3>
 * On the Whisper path there are no live partials — Whisper transcribes a
 * finished clip, not a stream. Callers get {@link Listener#onTranscribing()}
 * when recording stops and the upload begins, then a single
 * {@link Listener#onFinal}. On the device-recognizer fallback, partials arrive
 * as they always did. Either way {@link Listener#onEnd} is the last call.
 *
 * <p>One instance per listening session owner; call {@link #destroy()} when the
 * owning view/fragment goes away.
 */
public final class SpeechInput {

    public interface Listener {
        /** Live partial hypothesis — replace, don't append. Only ever called
         *  on the offline device-recognizer path; Whisper has no partials. */
        void onPartial(@NonNull String text);

        /** Final recognized text for this session. */
        void onFinal(@NonNull String text);

        /**
         * Same final text, plus the server's verdict on whether it actually
         * heard well ({@code low_confidence}, the 0.6 gate defined server-side).
         *
         * <p>Only matters to a caller that ACTS on the text without the user
         * reading it first — the assistant sends automatically. A caller that
         * merely drops the words into a field the user is looking at can ignore
         * this and keep using the one-argument form.
         *
         * <p>Defaulted so the existing anonymous Listeners keep compiling
         * untouched. Always false on the offline device-recognizer path, which
         * reports no confidence at all — that path behaves exactly as before.
         */
        default void onFinal(@NonNull String text, boolean lowConfidence) {
            onFinal(text);
        }

        /** Honest, human-readable reason listening stopped without a result. */
        void onError(@NonNull String message);

        /** Listening ended (after final, error, or stop()). */
        void onEnd();

        /**
         * Recording finished; the clip is on its way to the server. A cue to
         * show "Transcribing…" instead of "Listening…".
         *
         * <p>Defaulted so the existing anonymous Listeners keep compiling
         * untouched — nothing is required to care about this.
         */
        default void onTranscribing() {
        }
    }

    /**
     * Receives a finished clip instead of it being sent to /dictate — voice
     * mode's HTTP turn posts the clip to /assistant/voice/turn itself. The
     * sink owns the file from then on and must delete it.
     */
    public interface ClipSink {
        void onClip(@NonNull File clip);
    }

    /** Recording geometry: Whisper resamples to 16 kHz mono internally, so
     *  sending anything richer just makes a slower upload for identical text.
     *  A 10-second clip lands around 40 KB. */
    private static final int SAMPLE_RATE = 16_000;
    private static final int BIT_RATE = 32_000;

    /** Silence detection. MediaRecorder amplitude is 0–32767; these are
     *  heuristics, not physics — generous on purpose, because clipping someone
     *  mid-sentence is far worse than a second of trailing silence. Tapping
     *  the mic again always stops immediately regardless. */
    private static final int SPEECH_ONSET_AMPLITUDE = 1_500;
    private static final int SILENCE_AMPLITUDE = 800;
    private static final long POLL_MS = 150L;
    /** Trailing silence after speech that ends the clip. */
    private static final long SILENCE_AFTER_SPEECH_MS = 2_500L;
    /**
     * The same, while dictating something long (meeting notes): telling the
     * story of a visit has thinking pauses in it, and 2.5 s cut people off
     * mid-account — "it did not capture after sometime, all what I said got
     * cut" (reported 19 Sep 2026). The mic button still stops it at once.
     */
    private static final long SILENCE_AFTER_SPEECH_LONG_MS = 6_000L;
    /** Nobody said anything at all — give up rather than record a long hiss. */
    private static final long INITIAL_SILENCE_MS = 7_000L;
    /** Hard ceiling. A text field is not a meeting. */
    private static final long MAX_CLIP_MS = 60_000L;
    /** Hard ceiling for long-form dictation (~1.2 MB of 32 kbit/s audio). */
    private static final long MAX_CLIP_LONG_MS = 300_000L;
    /** Below this a "clip" is a double-tap, not speech. */
    private static final long MIN_CLIP_MS = 400L;
    /** How long an orphaned clip may sit in the cache before it's swept. */
    private static final long STALE_CLIP_MS = 60L * 60L * 1000L;

    @EntryPoint
    @InstallIn(SingletonComponent.class)
    public interface Deps {
        ApiService apiService();

        AppExecutors appExecutors();
    }

    private final Handler handler = new Handler(Looper.getMainLooper());

    private boolean listening;
    /** Dictating into a multi-line field: longer pauses, longer ceiling. */
    private boolean longForm;
    @Nullable private Listener listener;

    // ── Whisper path ──
    @Nullable private MediaRecorder recorder;
    @Nullable private File clip;
    private long startedAtMs;
    private long lastLoudAtMs;
    private boolean heardSpeech;
    private boolean uploading;

    /** Set by {@link #startClip}: hand the clip over rather than dictate it. */
    @Nullable private ClipSink clipSink;

    // ── Device-recognizer fallback ──
    @Nullable private SpeechRecognizer recognizer;
    private boolean usingDeviceRecognizer;

    /**
     * Whether this device can capture speech at all. A microphone is the only
     * hard requirement now — the transcriber is on the server, so a device
     * with no recognizer installed is no longer disqualified.
     */
    public static boolean available(@NonNull Context context) {
        return context.getPackageManager()
                .hasSystemFeature(PackageManager.FEATURE_MICROPHONE);
    }

    public boolean isListening() {
        return listening;
    }

    /**
     * Long-form dictation: for a field that holds an account of something
     * (meeting notes), not a name or a search box. Set it before
     * {@link #start}; it lasts until it is set again.
     */
    public void setLongForm(boolean longForm) {
        this.longForm = longForm;
    }

    private long silenceWindowMs() {
        return longForm ? SILENCE_AFTER_SPEECH_LONG_MS : SILENCE_AFTER_SPEECH_MS;
    }

    private long maxClipMs() {
        return longForm ? MAX_CLIP_LONG_MS : MAX_CLIP_MS;
    }

    public void start(@NonNull Context context, @NonNull Listener listener) {
        if (listening || uploading) return;
        this.listener = listener;
        this.clipSink = null;
        Context app = context.getApplicationContext();
        bind(app);

        // deps == null means the Hilt graph wasn't reachable; there is then
        // nowhere to post a clip to, so don't record one.
        if (deps != null && isOnline(app)) {
            if (startRecording(app)) return;
            // Recorder refused (mic held by something else, odd OEM state).
            // Fall through — the device recognizer may still manage.
        }
        startDeviceRecognizer(app, context);
    }

    /**
     * Record one utterance — same silence detection as dictation — and give
     * the clip to {@code sink} instead of transcribing it. There is no
     * device-recognizer fallback here: the clip is for the server, and with
     * no connection there is nothing to send it to. The listener receives
     * {@code onTranscribing} as the clip is handed over, errors for a clip
     * with no speech in it, and always {@code onEnd}.
     */
    public void startClip(@NonNull Context context, @NonNull Listener listener,
                          @NonNull ClipSink sink) {
        if (listening || uploading) return;
        this.listener = listener;
        Context app = context.getApplicationContext();
        bind(app);
        if (!isOnline(app)) {
            emitError("Voice mode needs a connection — you can type instead.");
            emitEnd();
            return;
        }
        this.clipSink = sink;
        if (!startRecording(app)) {
            this.clipSink = null;
            emitError("The microphone is busy — close other apps using it and try again.");
            emitEnd();
        }
    }

    /** Stop listening; a final result may still arrive. */
    public void stop() {
        if (!listening) return;
        if (usingDeviceRecognizer) {
            if (recognizer != null) recognizer.stopListening();
            return;
        }
        finishRecordingAndUpload();
    }

    public void destroy() {
        listening = false;
        uploading = false;
        listener = null;
        clipSink = null;
        handler.removeCallbacksAndMessages(null);
        releaseRecorder();
        deleteClip();
        if (recognizer != null) {
            recognizer.destroy();
            recognizer = null;
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // Whisper path: record locally, post the clip, get text back
    // ─────────────────────────────────────────────────────────────────────

    private boolean startRecording(@NonNull Context app) {
        File dir = new File(app.getCacheDir(), "dictation");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        sweepStaleClips(dir);
        File target = new File(dir, "dictation_" + System.currentTimeMillis() + ".m4a");

        MediaRecorder mr = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                ? new MediaRecorder(app)
                : new MediaRecorder();
        try {
            mr.setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION);
            mr.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            mr.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            mr.setAudioSamplingRate(SAMPLE_RATE);
            mr.setAudioChannels(1);
            mr.setAudioEncodingBitRate(BIT_RATE);
            mr.setOutputFile(target.getAbsolutePath());
            mr.prepare();
            mr.start();
        } catch (IOException | RuntimeException e) {
            try {
                mr.release();
            } catch (RuntimeException ignored) {
                // already dead
            }
            //noinspection ResultOfMethodCallIgnored
            target.delete();
            return false;
        }

        recorder = mr;
        clip = target;
        usingDeviceRecognizer = false;
        listening = true;
        heardSpeech = false;
        startedAtMs = System.currentTimeMillis();
        lastLoudAtMs = startedAtMs;
        handler.postDelayed(this.silenceWatch, POLL_MS);
        return true;
    }

    /**
     * Ends the clip when the speaker stops, so dictation feels like the
     * recognizer people are used to rather than a walkie-talkie.
     */
    private final Runnable silenceWatch = new Runnable() {
        @Override
        public void run() {
            MediaRecorder mr = recorder;
            if (!listening || mr == null) return;

            int amplitude;
            try {
                amplitude = mr.getMaxAmplitude();
            } catch (RuntimeException e) {
                amplitude = 0;
            }
            long now = System.currentTimeMillis();

            if (amplitude >= SPEECH_ONSET_AMPLITUDE) {
                heardSpeech = true;
                lastLoudAtMs = now;
            } else if (amplitude >= SILENCE_AMPLITUDE && heardSpeech) {
                // Quiet, but not silent — a soft syllable between words, not
                // the end of the sentence. Hold the clock.
                lastLoudAtMs = now;
            }

            long elapsed = now - startedAtMs;
            boolean tooLong = elapsed >= maxClipMs();
            boolean trailedOff = heardSpeech && now - lastLoudAtMs >= silenceWindowMs();
            boolean neverStarted = !heardSpeech && elapsed >= INITIAL_SILENCE_MS;

            if (tooLong || trailedOff || neverStarted) {
                finishRecordingAndUpload();
                return;
            }
            handler.postDelayed(this, POLL_MS);
        }
    };

    private void finishRecordingAndUpload() {
        if (!listening) return;
        listening = false;
        handler.removeCallbacks(silenceWatch);

        long durationMs = System.currentTimeMillis() - startedAtMs;
        boolean spoke = heardSpeech;
        File recorded = clip;
        clip = null;
        boolean stoppedCleanly = releaseRecorder();

        if (recorded == null || !stoppedCleanly || durationMs < MIN_CLIP_MS
                || !recorded.isFile() || recorded.length() == 0) {
            deleteFile(recorded);
            emitError("Didn't catch that — tap the mic and try again.");
            emitEnd();
            return;
        }
        if (!spoke) {
            deleteFile(recorded);
            emitError("Didn't hear anything — tap the mic and try again.");
            emitEnd();
            return;
        }
        ClipSink sink = clipSink;
        if (sink != null) {
            clipSink = null;
            emitTranscribing();
            sink.onClip(recorded);
            emitEnd();
            return;
        }
        upload(recorded);
    }

    private void upload(@NonNull File recorded) {
        Deps deps = this.deps;
        if (deps == null) {
            deleteFile(recorded);
            emitError("Dictation isn't wired up on this screen — you can type instead.");
            emitEnd();
            return;
        }
        uploading = true;
        emitTranscribing();

        deps.appExecutors().io().execute(() -> {
            String text = null;
            String error = null;
            boolean lowConfidence = false;
            try {
                RequestBody body = RequestBody.create(
                        recorded, MediaType.parse("audio/m4a"));
                MultipartBody.Part part = MultipartBody.Part.createFormData(
                        "file", recorded.getName(), body);
                Response<DictationResponse> response =
                        deps.apiService().dictate(part).execute();
                if (response.isSuccessful() && response.body() != null) {
                    text = response.body().text;
                    if (text != null) text = text.trim();
                    lowConfidence = response.body().lowConfidence;
                } else {
                    error = ErrorMapper.fromResponse(response).message;
                }
            } catch (IOException | RuntimeException e) {
                error = ErrorMapper.fromThrowable(e).message;
            } finally {
                deleteFile(recorded);
            }

            final String finalText = text;
            final String finalError = error;
            final boolean finalLowConfidence = lowConfidence;
            handler.post(() -> {
                uploading = false;
                if (finalError != null) {
                    emitError(finalError);
                } else if (finalText == null || finalText.isEmpty()) {
                    // Whisper heard audio but no words in it.
                    emitError("Didn't catch that — tap the mic and try again.");
                } else {
                    emitFinal(finalText, finalLowConfidence);
                }
                emitEnd();
            });
        });
    }

    /** @return true if the recorder stopped without complaining. A stop() that
     *  throws means the file has no usable moov atom — the clip is garbage. */
    private boolean releaseRecorder() {
        MediaRecorder mr = recorder;
        recorder = null;
        if (mr == null) return false;
        boolean clean = true;
        try {
            mr.stop();
        } catch (RuntimeException e) {
            clean = false;
        }
        try {
            mr.release();
        } catch (RuntimeException ignored) {
            // already released
        }
        return clean;
    }

    // ─────────────────────────────────────────────────────────────────────
    // Offline fallback: the on-device recognizer, as before
    // ─────────────────────────────────────────────────────────────────────

    private void startDeviceRecognizer(@NonNull Context app, @NonNull Context original) {
        if (!SpeechRecognizer.isRecognitionAvailable(app)) {
            emitError("Dictation needs a connection right now — you can type instead.");
            emitEnd();
            return;
        }
        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(original);
        }
        usingDeviceRecognizer = true;
        listening = true;
        recognizer.setRecognitionListener(new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle params) { }

            @Override public void onBeginningOfSpeech() { }

            @Override public void onRmsChanged(float rmsdB) { }

            @Override public void onBufferReceived(byte[] buffer) { }

            @Override public void onEndOfSpeech() { }

            @Override
            public void onError(int error) {
                listening = false;
                emitError(humanError(error));
                emitEnd();
            }

            @Override
            public void onResults(Bundle results) {
                listening = false;
                String text = firstResult(results);
                if (text != null && !text.isEmpty()) {
                    emitFinal(text);
                } else {
                    emitError(humanError(SpeechRecognizer.ERROR_NO_MATCH));
                }
                emitEnd();
            }

            @Override
            public void onPartialResults(Bundle partialResults) {
                String text = firstResult(partialResults);
                if (text != null && !text.isEmpty()) {
                    emitPartial(text);
                }
            }

            @Override public void onEvent(int eventType, Bundle params) { }
        });

        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        // Device locale — Indian English works out of the box (04 §3).
        recognizer.startListening(intent);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Plumbing
    // ─────────────────────────────────────────────────────────────────────

    @Nullable private Deps deps;

    /** Resolved lazily from the application graph: this class is constructed
     *  by plain views and dialogs that Hilt does not inject. */
    private void bind(@NonNull Context app) {
        if (deps != null) return;
        try {
            deps = EntryPointAccessors.fromApplication(app, Deps.class);
        } catch (RuntimeException e) {
            // No graph (unit test, or a context that isn't the app). Leave
            // deps null; start() then takes the device-recognizer path rather
            // than recording a clip nothing can transcribe.
            deps = null;
        }
    }

    private static boolean isOnline(@NonNull Context app) {
        ConnectivityManager cm = (ConnectivityManager)
                app.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return false;
        Network network = cm.getActiveNetwork();
        if (network == null) return false;
        NetworkCapabilities caps = cm.getNetworkCapabilities(network);
        return caps != null
                && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    private void emitPartial(@NonNull String text) {
        Listener l = listener;
        if (l != null) l.onPartial(text);
    }

    private void emitFinal(@NonNull String text) {
        emitFinal(text, false);
    }

    private void emitFinal(@NonNull String text, boolean lowConfidence) {
        Listener l = listener;
        if (l != null) l.onFinal(text, lowConfidence);
    }

    private void emitError(@NonNull String message) {
        Listener l = listener;
        if (l != null) l.onError(message);
    }

    private void emitTranscribing() {
        Listener l = listener;
        if (l != null) l.onTranscribing();
    }

    private void emitEnd() {
        Listener l = listener;
        if (l != null) l.onEnd();
    }

    private void deleteClip() {
        deleteFile(clip);
        clip = null;
    }

    /**
     * Drop clips a previous session left behind. The happy path deletes each
     * clip the moment it has been transcribed, but a process death mid-upload
     * skips that — and a recording of someone's voice is not something to
     * leave lying around on disk indefinitely waiting for the OS to reclaim
     * the cache.
     */
    private static void sweepStaleClips(@NonNull File dir) {
        File[] files = dir.listFiles();
        if (files == null) return;
        long cutoff = System.currentTimeMillis() - STALE_CLIP_MS;
        for (File f : files) {
            if (f.isFile() && f.lastModified() < cutoff) {
                //noinspection ResultOfMethodCallIgnored
                f.delete();
            }
        }
    }

    private static void deleteFile(@Nullable File file) {
        if (file != null && file.isFile()) {
            //noinspection ResultOfMethodCallIgnored
            file.delete();
        }
    }

    @Nullable
    private static String firstResult(@Nullable Bundle bundle) {
        if (bundle == null) return null;
        ArrayList<String> texts =
                bundle.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        return texts == null || texts.isEmpty() ? null : texts.get(0);
    }

    @NonNull
    private static String humanError(int code) {
        switch (code) {
            case SpeechRecognizer.ERROR_NO_MATCH:
            case SpeechRecognizer.ERROR_SPEECH_TIMEOUT:
                return "Didn't catch that — tap the mic and try again.";
            case SpeechRecognizer.ERROR_AUDIO:
                return "Microphone problem — try again.";
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS:
                return "Microphone permission is needed to dictate.";
            case SpeechRecognizer.ERROR_NETWORK:
            case SpeechRecognizer.ERROR_NETWORK_TIMEOUT:
                return "Speech service needs a connection right now.";
            case SpeechRecognizer.ERROR_RECOGNIZER_BUSY:
                return "The recognizer is busy — one dictation at a time.";
            default:
                return "Speech recognition failed — you can type instead.";
        }
    }
}
