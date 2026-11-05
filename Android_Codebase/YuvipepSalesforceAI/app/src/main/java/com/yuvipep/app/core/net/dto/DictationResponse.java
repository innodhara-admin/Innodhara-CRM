package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/**
 * POST /dictate — a short recording from a text field, transcribed by the
 * backend's Whisper (DICTATION_WHISPER_MODEL, "tiny" by default).
 *
 * Not the meeting pipeline: nothing is stored server-side and there is no
 * record to poll afterwards. The text comes straight back and is typed into
 * whichever field the user was speaking into.
 */
public class DictationResponse {

    public String text;
    /** Detected language ("en", "hi", …), or null when the model didn't say. */
    public String language;
    /** Whisper's own 0–1 confidence. Informational when a human is looking
     *  right at the field and can fix it; see {@link #lowConfidence} for the
     *  case where nobody is. */
    public double confidence;

    /**
     * The server's verdict on that number, against the same 0.6 threshold the
     * meeting review gate uses. The threshold lives on the server so the two
     * cannot drift apart.
     *
     * <p>Matters wherever dictated text is acted on WITHOUT the user reading
     * it first — the assistant's mic sends automatically. Measured with real
     * Kannada speech, "tiny" returned 6-12% similarity at 0.01-0.41
     * confidence, and that nonsense went out as a command. When this is true,
     * show the text and let the user decide; do not act on it.
     */
    @SerializedName("low_confidence")
    public boolean lowConfidence;
}
