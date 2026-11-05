package com.yuvipep.app.feature.assistant.voice;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

/**
 * The voice screen's living circle: rings that follow the microphone while
 * Jarvis listens, a turning arc while it thinks, ripples while it speaks.
 * Drawn, not animated from assets, so it costs nothing to ship.
 */
public class VoiceOrbView extends View {

    private static final int LISTEN = 0xFF4FC3F7;
    private static final int HEAR = 0xFFE8A13D;
    private static final int THINK = 0xFF9FA8DA;
    private static final int SPEAK = 0xFF7C4DFF;
    private static final int IDLE = 0xFF607D8B;

    private final Paint ring = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint core = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint arc = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF oval = new RectF();

    @NonNull private VoiceModeController.State state = VoiceModeController.State.OFF;
    private float level;
    private float shownLevel;
    private int color = IDLE;
    private boolean drawCore = true;
    private long startedAt = System.currentTimeMillis();
    private int shaderColor;
    private int shaderSize = -1;

    public VoiceOrbView(Context context) {
        this(context, null);
    }

    public VoiceOrbView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        ring.setStyle(Paint.Style.STROKE);
        arc.setStyle(Paint.Style.STROKE);
        arc.setStrokeCap(Paint.Cap.ROUND);
    }

    /** Only the rings — for a halo around a button. */
    public void setDrawCore(boolean drawCore) {
        this.drawCore = drawCore;
        invalidate();
    }

    public void setState(@NonNull VoiceModeController.State next) {
        state = next;
        switch (next) {
            case LISTENING: color = LISTEN; break;
            case HEARING: color = HEAR; break;
            case TRANSCRIBING:
            case THINKING: color = THINK; break;
            case SPEAKING: color = SPEAK; break;
            default: color = IDLE; break;
        }
        if (next != VoiceModeController.State.LISTENING
                && next != VoiceModeController.State.HEARING) {
            level = 0f;
        }
        startedAt = System.currentTimeMillis();
        invalidate();
    }

    public void setLevel(float value) {
        level = Math.max(0f, Math.min(1f, value));
        invalidate();
    }

    @Override
    protected void onDraw(@NonNull Canvas canvas) {
        super.onDraw(canvas);
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        float max = Math.min(getWidth(), getHeight()) / 2f;
        if (max <= 0) return;
        long t = System.currentTimeMillis() - startedAt;
        float density = getResources().getDisplayMetrics().density;

        // Ease the level so the rings breathe rather than jitter.
        shownLevel += (level - shownLevel) * 0.25f;
        float base = max * 0.56f;
        boolean animating = state != VoiceModeController.State.OFF
                && state != VoiceModeController.State.PAUSED;

        // Outer rings.
        ring.setStrokeWidth(2f * density);
        for (int i = 0; i < 3; i++) {
            float phase;
            float radius;
            int alpha;
            if (state == VoiceModeController.State.SPEAKING
                    || state == VoiceModeController.State.CONNECTING
                    || state == VoiceModeController.State.RECONNECTING) {
                // Ripples travelling outwards.
                phase = ((t / 1600f) + i / 3f) % 1f;
                radius = base + (max - base) * phase;
                alpha = (int) (170 * (1f - phase));
            } else {
                // Rings that swell with the voice.
                phase = (float) Math.sin(t / 700.0 + i) * 0.5f + 0.5f;
                float reach = 0.25f + 0.75f * shownLevel;
                radius = base + (max - base) * reach * (0.45f + 0.55f * (i + 1) / 3f)
                        + phase * 2f * density;
                alpha = animating ? 70 + (int) (80 * shownLevel) - i * 18 : 40 - i * 10;
            }
            ring.setColor(withAlpha(color, Math.max(alpha, 0)));
            canvas.drawCircle(cx, cy, Math.min(radius, max - density), ring);
        }

        // Core.
        if (drawCore) {
            float r = base * (0.92f + 0.08f * shownLevel);
            if (shaderColor != color || shaderSize != getWidth() * 10000 + getHeight()) {
                shaderColor = color;
                shaderSize = getWidth() * 10000 + getHeight();
                core.setShader(new RadialGradient(cx - base * 0.3f, cy - base * 0.35f,
                        base * 1.4f, lighten(color), darken(color), Shader.TileMode.CLAMP));
            }
            canvas.drawCircle(cx, cy, r, core);
        }

        // Thinking arc.
        if (state == VoiceModeController.State.THINKING
                || state == VoiceModeController.State.TRANSCRIBING) {
            float r = base + 6f * density;
            arc.setStrokeWidth(3f * density);
            arc.setColor(withAlpha(Color.WHITE, 200));
            oval.set(cx - r, cy - r, cx + r, cy + r);
            float start = (t / 3f) % 360f;
            canvas.drawArc(oval, start, 80f, false, arc);
            canvas.drawArc(oval, start + 180f, 40f, false, arc);
        }

        if (animating || Math.abs(level - shownLevel) > 0.01f) postInvalidateOnAnimation();
    }

    private static int withAlpha(int color, int alpha) {
        return (Math.min(alpha, 255) << 24) | (color & 0x00FFFFFF);
    }

    private static int lighten(int color) {
        return Color.rgb(Math.min(255, Color.red(color) + 60),
                Math.min(255, Color.green(color) + 60),
                Math.min(255, Color.blue(color) + 60));
    }

    private static int darken(int color) {
        return Color.rgb((int) (Color.red(color) * 0.45f),
                (int) (Color.green(color) * 0.45f),
                (int) (Color.blue(color) * 0.45f));
    }
}
