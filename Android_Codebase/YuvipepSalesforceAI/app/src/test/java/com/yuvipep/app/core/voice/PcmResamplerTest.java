package com.yuvipep.app.core.voice;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.ByteArrayOutputStream;

/**
 * The avatar lip-syncs to 16 kHz audio; the server speaks at 24 kHz, in
 * 100 ms frames. Resampling frame by frame must give the same signal as
 * resampling it whole — a click at every join would be heard, and seen on
 * the avatar's lips.
 */
public class PcmResamplerTest {

    private static byte[] tone(int rate, int samples, double hz) {
        byte[] out = new byte[samples * 2];
        for (int i = 0; i < samples; i++) {
            short s = (short) Math.round(12000 * Math.sin(2 * Math.PI * hz * i / rate));
            out[2 * i] = (byte) s;
            out[2 * i + 1] = (byte) (s >> 8);
        }
        return out;
    }

    private static short sample(byte[] pcm, int i) {
        return (short) ((pcm[2 * i] & 0xFF) | (pcm[2 * i + 1] << 8));
    }

    @Test
    public void serverFramesBecomeTwoThirdsAsLong() {
        PcmResampler r = new PcmResampler(24_000, 16_000);
        // 100 ms at 24 kHz = 4800 bytes → 100 ms at 16 kHz = 3200 bytes
        int total = 0;
        for (int i = 0; i < 50; i++) total += r.process(new byte[4800]).length;
        assertEquals(50 * 3200, total, 4);
    }

    @Test
    public void chunkedEqualsWhole() {
        byte[] signal = tone(24_000, 24_000, 220);   // one second
        byte[] whole = new PcmResampler(24_000, 16_000).process(signal);

        PcmResampler chunked = new PcmResampler(24_000, 16_000);
        ByteArrayOutputStream joined = new ByteArrayOutputStream();
        int[] sizes = {4800, 1, 999, 4800, 3, 2400};   // odd sizes split samples too
        int offset = 0;
        int k = 0;
        while (offset < signal.length) {
            int n = Math.min(sizes[k++ % sizes.length], signal.length - offset);
            byte[] part = new byte[n];
            System.arraycopy(signal, offset, part, 0, n);
            byte[] out = chunked.process(part);
            joined.write(out, 0, out.length);
            offset += n;
        }
        assertArrayEquals(whole, joined.toByteArray());
    }

    @Test
    public void theToneSurvives() {
        byte[] signal = tone(24_000, 2400, 440);
        byte[] out = new PcmResampler(24_000, 16_000).process(signal);
        // Output sample k sits at input position 1.5k: compare with the tone there.
        for (int k = 0; k < out.length / 2 - 1; k += 37) {
            double expected = 12000 * Math.sin(2 * Math.PI * 440 * (1.5 * k) / 24_000);
            assertTrue("sample " + k, Math.abs(sample(out, k) - expected) < 400);
        }
    }

    @Test
    public void deviceVoiceRatesToo() {
        // System TTS commonly renders at 22.05 kHz; Duix wants 16 kHz.
        byte[] out = new PcmResampler(22_050, 16_000).process(new byte[22_050 * 2]);
        assertEquals(16_000 * 2, out.length, 4);
        // Same rate: passthrough.
        byte[] same = tone(16_000, 100, 300);
        assertArrayEquals(same, new PcmResampler(16_000, 16_000).process(same));
    }
}
