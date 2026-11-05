package com.yuvipep.app.core.util;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiError;

/**
 * Loading | Success | Error — the one state type every ViewModel exposes
 * (02_ARCHITECTURE §6).
 */
public final class Result<T> {

    public enum Status { LOADING, SUCCESS, ERROR }

    @NonNull public final Status status;
    @Nullable public final T data;
    @Nullable public final ApiError error;

    private Result(@NonNull Status status, @Nullable T data, @Nullable ApiError error) {
        this.status = status;
        this.data = data;
        this.error = error;
    }

    public static <T> Result<T> loading() {
        return new Result<>(Status.LOADING, null, null);
    }

    public static <T> Result<T> success(@NonNull T data) {
        return new Result<>(Status.SUCCESS, data, null);
    }

    public static <T> Result<T> error(@NonNull ApiError error) {
        return new Result<>(Status.ERROR, null, error);
    }

    public boolean isLoading() { return status == Status.LOADING; }
    public boolean isSuccess() { return status == Status.SUCCESS; }
    public boolean isError() { return status == Status.ERROR; }
}
