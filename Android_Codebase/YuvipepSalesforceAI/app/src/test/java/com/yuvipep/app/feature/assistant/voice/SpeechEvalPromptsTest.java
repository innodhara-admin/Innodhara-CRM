package com.yuvipep.app.feature.assistant.voice;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;

public class SpeechEvalPromptsTest {

    @Test
    public void idsAreUniqueAndBracketsBalanced() {
        Set<String> ids = new HashSet<>();
        for (SpeechEvalPrompts.Prompt p : SpeechEvalPrompts.ALL) {
            assertTrue("duplicate id " + p.id, ids.add(p.id));
            int depth = 0;
            for (char ch : p.marked.toCharArray()) {
                if (ch == '[') depth++;
                if (ch == ']') depth--;
                assertTrue(p.id + " closes a bracket it never opened", depth >= 0);
                assertTrue(p.id + " nests brackets", depth <= 1);
            }
            assertEquals(p.id + " leaves a bracket open", 0, depth);
            assertFalse(p.display().contains("["));
        }
    }

    @Test
    public void displayDropsOnlyTheBrackets() {
        SpeechEvalPrompts.Prompt p = SpeechEvalPrompts.ALL.get(1);
        assertEquals("Create a lead named Shree Vidya Mandir in Pune.", p.display());
    }

    @Test
    public void wavHeaderDescribes16kMonoPcm() {
        byte[] pcm = new byte[640];
        byte[] wav = SpeechEvalPrompts.wav(pcm, 16_000);
        assertEquals(44 + 640, wav.length);
        ByteBuffer b = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN);
        assertEquals("RIFF", new String(wav, 0, 4, StandardCharsets.US_ASCII));
        assertEquals(36 + 640, b.getInt(4));
        assertEquals("WAVE", new String(wav, 8, 4, StandardCharsets.US_ASCII));
        assertEquals(1, b.getShort(20));
        assertEquals(1, b.getShort(22));
        assertEquals(16_000, b.getInt(24));
        assertEquals(32_000, b.getInt(28));
        assertEquals(16, b.getShort(34));
        assertEquals("data", new String(wav, 36, 4, StandardCharsets.US_ASCII));
        assertEquals(640, b.getInt(40));
    }
}
