package com.yuvipep.app.feature.assistant.voice;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.yuvipep.app.core.net.dto.AssistantDtos;

/**
 * The voice WebSocket's wire format, {@code protocol_version} 1
 * (backend docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md §5).
 *
 * <p>Pure Java so a unit test can pin it: text frames are JSON, binary frames
 * are audio (16 kHz s16le up, 24 kHz s16le down).
 */
public final class VoiceProtocol {

    public static final int PROTOCOL_VERSION = 1;
    public static final String PATH = "/api/v1/assistant/voice";

    public static final int INPUT_SAMPLE_RATE = 16_000;
    /** 20 ms of 16 kHz mono s16le — the frame size the server expects. */
    public static final int INPUT_FRAME_BYTES = 640;
    public static final int OUTPUT_SAMPLE_RATE = 24_000;
    /** The client's keep-alive; the server closes after 300 s of silence. */
    public static final long PING_INTERVAL_MS = 20_000L;

    // Close codes (§5.6)
    public static final int CLOSE_NORMAL = 1000;
    public static final int CLOSE_SERVER_ERROR = 1011;
    public static final int CLOSE_BAD_REQUEST = 4400;
    public static final int CLOSE_UNAUTHORIZED = 4401;
    public static final int CLOSE_FORBIDDEN = 4403;
    public static final int CLOSE_IDLE = 4408;

    private static final Gson GSON = new Gson();

    private VoiceProtocol() {
    }

    /**
     * The socket's address on the current server: {@code https → wss},
     * {@code http → ws}. The base URL is EnvironmentStore's, without a
     * trailing slash.
     */
    @NonNull
    public static String socketUrl(@NonNull String baseUrl) {
        String base = baseUrl.trim();
        while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
        if (base.regionMatches(true, 0, "https://", 0, 8)) {
            base = "wss://" + base.substring(8);
        } else if (base.regionMatches(true, 0, "http://", 0, 7)) {
            base = "ws://" + base.substring(7);
        }
        return base + PATH;
    }

    /**
     * The first frame. The token rides in the Authorization header, so it is
     * left out here — a bad token is refused after this message, not at the
     * handshake.
     */
    @NonNull
    public static String start(@NonNull String sessionId, boolean serverVoice,
                               boolean bargeIn, @Nullable String voice, @Nullable String leadId,
                               @Nullable String proposalId, @Nullable String meetingId) {
        JsonObject o = new JsonObject();
        o.addProperty("type", "start");
        if (voice != null) o.addProperty("voice", voice);
        o.addProperty("session_id", sessionId);
        o.addProperty("format", "pcm_s16le");
        o.addProperty("sample_rate", INPUT_SAMPLE_RATE);
        o.addProperty("vad", "server");
        o.addProperty("server_voice", serverVoice);
        o.addProperty("barge_in", bargeIn);
        addContext(o, leadId, proposalId, meetingId);
        return o.toString();
    }

    /** A typed turn in the same session (question-card chips, the keyboard). */
    @NonNull
    public static String text(@NonNull String text) {
        JsonObject o = new JsonObject();
        o.addProperty("type", "text");
        o.addProperty("text", text);
        return o.toString();
    }

    /** Speak with another server voice from the next sentence on. */
    @NonNull
    public static String voice(@NonNull String voice) {
        JsonObject o = new JsonObject();
        o.addProperty("type", "voice");
        o.addProperty("voice", voice);
        return o.toString();
    }

    /** The screen changed. Replaces the whole context on the server. */
    @NonNull
    public static String context(@Nullable String leadId, @Nullable String proposalId,
                                 @Nullable String meetingId) {
        JsonObject o = new JsonObject();
        o.addProperty("type", "context");
        addContext(o, leadId, proposalId, meetingId);
        return o.toString();
    }

    /** {@code interrupt}, {@code ping}, {@code stop}, {@code cancel}, {@code end_of_speech}. */
    @NonNull
    public static String control(@NonNull String type) {
        JsonObject o = new JsonObject();
        o.addProperty("type", type);
        return o.toString();
    }

    /** Parse a server text frame; null when it is not a JSON object with a type. */
    @Nullable
    public static JsonObject parse(@Nullable String frame) {
        if (frame == null) return null;
        try {
            JsonElement root = JsonParser.parseString(frame);
            if (!root.isJsonObject()) return null;
            JsonObject o = root.getAsJsonObject();
            return o.has("type") && o.get("type").isJsonPrimitive() ? o : null;
        } catch (RuntimeException e) {
            return null;
        }
    }

    @NonNull
    public static String type(@NonNull JsonObject message) {
        return message.get("type").getAsString();
    }

    /**
     * A {@code reply} message as the command response it contains — its
     * {@code agent/reply/actions/pending_approvals/session_id} are exactly
     * /assistant/command's, so the same cards render from it.
     */
    @NonNull
    public static AssistantDtos.VoiceTurnResponse reply(@NonNull JsonObject message) {
        return GSON.fromJson(message, AssistantDtos.VoiceTurnResponse.class);
    }

    @Nullable
    public static String string(@NonNull JsonObject o, @NonNull String key) {
        JsonElement e = o.get(key);
        return e == null || e.isJsonNull() || !e.isJsonPrimitive() ? null : e.getAsString();
    }

    public static boolean bool(@NonNull JsonObject o, @NonNull String key, boolean fallback) {
        JsonElement e = o.get(key);
        if (e == null || e.isJsonNull() || !e.isJsonPrimitive()) return fallback;
        try {
            return e.getAsBoolean();
        } catch (RuntimeException ex) {
            return fallback;
        }
    }

    public static int integer(@NonNull JsonObject o, @NonNull String key, int fallback) {
        JsonElement e = o.get(key);
        if (e == null || e.isJsonNull() || !e.isJsonPrimitive()) return fallback;
        try {
            return e.getAsInt();
        } catch (RuntimeException ex) {
            return fallback;
        }
    }

    /**
     * Should a closed socket be reopened? Only for network trouble and server
     * hiccups — a refusal (bad start, no permission, voice switched off) or a
     * deliberate end would just be refused again.
     */
    public static boolean shouldReconnect(int closeCode) {
        switch (closeCode) {
            case CLOSE_NORMAL:
            case CLOSE_BAD_REQUEST:
            case CLOSE_UNAUTHORIZED:
            case CLOSE_FORBIDDEN:
            case CLOSE_IDLE:
                return false;
            default:
                return true;
        }
    }

    private static void addContext(@NonNull JsonObject o, @Nullable String leadId,
                                   @Nullable String proposalId, @Nullable String meetingId) {
        o.addProperty("lead_id", leadId);
        o.addProperty("proposal_id", proposalId);
        o.addProperty("meeting_id", meetingId);
    }
}
