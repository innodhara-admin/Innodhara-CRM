package com.yuvipep.app.core.voice;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

/**
 * Where Jarvis's voice comes out: the plain streaming player
 * ({@link VoicePlayer}) or the talking avatar, which plays the same audio
 * while moving its lips to it.
 *
 * <p>An utterance is {@link #play} … {@link #endOfSpeech()}; utterances play
 * one after another. {@link Listener#onDrained()} fires once everything up to
 * the last end-of-speech has actually been heard.
 */
public interface SpeechOutput {

    interface Listener {
        /** Everything queued has played. Main thread. */
        void onDrained();
    }

    void setListener(@Nullable Listener listener);

    /** The rate of the PCM that follows (mono, 16-bit little-endian). */
    void setSampleRate(int rate);

    void play(@NonNull byte[] pcm);

    void endOfSpeech();

    /** Silence now and forget everything queued. Does not call onDrained. */
    void stopNow();

    /** Sound is queued or still coming out of the speaker. */
    boolean isActive();

    /**
     * Whether a phone's echo canceller hears this output. When false the
     * person cannot talk over Jarvis: the mic stays shut while it speaks.
     */
    boolean echoCancellable();

    /**
     * Say {@code text} in this output's own way (for replies the server did
     * not voice). Returns false when this output cannot, so the caller uses
     * the system voice instead.
     */
    default boolean speakText(@NonNull String text) {
        return false;
    }

    void release();
}
