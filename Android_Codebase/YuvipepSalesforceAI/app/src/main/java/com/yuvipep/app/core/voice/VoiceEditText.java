package com.yuvipep.app.core.voice;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.drawable.Drawable;
import android.util.AttributeSet;
import android.view.MotionEvent;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.drawable.DrawableCompat;

import com.google.android.material.color.MaterialColors;
import com.google.android.material.textfield.TextInputEditText;
import com.yuvipep.app.R;

/**
 * The "everything typeable is dictatable" input (03 preamble, 06 §2): a
 * TextInputEditText with a mic at the end. Tap the mic → live dictation is
 * appended at the current text; tap again to stop. Works inside a
 * TextInputLayout and as a plain dialog field.
 */
public class VoiceEditText extends TextInputEditText {

    private static final int PERMISSION_REQUEST = 7301;

    @Nullable private SpeechInput speech;
    private boolean listening;
    private String baseText = "";
    @Nullable private CharSequence idleHint;

    public VoiceEditText(@NonNull Context context) {
        super(context);
        init();
    }

    public VoiceEditText(@NonNull Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    public VoiceEditText(@NonNull Context context, @Nullable AttributeSet attrs,
                         int defStyleAttr) {
        super(context, attrs, defStyleAttr);
        init();
    }

    private void init() {
        setMicIcon(false);
    }

    private void setMicIcon(boolean active) {
        Drawable mic = ContextCompat.getDrawable(getContext(), R.drawable.ic_mic);
        if (mic == null) return;
        mic = DrawableCompat.wrap(mic.mutate());
        int color = active
                ? MaterialColors.getColor(this,
                        androidx.appcompat.R.attr.colorPrimary)
                : MaterialColors.getColor(this,
                        com.google.android.material.R.attr.colorOnSurfaceVariant);
        DrawableCompat.setTint(mic, color);
        mic.setBounds(0, 0, mic.getIntrinsicWidth(), mic.getIntrinsicHeight());
        setCompoundDrawablesRelative(null, null, mic, null);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        Drawable end = getCompoundDrawablesRelative()[2];
        if (end != null && event.getAction() == MotionEvent.ACTION_UP) {
            boolean rtl = getLayoutDirection() == LAYOUT_DIRECTION_RTL;
            int iconWidth = end.getBounds().width() + getCompoundDrawablePadding();
            boolean onIcon = rtl
                    ? event.getX() <= getPaddingStart() + iconWidth
                    : event.getX() >= getWidth() - getPaddingEnd() - iconWidth;
            if (onIcon) {
                toggleDictation();
                return true;
            }
        }
        return super.onTouchEvent(event);
    }

    /** True when this field is laid out for several lines of text. */
    private boolean isMultiLine() {
        int type = getInputType();
        boolean multiLineFlag = (type & android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE) != 0;
        return multiLineFlag || getMaxLines() > 1 || getMinLines() > 1;
    }

    private void toggleDictation() {
        if (listening) {
            if (speech != null) speech.stop();
            return;
        }
        Context context = getContext();
        if (!SpeechInput.available(context)) {
            Toast.makeText(context, R.string.voice_unavailable, Toast.LENGTH_LONG).show();
            return;
        }
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(context, R.string.voice_permission_hint, Toast.LENGTH_LONG).show();
            Activity activity = activityFrom(context);
            if (activity != null) {
                ActivityCompat.requestPermissions(activity,
                        new String[]{Manifest.permission.RECORD_AUDIO}, PERMISSION_REQUEST);
            }
            return;
        }
        startDictation();
    }

    private void startDictation() {
        if (speech == null) speech = new SpeechInput();
        // A multi-line field holds an account of something (meeting notes),
        // and people pause while telling it: give dictation its longer
        // patience there, and leave one-line fields as snappy as they were.
        speech.setLongForm(isMultiLine());
        listening = true;
        baseText = getText() == null ? "" : getText().toString();
        if (!baseText.isEmpty() && !baseText.endsWith(" ")) baseText += " ";
        idleHint = getHint();
        setHint(R.string.voice_listening);
        setMicIcon(true);
        speech.start(getContext(), new SpeechInput.Listener() {
            @Override
            public void onPartial(@NonNull String text) {
                setTextKeepingCursorAtEnd(baseText + text);
            }

            @Override
            public void onFinal(@NonNull String text) {
                setTextKeepingCursorAtEnd(baseText + text);
            }

            @Override
            public void onTranscribing() {
                // The clip is uploading. Say so — "Listening…" while the mic
                // is already closed reads as a hang.
                setHint(R.string.voice_transcribing);
            }

            @Override
            public void onError(@NonNull String message) {
                Toast.makeText(getContext(), message, Toast.LENGTH_SHORT).show();
            }

            @Override
            public void onEnd() {
                listening = false;
                setHint(idleHint);
                setMicIcon(false);
            }
        });
    }

    private void setTextKeepingCursorAtEnd(@NonNull String text) {
        setText(text);
        setSelection(text.length());
    }

    @Nullable
    private static Activity activityFrom(@Nullable Context context) {
        while (context instanceof android.content.ContextWrapper) {
            if (context instanceof Activity) return (Activity) context;
            context = ((android.content.ContextWrapper) context).getBaseContext();
        }
        return null;
    }

    @Override
    protected void onDetachedFromWindow() {
        if (speech != null) {
            speech.destroy();
            speech = null;
        }
        listening = false;
        super.onDetachedFromWindow();
    }
}
