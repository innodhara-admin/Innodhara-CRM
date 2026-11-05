package com.yuvipep.app.core.voice;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.media.audiofx.AcousticEchoCanceler;
import android.media.audiofx.AudioEffect;
import android.media.audiofx.NoiseSuppressor;
import android.os.Handler;
import android.os.Looper;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.RequiresPermission;

/**
 * The microphone as a stream of 20 ms frames of 16 kHz mono s16le PCM — the
 * format the voice WebSocket takes (backend doc §5.7).
 *
 * <p>Captures with {@code VOICE_COMMUNICATION}, which is the source Android
 * applies its echo canceller to, and attaches the canceller and noise
 * suppressor when the device has them. Frames are handed to the sink on the
 * capture thread (sending them is thread-safe); the level is posted to the
 * main thread about ten times a second for the orb.
 */
public final class MicStreamer {

    public interface Sink {
        /** One frame. Capture thread — the array is not reused. */
        void onFrame(@NonNull byte[] frame);

        /** 0..1 loudness, main thread, ~10 Hz. */
        void onLevel(float level);

        /** The mic could not be opened or failed while open. Main thread. */
        void onMicError(@NonNull String message);
    }

    /**
     * How the microphone is opened. {@link #COMMUNICATION} is what voice mode
     * uses; the others exist so the speech test recorder can compare them.
     */
    public enum CaptureMode {
        /** VOICE_COMMUNICATION + echo canceller + noise suppressor. */
        COMMUNICATION("communication", MediaRecorder.AudioSource.VOICE_COMMUNICATION, true, true),
        /** VOICE_COMMUNICATION + echo canceller, no noise suppressor. */
        COMMUNICATION_NO_NS("communication_no_ns",
                MediaRecorder.AudioSource.VOICE_COMMUNICATION, true, false),
        /** VOICE_RECOGNITION (tuned for speech recognisers), no effects. */
        RECOGNITION("recognition", MediaRecorder.AudioSource.VOICE_RECOGNITION, false, false);

        /** Stable name used in file names. */
        @NonNull public final String key;
        final int source;
        final boolean echoCanceller;
        final boolean noiseSuppressor;

        CaptureMode(@NonNull String key, int source, boolean echoCanceller,
                    boolean noiseSuppressor) {
            this.key = key;
            this.source = source;
            this.echoCanceller = echoCanceller;
            this.noiseSuppressor = noiseSuppressor;
        }
    }

    private static final int SAMPLE_RATE = 16_000;
    private static final int FRAME_BYTES = 640;
    private static final int LEVEL_EVERY_FRAMES = 5;

    private final Handler main = new Handler(Looper.getMainLooper());
    @NonNull private final CaptureMode mode;
    @Nullable private volatile Thread thread;
    private volatile boolean running;

    public MicStreamer() {
        this(CaptureMode.COMMUNICATION);
    }

    public MicStreamer(@NonNull CaptureMode mode) {
        this.mode = mode;
    }

    /** Whether this phone offers an echo canceller at all. */
    public static boolean echoCancellerAvailable() {
        try {
            return AcousticEchoCanceler.isAvailable();
        } catch (RuntimeException e) {
            return false;
        }
    }

    public boolean isRunning() {
        return running;
    }

    @RequiresPermission(android.Manifest.permission.RECORD_AUDIO)
    public void start(@NonNull Sink sink) {
        if (running) return;
        running = true;
        Thread t = new Thread(() -> capture(sink), "jarvis-voice-mic");
        thread = t;
        t.start();
    }

    public void stop() {
        running = false;
        Thread t = thread;
        thread = null;
        if (t != null) t.interrupt();
    }

    @SuppressWarnings("MissingPermission")
    private void capture(@NonNull Sink sink) {
        int min = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord record = null;
        AudioEffect aec = null;
        AudioEffect ns = null;
        try {
            record = new AudioRecord(mode.source,
                    SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, Math.max(min, FRAME_BYTES * 8));
            if (record.getState() != AudioRecord.STATE_INITIALIZED) {
                fail(sink, "The microphone is busy — close other apps using it and try again.");
                return;
            }
            int session = record.getAudioSessionId();
            aec = enable(mode.echoCanceller && AcousticEchoCanceler.isAvailable()
                    ? AcousticEchoCanceler.create(session) : null);
            ns = enable(mode.noiseSuppressor && NoiseSuppressor.isAvailable()
                    ? NoiseSuppressor.create(session) : null);
            record.startRecording();
            if (record.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                fail(sink, "The microphone is busy — close other apps using it and try again.");
                return;
            }

            int frames = 0;
            long sumSquares = 0;
            int samples = 0;
            while (live()) {
                byte[] frame = new byte[FRAME_BYTES];
                int got = 0;
                while (got < FRAME_BYTES && live()) {
                    int n = record.read(frame, got, FRAME_BYTES - got);
                    if (n < 0) {
                        fail(sink, "The microphone stopped working — try again.");
                        return;
                    }
                    got += n;
                }
                if (!live()) break;
                sink.onFrame(frame);

                for (int i = 0; i + 1 < FRAME_BYTES; i += 2) {
                    int s = (short) ((frame[i] & 0xFF) | (frame[i + 1] << 8));
                    sumSquares += (long) s * s;
                }
                samples += FRAME_BYTES / 2;
                if (++frames % LEVEL_EVERY_FRAMES == 0) {
                    double rms = Math.sqrt((double) sumSquares / Math.max(samples, 1));
                    // Speech sits around 500–5000 RMS; a gentle log curve reads well.
                    float level = (float) Math.min(1.0,
                            Math.max(0.0, Math.log10(Math.max(rms, 1)) - 2.0) / 2.0);
                    sumSquares = 0;
                    samples = 0;
                    main.post(() -> {
                        if (running) sink.onLevel(level);
                    });
                }
            }
        } catch (SecurityException e) {
            fail(sink, "Microphone permission is needed for voice mode.");
        } catch (RuntimeException e) {
            fail(sink, "The microphone could not be opened — try again.");
        } finally {
            release(aec);
            release(ns);
            if (record != null) {
                try {
                    record.stop();
                } catch (RuntimeException ignored) {
                    // never started
                }
                record.release();
            }
        }
    }

    /** This capture thread is still the one wanted (a quick stop/start
     *  must not leave two readers on the mic). */
    private boolean live() {
        return running && thread == Thread.currentThread();
    }

    private void fail(@NonNull Sink sink, @NonNull String message) {
        if (!live()) return;
        running = false;
        main.post(() -> sink.onMicError(message));
    }

    @Nullable
    private static AudioEffect enable(@Nullable AudioEffect effect) {
        if (effect == null) return null;
        try {
            effect.setEnabled(true);
        } catch (RuntimeException ignored) {
            // present but refused — capture works without it
        }
        return effect;
    }

    private static void release(@Nullable AudioEffect effect) {
        if (effect == null) return;
        try {
            effect.release();
        } catch (RuntimeException ignored) {
            // already released
        }
    }
}
