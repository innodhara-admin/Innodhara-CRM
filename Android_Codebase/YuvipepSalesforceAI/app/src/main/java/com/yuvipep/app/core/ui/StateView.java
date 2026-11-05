package com.yuvipep.app.core.ui;

import android.content.Context;
import android.util.AttributeSet;
import android.view.LayoutInflater;
import android.view.View;
import android.widget.FrameLayout;

import androidx.annotation.DrawableRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.R;
import com.yuvipep.app.databinding.ViewStateBinding;

/**
 * Unified loading / empty / error / offline view (06_DESIGN_SYSTEM §2).
 * Every error shows the backend's own message plus a Retry; nothing ever
 * dead-ends.
 */
public class StateView extends FrameLayout {

    private final ViewStateBinding binding;

    public StateView(@NonNull Context context) {
        this(context, null);
    }

    public StateView(@NonNull Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        binding = ViewStateBinding.inflate(LayoutInflater.from(context), this, true);
    }

    public void showLoading() {
        showLoading(getContext().getString(R.string.state_loading));
    }

    public void showLoading(@NonNull String title) {
        setVisibility(VISIBLE);
        binding.stateProgress.setVisibility(VISIBLE);
        binding.stateIcon.setVisibility(GONE);
        binding.stateTitle.setText(title);
        binding.stateBody.setVisibility(GONE);
        binding.stateAction.setVisibility(GONE);
    }

    public void showEmpty(@NonNull String title, @Nullable String body,
                          @DrawableRes int icon,
                          @Nullable String actionLabel, @Nullable Runnable action) {
        setVisibility(VISIBLE);
        binding.stateProgress.setVisibility(GONE);
        if (icon != 0) {
            binding.stateIcon.setImageResource(icon);
            binding.stateIcon.setVisibility(VISIBLE);
        } else {
            binding.stateIcon.setVisibility(GONE);
        }
        binding.stateTitle.setText(title);
        setBody(body);
        setAction(actionLabel, action);
    }

    public void showError(@NonNull String backendMessage, @Nullable Runnable retry) {
        setVisibility(VISIBLE);
        binding.stateProgress.setVisibility(GONE);
        binding.stateIcon.setVisibility(GONE);
        binding.stateTitle.setText(R.string.state_error_generic);
        setBody(backendMessage);
        setAction(retry != null ? getContext().getString(R.string.state_retry) : null, retry);
    }

    public void showOffline(@Nullable String detail, @Nullable Runnable retry) {
        setVisibility(VISIBLE);
        binding.stateProgress.setVisibility(GONE);
        binding.stateIcon.setVisibility(GONE);
        binding.stateTitle.setText(R.string.state_offline);
        setBody(detail);
        setAction(retry != null ? getContext().getString(R.string.state_retry) : null, retry);
    }

    public void hide() {
        setVisibility(GONE);
    }

    private void setBody(@Nullable String body) {
        if (body == null || body.isEmpty()) {
            binding.stateBody.setVisibility(GONE);
        } else {
            binding.stateBody.setText(body);
            binding.stateBody.setVisibility(VISIBLE);
        }
    }

    private void setAction(@Nullable String label, @Nullable Runnable action) {
        if (label == null || action == null) {
            binding.stateAction.setVisibility(GONE);
            binding.stateAction.setOnClickListener(null);
        } else {
            binding.stateAction.setText(label);
            binding.stateAction.setVisibility(VISIBLE);
            binding.stateAction.setOnClickListener(new OnClickListener() {
                @Override
                public void onClick(View v) {
                    action.run();
                }
            });
        }
    }
}
