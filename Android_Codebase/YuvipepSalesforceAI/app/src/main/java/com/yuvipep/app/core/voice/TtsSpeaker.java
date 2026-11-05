package com.yuvipep.app.core.voice;

import android.content.Context;
import android.content.SharedPreferences;
import android.speech.tts.TextToSpeech;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import javax.inject.Inject;
import javax.inject.Singleton;

import dagger.hilt.android.qualifiers.ApplicationContext;

/**
 * Jarvis's spoken replies (04 §2 "TTS toggle"). v1 uses the system
 * TextToSpeech engine; the sherpa-onnx/Kokoro neural voice slots in behind
 * this same interface once its model download flow lands (04 §3 — the doc
 * gates that on a Phase-5-start re-verification of the model builds).
 *
 * Speaks the reply's short summary only — never action-card bodies.
 */
@Singleton
public class TtsSpeaker {

    private static final String PREFS = "yuvipep_voice";
    private static final String KEY_SPEAK = "speak_replies";
    private static final int MAX_SPOKEN_CHARS = 300;

    private final Context context;
    private final SharedPreferences prefs;
    @Nullable private TextToSpeech tts;
    private boolean ready;

    @Inject
    public TtsSpeaker(@ApplicationContext Context context) {
        this.context = context;
        this.prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public boolean isEnabled() {
        return prefs.getBoolean(KEY_SPEAK, false);
    }

    public void setEnabled(boolean enabled) {
        prefs.edit().putBoolean(KEY_SPEAK, enabled).apply();
        if (enabled) {
            ensureEngine();
        } else {
            stop();
        }
    }

    /** Speak a reply if the toggle is on. Long texts are trimmed to a summary. */
    public void speak(@Nullable String text) {
        if (text == null || text.trim().isEmpty() || !isEnabled()) return;
        String spoken = text.trim();
        if (spoken.length() > MAX_SPOKEN_CHARS) {
            int cut = spoken.lastIndexOf('.', MAX_SPOKEN_CHARS);
            spoken = spoken.substring(0, cut > 40 ? cut + 1 : MAX_SPOKEN_CHARS);
        }
        final String toSay = spoken;
        if (ready && tts != null) {
            tts.speak(toSay, TextToSpeech.QUEUE_FLUSH, null, "jarvis-reply");
        } else {
            ensureEngine(() -> {
                if (ready && tts != null) {
                    tts.speak(toSay, TextToSpeech.QUEUE_FLUSH, null, "jarvis-reply");
                }
            });
        }
    }

    /**
     * Voice mode's device voice: speak now whatever the toggle says (the
     * person is in a spoken conversation), and report when it is over —
     * finished, failed or cut off by {@link #stop()} — on the main thread, so
     * the mic can reopen. {@code onDone} runs exactly once.
     */
    public void speakNow(@Nullable String text, @Nullable Runnable onDone) {
        String toSay = text == null ? "" : text.trim();
        Runnable previous = pendingDone;
        pendingDone = null;
        if (previous != null) main.post(previous);
        if (toSay.isEmpty()) {
            if (onDone != null) main.post(onDone);
            return;
        }
        final String id = "jarvis-voice-" + (++utteranceSeq);
        pendingId = id;
        pendingDone = onDone;
        Runnable say = () -> {
            if (!ready || tts == null) {
                finish(id);
                return;
            }
            tts.setOnUtteranceProgressListener(progress);
            if (tts.speak(toSay, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) {
                finish(id);
            }
        };
        // An engine that failed to start is not waited on — `say` reports
        // it as done at once.
        ensureEngine(say);
    }

    /** Whether a {@link #speakNow} utterance is still in progress. */
    public boolean isSpeakingNow() {
        return pendingDone != null;
    }

    public void stop() {
        if (tts != null) tts.stop();
        String id = pendingId;
        if (id != null) finish(id);
    }

    private final android.os.Handler main =
            new android.os.Handler(android.os.Looper.getMainLooper());
    private int utteranceSeq;
    @Nullable private volatile String pendingId;
    @Nullable private volatile Runnable pendingDone;

    private final android.speech.tts.UtteranceProgressListener progress =
            new android.speech.tts.UtteranceProgressListener() {
                @Override
                public void onStart(String utteranceId) {
                }

                @Override
                public void onDone(String utteranceId) {
                    finish(utteranceId);
                }

                @Override
                public void onStop(String utteranceId, boolean interrupted) {
                    finish(utteranceId);
                }

                @Override
                @SuppressWarnings("deprecation")
                public void onError(String utteranceId) {
                    finish(utteranceId);
                }
            };

    private void finish(@Nullable String utteranceId) {
        main.post(() -> {
            if (utteranceId == null || !utteranceId.equals(pendingId)) return;
            Runnable done = pendingDone;
            pendingDone = null;
            pendingId = null;
            if (done != null) done.run();
        });
    }

    private void ensureEngine() {
        ensureEngine(null);
    }

    private void ensureEngine(@Nullable Runnable onReady) {
        if (tts != null) {
            if (onReady == null) return;
            if (initDone) {
                onReady.run();
            } else {
                afterInit.add(onReady);
            }
            return;
        }
        if (onReady != null) afterInit.add(onReady);
        tts = new TextToSpeech(context, status -> {
            ready = status == TextToSpeech.SUCCESS;
            initDone = true;
            // Always run: every caller checks `ready` itself, and a voice
            // conversation must hear "failed" rather than wait forever.
            java.util.List<Runnable> waiting = new java.util.ArrayList<>(afterInit);
            afterInit.clear();
            for (Runnable r : waiting) r.run();
        });
    }

    private boolean initDone;
    private final java.util.List<Runnable> afterInit = new java.util.ArrayList<>();
}
