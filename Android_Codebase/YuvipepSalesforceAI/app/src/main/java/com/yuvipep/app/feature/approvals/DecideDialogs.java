package com.yuvipep.app.feature.approvals;

import android.content.Context;
import android.text.InputType;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.FrameLayout;

import androidx.annotation.NonNull;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;

import java.util.function.Consumer;

/** The reject-with-note sheet used from Home, the inbox and the detail. */
public final class DecideDialogs {

    private DecideDialogs() {
    }

    public static void rejectWithNote(@NonNull Context context,
                                      @NonNull Consumer<String> onReject) {
        // Dictatable (Phase 5): the note field carries a mic like every
        // other text input (03 preamble).
        EditText input = new com.yuvipep.app.core.voice.VoiceEditText(context);
        input.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        input.setMinLines(2);
        input.setHint(R.string.reject_note_hint);
        FrameLayout wrapper = new FrameLayout(context);
        int pad = (int) (20 * context.getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);
        wrapper.addView(input, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        new MaterialAlertDialogBuilder(context)
                .setTitle(R.string.reject_note_title)
                .setView(wrapper)
                .setPositiveButton(R.string.action_send_rejection, (d, w) -> {
                    String note = input.getText().toString().trim();
                    onReject.accept(note.isEmpty() ? null : note);
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }
}
