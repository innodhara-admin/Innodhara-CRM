package com.yuvipep.app.feature.assistant.voice;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.yuvipep.app.core.net.dto.AssistantDtos;
import com.yuvipep.app.core.voice.VoicePlayer;

import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

/**
 * The voice WebSocket's wire format, pinned against the backend's handover
 * (docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md §5) and against frames
 * captured from the live server on 2026-09-17.
 */
public class VoiceProtocolTest {

    @Test
    public void theSocketLivesOnTheSameServerAsTheApi() {
        assertEquals("wss://example.ngrok-free.dev/api/v1/assistant/voice",
                VoiceProtocol.socketUrl("https://example.ngrok-free.dev"));
        assertEquals("wss://example.ngrok-free.dev/api/v1/assistant/voice",
                VoiceProtocol.socketUrl("https://example.ngrok-free.dev/"));
        assertEquals("ws://10.0.2.2:8000/api/v1/assistant/voice",
                VoiceProtocol.socketUrl("http://10.0.2.2:8000"));
        assertEquals("wss://HOST/api/v1/assistant/voice",
                VoiceProtocol.socketUrl("HTTPS://HOST"));
    }

    @Test
    public void theStartMessageIsWhatTheServerValidates() {
        JsonObject start = JsonParser.parseString(VoiceProtocol.start(
                "abcdef0123456789", true, false, "af_bella", "lead-1", null, null))
                .getAsJsonObject();
        assertEquals("start", start.get("type").getAsString());
        assertEquals("abcdef0123456789", start.get("session_id").getAsString());
        assertEquals("pcm_s16le", start.get("format").getAsString());
        assertEquals(16000, start.get("sample_rate").getAsInt());
        assertEquals("server", start.get("vad").getAsString());
        assertTrue(start.get("server_voice").getAsBoolean());
        assertFalse(start.get("barge_in").getAsBoolean());
        assertEquals("lead-1", start.get("lead_id").getAsString());
        assertEquals("af_bella", start.get("voice").getAsString());
        // No avatar chosen: the server's default voice, so no field at all.
        assertFalse(JsonParser.parseString(VoiceProtocol.start("abcdef0123456789", true, false,
                null, null, null, null)).getAsJsonObject().has("voice"));
        // Never a token in the frame — it rides in the Authorization header.
        assertFalse(start.has("token"));
    }

    @Test
    public void controlAndTextMessages() {
        assertEquals("{\"type\":\"ping\"}", VoiceProtocol.control("ping"));
        assertEquals("{\"type\":\"voice\",\"voice\":\"am_puck\"}",
                VoiceProtocol.voice("am_puck"));
        JsonObject text = JsonParser.parseString(VoiceProtocol.text("Create it"))
                .getAsJsonObject();
        assertEquals("text", text.get("type").getAsString());
        assertEquals("Create it", text.get("text").getAsString());
        JsonObject context = JsonParser.parseString(
                VoiceProtocol.context(null, "p-9", null)).getAsJsonObject();
        assertEquals("context", context.get("type").getAsString());
        assertEquals("p-9", context.get("proposal_id").getAsString());
        assertTrue(context.get("lead_id").isJsonNull());
    }

    @Test
    public void aReplyFrameReadsLikeACommandResponse() {
        // Captured from the live server (trimmed).
        String frame = "{\"type\": \"reply\", \"turn\": 1, \"spoken_by\": \"server\","
                + " \"acted\": true, \"transcript\": \"What are my open tasks?\","
                + " \"agent\": \"query\", \"reply\": \"1. I tried to pull your **open tasks**\","
                + " \"speech\": \"1. I tried to pull your open tasks\","
                + " \"actions\": [{\"tool\": \"list_tasks\", \"ok\": true}],"
                + " \"pending_approvals\": [], \"session_id\": \"wsprobe0002\"}";
        JsonObject message = VoiceProtocol.parse(frame);
        assertNotNull(message);
        assertEquals("reply", VoiceProtocol.type(message));
        assertEquals(1, VoiceProtocol.integer(message, "turn", 0));

        AssistantDtos.VoiceTurnResponse reply = VoiceProtocol.reply(message);
        assertEquals("server", reply.spokenBy);
        assertTrue(reply.acted);
        assertEquals("query", reply.agent);
        assertEquals("What are my open tasks?", reply.transcript);
        assertEquals("1. I tried to pull your open tasks", reply.speech);
        assertEquals(1, reply.actions.size());
        assertEquals("list_tasks", reply.actions.get(0).get("tool"));
        assertEquals("wsprobe0002", reply.sessionId);
    }

    @Test
    public void aNotActedReplyFrame() {
        JsonObject message = VoiceProtocol.parse("{\"type\":\"reply\",\"turn\":2,"
                + "\"spoken_by\":\"device\",\"acted\":false,\"transcript\":\"Ad City\","
                + "\"agent\":\"voice\",\"reply\":\"I heard 'Ad City'.\","
                + "\"speech\":\"I heard 'Ad City'.\",\"actions\":[],"
                + "\"pending_approvals\":[],\"session_id\":\"s1234567\"}");
        assertNotNull(message);
        AssistantDtos.VoiceTurnResponse reply = VoiceProtocol.reply(message);
        assertFalse(reply.acted);
        assertEquals("device", reply.spokenBy);
        assertEquals("Ad City", reply.transcript);
    }

    @Test
    public void junkFramesAreIgnored() {
        assertNull(VoiceProtocol.parse(null));
        assertNull(VoiceProtocol.parse("not json"));
        assertNull(VoiceProtocol.parse("[1,2]"));
        assertNull(VoiceProtocol.parse("{\"no\":\"type\"}"));
        JsonObject ready = VoiceProtocol.parse("{\"type\":\"ready\",\"barge_in\":false,"
                + "\"server_voice\":{\"available\":null}}");
        assertNotNull(ready);
        assertFalse(VoiceProtocol.bool(ready, "barge_in", true));
        assertFalse(VoiceProtocol.bool(ready.getAsJsonObject("server_voice"),
                "available", false));
        assertEquals(24000, VoiceProtocol.integer(ready, "sample_rate", 24000));
        assertNull(VoiceProtocol.string(ready, "missing"));
    }

    @Test
    public void onlyTroubleIsRetried() {
        assertFalse(VoiceProtocol.shouldReconnect(VoiceProtocol.CLOSE_NORMAL));
        assertFalse(VoiceProtocol.shouldReconnect(VoiceProtocol.CLOSE_BAD_REQUEST));
        assertFalse(VoiceProtocol.shouldReconnect(VoiceProtocol.CLOSE_UNAUTHORIZED));
        assertFalse(VoiceProtocol.shouldReconnect(VoiceProtocol.CLOSE_FORBIDDEN));
        assertFalse(VoiceProtocol.shouldReconnect(VoiceProtocol.CLOSE_IDLE));
        assertTrue(VoiceProtocol.shouldReconnect(VoiceProtocol.CLOSE_SERVER_ERROR));
        assertTrue(VoiceProtocol.shouldReconnect(1006));   // network dropped
        assertTrue(VoiceProtocol.shouldReconnect(1001));   // server going away (restart)
    }

    @Test
    public void theHttpTurnsWavBecomesPlayablePcm() {
        byte[] pcm = {1, 0, 2, 0, 3, 0, 4, 0};
        VoicePlayer.Pcm decoded = VoicePlayer.decodeWav(wav(pcm, 24000, 1, true));
        assertNotNull(decoded);
        assertEquals(24000, decoded.sampleRate);
        assertEquals(8, decoded.data.length);
        assertEquals(3, decoded.data[4]);

        // Stereo is folded to mono.
        byte[] stereo = {2, 0, 4, 0, 6, 0, 8, 0};
        VoicePlayer.Pcm mono = VoicePlayer.decodeWav(wav(stereo, 16000, 2, false));
        assertNotNull(mono);
        assertEquals(4, mono.data.length);
        assertEquals(3, mono.data[0]);
        assertEquals(7, mono.data[2]);

        assertNull(VoicePlayer.decodeWav(new byte[10]));
        assertNull(VoicePlayer.decodeWav("RIFFxxxxWAVEnope".getBytes(StandardCharsets.US_ASCII)));
    }

    @Test
    public void captionsReadWithoutMarkdown() {
        assertEquals("1. I tried to pull your open tasks",
                VoiceStageDialog.stripMarkdown("1. I tried to pull your **open tasks**"));
        assertEquals("See the proposal now",
                VoiceStageDialog.stripMarkdown("See [the proposal](https://x/y) `now`"));
        assertEquals("Line one Line two",
                VoiceStageDialog.stripMarkdown("# Line one\n\n> Line two"));
    }

    /** A minimal WAV, optionally with an extra chunk before "data" (as some encoders write). */
    private static byte[] wav(byte[] pcm, int rate, int channels, boolean extraChunk) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ByteBuffer header = ByteBuffer.allocate(36).order(ByteOrder.LITTLE_ENDIAN);
        header.put("RIFF".getBytes(StandardCharsets.US_ASCII)).putInt(0)
                .put("WAVE".getBytes(StandardCharsets.US_ASCII))
                .put("fmt ".getBytes(StandardCharsets.US_ASCII)).putInt(16)
                .putShort((short) 1).putShort((short) channels).putInt(rate)
                .putInt(rate * channels * 2).putShort((short) (channels * 2))
                .putShort((short) 16);
        out.write(header.array(), 0, 36);
        if (extraChunk) {
            ByteBuffer list = ByteBuffer.allocate(11).order(ByteOrder.LITTLE_ENDIAN);
            list.put("LIST".getBytes(StandardCharsets.US_ASCII)).putInt(3)
                    .put(new byte[]{9, 9, 9});   // odd size → one pad byte
            out.write(list.array(), 0, 11);
            out.write(0);
        }
        ByteBuffer data = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN);
        data.put("data".getBytes(StandardCharsets.US_ASCII)).putInt(pcm.length);
        out.write(data.array(), 0, 8);
        out.write(pcm, 0, pcm.length);
        return out.toByteArray();
    }
}
