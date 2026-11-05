package com.yuvipep.app.core.voice;

import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Handler;
import android.os.Looper;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.concurrent.LinkedBlockingQueue;

/**
 * Plays Jarvis's server voice: mono 16-bit PCM, streamed.
 *
 * <p>The server sends a reply's audio <b>faster than real time</b> (25 s of
 * speech arrived in half a second when measured), so "the server finished
 * sending" is not "the phone finished speaking". This class paces the audio
 * through a streaming {@link AudioTrack} on its own thread and reports
 * {@link Listener#onDrained()} only when the last sample marked with
 * {@link #endOfSpeech()} has actually played — that is when the mic may open
 * again on a phone without echo cancellation.
 *
 * <p>{@link #stopNow()} drops everything queued and silences the track at
 * once (the person started talking, or tapped Stop).
 */
public final class VoicePlayer implements SpeechOutput {

    /** 50 ms at 24 kHz — small enough that stopNow() is heard immediately. */
    private static final int WRITE_CHUNK_BYTES = 2_400;
    private static final long DRAIN_POLL_MS = 20L;

    private static final class Chunk {
        final int generation;
        @Nullable final byte[] pcm;   // null = end-of-speech marker
        final int sampleRate;

        Chunk(int generation, @Nullable byte[] pcm, int sampleRate) {
            this.generation = generation;
            this.pcm = pcm;
            this.sampleRate = sampleRate;
        }
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private final LinkedBlockingQueue<Chunk> queue = new LinkedBlockingQueue<>();
    private final Object trackLock = new Object();
    @Nullable private volatile Listener listener;
    private final Thread writer;

    private volatile int generation;
    private volatile boolean active;
    private volatile boolean released;
    private volatile int sampleRate = 24_000;

    // Writer thread only (and stopNow, under trackLock).
    @Nullable private AudioTrack track;
    private int trackRate;
    private long framesWritten;
    /** Set by stopNow(): the next audio gets a fresh track, so its playback
     *  position starts at 0 — flush() does not reset it on every release. */
    private boolean trackStale;

    public VoicePlayer(@Nullable Listener listener) {
        this.listener = listener;
        writer = new Thread(this::loop, "jarvis-voice-player");
        writer.setDaemon(true);
        writer.start();
    }

    @Override
    public void setListener(@Nullable Listener listener) {
        this.listener = listener;
    }

    /** Played through the assistant stream an echo canceller can hear. */
    @Override
    public boolean echoCancellable() {
        return true;
    }

    /** The rate of the audio that follows (from {@code speak_start}). */
    @Override
    public void setSampleRate(int rate) {
        if (rate > 0) sampleRate = rate;
    }

    @Override
    public void play(@NonNull byte[] pcm) {
        if (released || pcm.length == 0) return;
        active = true;
        queue.offer(new Chunk(generation, pcm, sampleRate));
    }

    /** Nothing more follows for now; report when what was queued has played. */
    @Override
    public void endOfSpeech() {
        if (released) return;
        queue.offer(new Chunk(generation, null, sampleRate));
    }

    /** Sound is queued or still coming out of the speaker. */
    @Override
    public boolean isActive() {
        return active;
    }

    /** Silence now and forget everything queued. Does not call onDrained. */
    @Override
    public void stopNow() {
        generation++;
        queue.clear();
        active = false;
        synchronized (trackLock) {
            AudioTrack t = track;
            if (t != null) {
                try {
                    t.pause();
                    t.flush();
                } catch (IllegalStateException ignored) {
                    // not initialised — nothing is playing anyway
                }
            }
            framesWritten = 0;
            trackStale = true;
        }
    }

    @Override
    public void release() {
        released = true;
        stopNow();
        writer.interrupt();
    }

    /**
     * A WAV file (the HTTP turn's {@code audio.base64}) as PCM + rate.
     * Returns null for anything that is not 16-bit mono/stereo PCM.
     */
    @Nullable
    public static Pcm decodeWav(@NonNull byte[] wav) {
        if (wav.length < 44 || wav[0] != 'R' || wav[1] != 'I' || wav[2] != 'F'
                || wav[3] != 'F') {
            return null;
        }
        ByteBuffer b = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN);
        int pos = 12;
        int rate = 0;
        int channels = 0;
        int bits = 0;
        while (pos + 8 <= wav.length) {
            String id = new String(wav, pos, 4, java.nio.charset.StandardCharsets.US_ASCII);
            int size = b.getInt(pos + 4);
            int body = pos + 8;
            if (size < 0) return null;
            if ("fmt ".equals(id) && body + 16 <= wav.length) {
                channels = b.getShort(body + 2);
                rate = b.getInt(body + 4);
                bits = b.getShort(body + 14);
            } else if ("data".equals(id)) {
                if (bits != 16 || rate <= 0 || channels < 1) return null;
                int end = (int) Math.min((long) body + size, wav.length);
                byte[] pcm = new byte[end - body];
                System.arraycopy(wav, body, pcm, 0, pcm.length);
                if (channels > 1) pcm = downmix(pcm, channels);
                return new Pcm(pcm, rate);
            }
            pos = body + size + (size & 1);
        }
        return null;
    }

    public static final class Pcm {
        @NonNull public final byte[] data;
        public final int sampleRate;

        Pcm(@NonNull byte[] data, int sampleRate) {
            this.data = data;
            this.sampleRate = sampleRate;
        }
    }

    // ── writer thread ────────────────────────────────────────────────

    private void loop() {
        while (!released) {
            Chunk chunk;
            try {
                chunk = queue.take();
            } catch (InterruptedException e) {
                break;
            }
            if (chunk.generation != generation) continue;
            if (chunk.pcm == null) {
                awaitPlayedOut(chunk.generation);
                continue;
            }
            AudioTrack t = ensureTrack(chunk.sampleRate);
            if (t == null) continue;
            write(t, chunk);
        }
        synchronized (trackLock) {
            if (track != null) {
                try {
                    track.release();
                } catch (RuntimeException ignored) {
                    // already gone
                }
                track = null;
            }
        }
    }

    private void write(@NonNull AudioTrack t, @NonNull Chunk chunk) {
        byte[] pcm = chunk.pcm;
        if (pcm == null) return;
        int offset = 0;
        // Even length only: a split sample would turn the rest into noise.
        int length = pcm.length & ~1;
        while (offset < length && chunk.generation == generation && !released) {
            int n = Math.min(WRITE_CHUNK_BYTES, length - offset);
            synchronized (trackLock) {
                if (chunk.generation != generation) return;
                try {
                    if (t.getPlayState() != AudioTrack.PLAYSTATE_PLAYING) t.play();
                } catch (IllegalStateException e) {
                    return;
                }
            }
            // Blocking write outside the lock — this is what paces playback.
            int written = t.write(pcm, offset, n);
            if (written <= 0) return;
            synchronized (trackLock) {
                if (chunk.generation == generation) framesWritten += written / 2;
            }
            offset += written;
        }
    }

    /** Block until the track has played every frame written, then report. */
    private void awaitPlayedOut(int gen) {
        while (!released && gen == generation) {
            // Something new was queued behind the marker: keep speaking.
            Chunk next = queue.peek();
            if (next != null && next.generation == generation) return;
            long played;
            long written;
            synchronized (trackLock) {
                AudioTrack t = track;
                written = framesWritten;
                played = t == null ? written
                        : (t.getPlaybackHeadPosition() & 0xFFFFFFFFL);
            }
            if (played >= written) break;
            try {
                Thread.sleep(DRAIN_POLL_MS);
            } catch (InterruptedException e) {
                return;
            }
        }
        if (released || gen != generation || !queue.isEmpty()) return;
        active = false;
        Listener l = listener;
        if (l != null) {
            main.post(() -> {
                if (!released && gen == generation && !active) l.onDrained();
            });
        }
    }

    @Nullable
    private AudioTrack ensureTrack(int rate) {
        synchronized (trackLock) {
            if (track != null && trackRate == rate && !trackStale) return track;
            trackStale = false;
            if (track != null) {
                try {
                    track.release();
                } catch (RuntimeException ignored) {
                    // replacing it anyway
                }
                track = null;
            }
            int min = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO,
                    AudioFormat.ENCODING_PCM_16BIT);
            try {
                track = new AudioTrack.Builder()
                        .setAudioAttributes(new AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_ASSISTANT)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build())
                        .setAudioFormat(new AudioFormat.Builder()
                                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                                .setSampleRate(rate)
                                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                                .build())
                        .setTransferMode(AudioTrack.MODE_STREAM)
                        .setBufferSizeInBytes(Math.max(min, rate / 5 * 2))
                        .build();
                trackRate = rate;
                framesWritten = 0;
            } catch (RuntimeException e) {
                android.util.Log.w("VoicePlayer", "No audio track at " + rate + " Hz", e);
                track = null;
            }
            return track;
        }
    }

    @NonNull
    private static byte[] downmix(@NonNull byte[] pcm, int channels) {
        int frames = pcm.length / (2 * channels);
        byte[] out = new byte[frames * 2];
        ByteBuffer in = ByteBuffer.wrap(pcm).order(ByteOrder.LITTLE_ENDIAN);
        ByteBuffer o = ByteBuffer.wrap(out).order(ByteOrder.LITTLE_ENDIAN);
        for (int f = 0; f < frames; f++) {
            int sum = 0;
            for (int c = 0; c < channels; c++) sum += in.getShort();
            o.putShort((short) (sum / channels));
        }
        return out;
    }
}
