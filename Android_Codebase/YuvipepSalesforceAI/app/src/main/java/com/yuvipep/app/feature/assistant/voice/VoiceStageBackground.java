package com.yuvipep.app.feature.assistant.voice;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import com.yuvipep.app.R;

/**
 * The voice screen's night sky: a deep navy wash with three soft glows (the
 * idea from LinguaAI's nebula background, in the app's indigo and amber).
 * Radial gradients rather than blur filters, so it stays hardware-drawn.
 */
public class VoiceStageBackground extends View {

    private final Paint wash = new Paint();
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private Shader washShader;
    private Shader[] glows = new Shader[0];
    private float[][] circles = new float[0][];

    public VoiceStageBackground(Context context) {
        this(context, null);
    }

    public VoiceStageBackground(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        super.onSizeChanged(w, h, oldw, oldh);
        int top = ContextCompat.getColor(getContext(), R.color.stage_bg_top);
        int bottom = ContextCompat.getColor(getContext(), R.color.stage_bg_bottom);
        washShader = new LinearGradient(0, 0, 0, h, top, bottom, Shader.TileMode.CLAMP);
        float r = Math.max(w, h) * 0.45f;
        circles = new float[][]{
                {w * 0.05f, h * 0.10f, r},          // indigo, top-left
                {w * 1.00f, h * 0.40f, r * 0.8f},   // amber, right
                {w * 0.60f, h * 1.00f, r},          // blue, bottom
        };
        int[] colors = {0x557C3AED, 0x33E8A13D, 0x550566D9};
        glows = new Shader[circles.length];
        for (int i = 0; i < circles.length; i++) {
            glows[i] = new RadialGradient(circles[i][0], circles[i][1], circles[i][2],
                    colors[i], 0x00000000, Shader.TileMode.CLAMP);
        }
    }

    @Override
    protected void onDraw(@NonNull Canvas canvas) {
        super.onDraw(canvas);
        if (washShader == null) return;
        wash.setShader(washShader);
        canvas.drawRect(0, 0, getWidth(), getHeight(), wash);
        for (int i = 0; i < glows.length; i++) {
            glow.setShader(glows[i]);
            canvas.drawCircle(circles[i][0], circles[i][1], circles[i][2], glow);
        }
    }
}
