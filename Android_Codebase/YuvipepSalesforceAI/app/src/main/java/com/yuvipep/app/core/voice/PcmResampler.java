package com.yuvipep.app.core.voice;

import androidx.annotation.NonNull;

/**
 * Mono 16-bit little-endian PCM from one rate to another, chunk by chunk.
 *
 * <p>Streaming-safe: the position and the last sample carry over between
 * {@link #process} calls, so audio arriving in 100 ms frames comes out as one
 * continuous signal — resampling each frame on its own would click at every
 * join. Linear interpolation: plenty for speech going to a lip-sync model and
 * a phone speaker. Not thread-safe; one instance per utterance.
 */
public final class PcmResampler {

    private final int from;
    private final int to;
    private final double step;
    /** Position of the next output sample, relative to {@link #previous}. */
    private double position;
    /** The last input sample of the previous chunk (index -1 of this one). */
    private short previous;
    private boolean started;
    /** A byte left over when a chunk had an odd length. */
    private int carry = -1;

    public PcmResampler(int fromRate, int toRate) {
        if (fromRate <= 0 || toRate <= 0) throw new IllegalArgumentException("rate");
        this.from = fromRate;
        this.to = toRate;
        this.step = (double) fromRate / toRate;
    }

    @NonNull
    public byte[] process(@NonNull byte[] input) {
        byte[] bytes = input;
        if (carry >= 0) {
            bytes = new byte[input.length + 1];
            bytes[0] = (byte) carry;
            System.arraycopy(input, 0, bytes, 1, input.length);
            carry = -1;
        }
        int count = bytes.length / 2;
        if (bytes.length % 2 == 1) carry = bytes[bytes.length - 1] & 0xFF;
        if (count == 0) return new byte[0];

        short[] in = new short[count];
        for (int i = 0; i < count; i++) {
            in[i] = (short) ((bytes[2 * i] & 0xFF) | (bytes[2 * i + 1] << 8));
        }
        if (from == to) {
            byte[] same = new byte[count * 2];
            System.arraycopy(bytes, 0, same, 0, count * 2);
            return same;
        }
        if (!started) {
            // The first output sample is the first input sample.
            previous = in[0];
            position = 1.0;
            started = true;
        }

        // Sample k of this chunk sits at position k + 1 (previous is at 0).
        int capacity = (int) Math.ceil((count + 1 - position) / step) + 1;
        short[] out = new short[Math.max(capacity, 0)];
        int n = 0;
        while (position <= count && n < out.length) {
            int i = (int) Math.floor(position);
            double frac = position - i;
            short a = i == 0 ? previous : in[i - 1];
            short b = i >= count ? in[count - 1] : (i == 0 ? in[0] : in[i]);
            if (i >= count) {
                // Exactly on the last sample: no right neighbour needed.
                out[n++] = a;
            } else {
                out[n++] = (short) Math.round(a + (b - a) * frac);
            }
            position += step;
        }
        previous = in[count - 1];
        position -= count;

        byte[] result = new byte[n * 2];
        for (int k = 0; k < n; k++) {
            result[2 * k] = (byte) out[k];
            result[2 * k + 1] = (byte) (out[k] >> 8);
        }
        return result;
    }
}
