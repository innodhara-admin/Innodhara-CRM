package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

/**
 * POST /assistant/command — the Jarvis endpoint. Actions and pending
 * approvals stay generic maps: every agent reports different shapes, and
 * the app renders whatever came back instead of inventing a schema.
 *
 * The {@code session_id} makes the calls a conversation: the backend replays
 * the previous turns to the agent, so "make it warmer" and "the second one"
 * mean something. It is minted and kept by {@code AssistantSession}.
 */
public final class AssistantDtos {

    private AssistantDtos() {
    }

    public static class CommandRequest {
        @SerializedName("text") public String text;
        @SerializedName("session_id") public String sessionId;
        @SerializedName("lead_id") public String leadId;
        @SerializedName("proposal_id") public String proposalId;
        @SerializedName("meeting_id") public String meetingId;

        public CommandRequest(String text, String sessionId, String leadId,
                              String proposalId, String meetingId) {
            this.text = text;
            this.sessionId = sessionId;
            this.leadId = leadId;
            this.proposalId = proposalId;
            this.meetingId = meetingId;
        }
    }

    public static class CommandResponse {
        @SerializedName("agent") public String agent;
        @SerializedName("reply") public String reply;
        @SerializedName("actions") public List<Map<String, Object>> actions;
        @SerializedName("pending_approvals")
        public List<Map<String, Object>> pendingApprovals;
        @SerializedName("session_id") public String sessionId;
    }

    /**
     * GET /assistant/voice/config — what voice mode can do on this server
     * right now. Read when the voice panel opens; {@code enabled == false}
     * hides it (typed Jarvis and /dictate still work).
     */
    public static class VoiceConfig {
        @SerializedName("enabled") public boolean enabled;
        @SerializedName("protocol_version") public int protocolVersion;
        @SerializedName("tts") public VoiceTts tts;
        @SerializedName("clip_formats") public List<String> clipFormats;
        @SerializedName("end_of_turn_silence_ms") public int endOfTurnSilenceMs;
        @SerializedName("max_utterance_seconds") public int maxUtteranceSeconds;
        @SerializedName("barge_in") public boolean bargeIn;
        @SerializedName("confirmation_ttl_seconds") public int confirmationTtlSeconds;
    }

    public static class VoiceTts {
        @SerializedName("engine") public String engine;
        /** null until the server has tried to load its voice in this process. */
        @SerializedName("available") public Boolean available;
        @SerializedName("sample_rate") public Integer sampleRate;
        @SerializedName("error") public String error;
    }

    /**
     * POST /assistant/voice/turn — one recorded clip in, one answer out. The
     * inherited fields are exactly /assistant/command's, so the same cards
     * render from it.
     */
    public static class VoiceTurnResponse extends CommandResponse {
        @SerializedName("transcript") public String transcript;
        @SerializedName("language") public String language;
        @SerializedName("confidence") public double confidence;
        @SerializedName("low_confidence") public boolean lowConfidence;
        /** false = the transcript was too uncertain and nothing was done. */
        @SerializedName("acted") public boolean acted;
        /** The reply made speakable: no markdown, long answers cut short. */
        @SerializedName("speech") public String speech;
        @SerializedName("audio") public VoiceAudio audio;
        /** "server" (audio is attached) or "device" (speak {@link #speech}). */
        @SerializedName("spoken_by") public String spokenBy;
    }

    public static class VoiceAudio {
        @SerializedName("format") public String format;
        @SerializedName("sample_rate") public int sampleRate;
        @SerializedName("base64") public String base64;
    }

    /** POST /assistant/voice/speak — text in the server's voice (WAV back). */
    public static class SpeakRequest {
        @SerializedName("text") public String text;
        @SerializedName("voice") public String voice;

        public SpeakRequest(String text, String voice) {
            this.text = text;
            this.voice = voice;
        }
    }

    /** GET /assistant/history — one stored turn, oldest first. */
    public static class Turn {
        @SerializedName("role") public String role;  // user | assistant
        @SerializedName("content") public String content;
        @SerializedName("agent") public String agent;
        @SerializedName("at") public String at;
    }

    /** GET /why/{entity_type}/{entity_id} */
    public static class WhyResponse {
        @SerializedName("trace") public String trace;
    }
}
