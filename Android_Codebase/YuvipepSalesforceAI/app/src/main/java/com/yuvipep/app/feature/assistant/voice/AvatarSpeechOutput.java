package com.yuvipep.app.feature.assistant.voice;

import android.content.Context;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.voice.PcmResampler;
import com.yuvipep.app.core.voice.SpeechOutput;
import com.yuvipep.app.core.voice.VoicePlayer;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.file.Files;
import java.util.ArrayDeque;
import java.util.Locale;

import ai.guiji.duix.sdk.client.DUIX;

/**
 * Jarvis's voice through the Duix avatar: the avatar plays the audio itself
 * and moves its lips to it.
 *
 * <p>Duix takes 16 kHz mono PCM as {@code startPush → pushPcm… → stopPush},
 * one "session" per utterance, and reports the end of playback. Three of its
 * habits shape this class:
 * <ul>
 *   <li>A new session <b>replaces</b> the one playing (its unplayed audio and
 *   its end report are dropped). So utterances are queued here and each is
 *   started only when the previous one has finished — the spoken "Let me
 *   check." is not cut off by the answer arriving behind it.</li>
 *   <li>It needs at least a second of audio before it starts; shorter
 *   utterances are padded with silence.</li>
 *   <li>If it never gets going it never reports an end, which would leave
 *   the mic shut for good — a watchdog ends the utterance after its length
 *   plus a margin.</li>
 * </ul>
 * Its audio goes to the music stream, which echo cancellers do not hear, so
 * {@link #echoCancellable()} is false. Main thread only.
 */
public final class AvatarSpeechOutput implements SpeechOutput {

    private static final int DUIX_RATE = 16_000;
    /** Duix wants a second of audio (16 kHz × 2 bytes) before it plays. */
    private static final int MIN_BYTES = 32_000;
    /** 100 ms per pushPcm, as the SDK's own sample does. */
    private static final int PUSH_BYTES = 3_200;
    private static final long WATCHDOG_MARGIN_MS = 6_000L;

    private static final class Utterance {
        final ByteArrayOutputStream pending = new ByteArrayOutputStream();
        final PcmResampler resampler;
        long pushedBytes;
        /** No more audio will be added. */
        boolean ended;
        /** startPush sent. */
        boolean started;
        /** stopPush sent — Duix now owns the rest, and will report its end. */
        boolean closed;

        Utterance(int sampleRate) {
            resampler = new PcmResampler(sampleRate, DUIX_RATE);
        }
    }

    private final Context app;
    private final Handler main = new Handler(Looper.getMainLooper());
    /** Separate from {@link #main}: stopNow() clears that one, and the engine's
     *  "ready" must not be lost with it. */
    private final Handler initHandler = new Handler(Looper.getMainLooper());
    private final ArrayDeque<Utterance> queue = new ArrayDeque<>();
    @Nullable private DUIX duix;
    @Nullable private Listener listener;
    private int sampleRate = 24_000;
    /** The utterance audio is being added to (the newest, not yet ended). */
    @Nullable private Utterance receiving;
    private int generation;

    @Nullable private TextToSpeech tts;
    private boolean ttsReady;
    private boolean ttsInitDone;
    private final java.util.List<Runnable> afterTtsInit = new java.util.ArrayList<>();
    private int ttsSeq;

    public AvatarSpeechOutput(@NonNull Context context, @NonNull DUIX duix) {
        this.app = context.getApplicationContext();
        this.duix = duix;
    }

    /** From the Duix callback (any thread): the current utterance finished. */
    public void onDuixPlayEnd() {
        main.post(this::finishHead);
    }

    @Override
    public void setListener(@Nullable Listener listener) {
        this.listener = listener;
    }

    @Override
    public void setSampleRate(int rate) {
        if (rate > 0) sampleRate = rate;
    }

    @Override
    public void play(@NonNull byte[] pcm) {
        if (duix == null || pcm.length == 0) return;
        Utterance u = receiving;
        if (u == null) {
            u = new Utterance(sampleRate);
            receiving = u;
            queue.addLast(u);
        }
        byte[] converted = u.resampler.process(pcm);
        u.pending.write(converted, 0, converted.length);
        if (queue.peekFirst() == u) pump(u);
    }

    @Override
    public void endOfSpeech() {
        Utterance u = receiving;
        receiving = null;
        if (u == null) {
            if (queue.isEmpty()) drained();
            return;
        }
        u.ended = true;
        if (queue.peekFirst() == u) pump(u);
    }

    @Override
    public void stopNow() {
        generation++;
        queue.clear();
        receiving = null;
        main.removeCallbacksAndMessages(null);
        if (tts != null) tts.stop();
        if (duix != null) duix.stopAudio();
    }

    @Override
    public boolean isActive() {
        return !queue.isEmpty();
    }

    @Override
    public boolean echoCancellable() {
        return false;
    }

    /**
     * The system voice, rendered to a file and played by the avatar so its
     * lips still move — for replies the server did not voice.
     */
    @Override
    public boolean speakText(@NonNull String text) {
        if (duix == null) return false;
        final int gen = generation;
        final Utterance u = new Utterance(DUIX_RATE);
        queue.addLast(u);   // holds its place in line while it is synthesised
        final File wav = new File(app.getCacheDir(), "jarvis_avatar_tts.wav");
        final String id = "avatar-" + (++ttsSeq);
        Runnable synth = () -> {
            if (gen != generation) return;
            if (!ttsReady || tts == null) {
                abandon(u);
                return;
            }
            tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override
                public void onStart(String utteranceId) {
                }

                @Override
                public void onDone(String utteranceId) {
                    if (!id.equals(utteranceId)) return;
                    byte[] bytes;
                    try {
                        bytes = Files.readAllBytes(wav.toPath());
                    } catch (Exception e) {
                        bytes = null;
                    }
                    //noinspection ResultOfMethodCallIgnored
                    wav.delete();
                    final byte[] data = bytes;
                    main.post(() -> {
                        if (gen != generation) return;
                        VoicePlayer.Pcm pcm = data == null ? null : VoicePlayer.decodeWav(data);
                        if (pcm == null) {
                            abandon(u);
                            return;
                        }
                        byte[] converted = new PcmResampler(pcm.sampleRate, DUIX_RATE)
                                .process(pcm.data);
                        u.pending.write(converted, 0, converted.length);
                        u.ended = true;
                        if (queue.peekFirst() == u) pump(u);
                    });
                }

                @Override
                @SuppressWarnings("deprecation")
                public void onError(String utteranceId) {
                    if (id.equals(utteranceId)) main.post(() -> abandon(u));
                }
            });
            if (tts.synthesizeToFile(text, new Bundle(), wav, id) != TextToSpeech.SUCCESS) {
                abandon(u);
            }
        };
        if (ttsInitDone) {
            synth.run();
            return true;
        }
        afterTtsInit.add(synth);
        if (tts == null) {
            tts = new TextToSpeech(app, status -> initHandler.post(() -> {
                ttsInitDone = true;
                ttsReady = status == TextToSpeech.SUCCESS;
                if (ttsReady && tts != null) tts.setLanguage(Locale.US);
                java.util.List<Runnable> waiting = new java.util.ArrayList<>(afterTtsInit);
                afterTtsInit.clear();
                for (Runnable r : waiting) r.run();
            }));
        }
        return true;
    }

    @Override
    public void release() {
        stopNow();
        afterTtsInit.clear();
        if (tts != null) {
            tts.shutdown();
            tts = null;
        }
        duix = null;
        listener = null;
    }

    // ── internals ────────────────────────────────────────────────────

    /** Feed the head utterance to Duix: what has arrived, and its end if known. */
    private void pump(@NonNull Utterance u) {
        DUIX d = duix;
        if (d == null) return;
        byte[] bytes = u.pending.toByteArray();
        u.pending.reset();
        if (!u.started) {
            // Nothing to start with yet (a synthesis still running).
            if (bytes.length == 0 && !u.ended) return;
            u.started = true;
            d.startPush();
        }
        for (int offset = 0; offset < bytes.length; offset += PUSH_BYTES) {
            int n = Math.min(PUSH_BYTES, bytes.length - offset);
            byte[] chunk = new byte[n];
            System.arraycopy(bytes, offset, chunk, 0, n);
            d.pushPcm(chunk);
        }
        u.pushedBytes += bytes.length;
        if (!u.ended || u.closed) return;

        if (u.pushedBytes < MIN_BYTES) {
            d.pushPcm(new byte[(int) (MIN_BYTES - u.pushedBytes)]);
            u.pushedBytes = MIN_BYTES;
        }
        d.stopPush();
        u.closed = true;
        final int gen = generation;
        long lengthMs = u.pushedBytes * 1000L / (DUIX_RATE * 2);
        main.postDelayed(() -> {
            if (gen == generation && queue.peekFirst() == u) finishHead();
        }, lengthMs + WATCHDOG_MARGIN_MS);
    }

    private void finishHead() {
        Utterance head = queue.peekFirst();
        // Only an utterance that has been closed can have finished playing.
        if (head == null || !head.closed) return;
        queue.pollFirst();
        Utterance next = queue.peekFirst();
        if (next != null) {
            pump(next);
        } else {
            drained();
        }
    }

    /** An utterance that will never have audio (synthesis failed). */
    private void abandon(@NonNull Utterance u) {
        boolean wasHead = queue.peekFirst() == u;
        queue.remove(u);
        if (!wasHead) return;
        Utterance next = queue.peekFirst();
        if (next != null) pump(next);
        else drained();
    }

    private void drained() {
        Listener l = listener;
        if (l != null) main.post(() -> {
            if (queue.isEmpty()) l.onDrained();
        });
    }
}
