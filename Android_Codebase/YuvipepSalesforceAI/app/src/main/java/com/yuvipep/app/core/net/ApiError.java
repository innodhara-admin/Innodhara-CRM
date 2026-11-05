package com.yuvipep.app.core.net;

import androidx.annotation.NonNull;

/**
 * A typed, human-renderable API failure. The backend writes its error
 * messages for humans ({"detail": "..."}), so screens show them verbatim
 * (02 §4 ErrorMapper).
 */
public final class ApiError {

    /** HTTP status, or 0 for transport-level failures (offline, timeout). */
    public final int httpCode;
    @NonNull public final String message;
    /** True when the failure is connectivity, not the server refusing. */
    public final boolean isNetwork;

    public ApiError(int httpCode, @NonNull String message, boolean isNetwork) {
        this.httpCode = httpCode;
        this.message = message;
        this.isNetwork = isNetwork;
    }

    public boolean isUnauthorized() {
        return httpCode == 401;
    }

    @NonNull
    @Override
    public String toString() {
        return "ApiError(" + httpCode + ", " + message + ")";
    }
}
