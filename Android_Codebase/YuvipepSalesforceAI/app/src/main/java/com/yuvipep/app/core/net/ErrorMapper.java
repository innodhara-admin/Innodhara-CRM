package com.yuvipep.app.core.net;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;

import okhttp3.ResponseBody;
import retrofit2.Response;

/**
 * Backend error envelope → typed ApiError. FastAPI errors arrive as
 * {"detail": "human message"} (AppError handler in app/main.py) or, for
 * request validation, {"detail": [{loc, msg, ...}]}. Whatever arrives, the
 * user sees the backend's own words — never a fake "unknown error" when a
 * real message exists.
 */
public final class ErrorMapper {

    private static final Gson GSON = new Gson();

    private ErrorMapper() {
    }

    @NonNull
    public static ApiError fromResponse(@NonNull Response<?> response) {
        String message = null;
        try (ResponseBody body = response.errorBody()) {
            if (body != null) {
                message = extractDetail(body.string());
            }
        } catch (IOException | RuntimeException ignored) {
            // fall through to status-line fallback
        }
        if (message == null || message.isEmpty()) {
            message = fallbackForStatus(response.code());
        }
        return new ApiError(response.code(), message, false);
    }

    @NonNull
    public static ApiError fromThrowable(@NonNull Throwable t) {
        if (t instanceof UnknownHostException) {
            return new ApiError(0, "Can’t reach the server — check your connection", true);
        }
        if (t instanceof SocketTimeoutException) {
            return new ApiError(0, "The server is taking too long — try again", true);
        }
        if (t instanceof IOException) {
            return new ApiError(0, "Network trouble — check your connection and retry", true);
        }
        String msg = t.getMessage();
        return new ApiError(0, msg != null ? msg : "Something went wrong", false);
    }

    @Nullable
    static String extractDetail(@Nullable String rawBody) {
        if (rawBody == null || rawBody.isEmpty()) return null;
        try {
            JsonElement root = JsonParser.parseString(rawBody);
            if (!root.isJsonObject()) return null;
            JsonElement detail = root.getAsJsonObject().get("detail");
            if (detail == null) return null;
            if (detail.isJsonPrimitive()) {
                return detail.getAsString();
            }
            if (detail.isJsonArray() && !detail.getAsJsonArray().isEmpty()) {
                // Pydantic validation list — surface the first human message.
                JsonElement first = detail.getAsJsonArray().get(0);
                if (first.isJsonObject()) {
                    JsonObject obj = first.getAsJsonObject();
                    if (obj.has("msg")) return obj.get("msg").getAsString();
                }
                return GSON.toJson(first);
            }
        } catch (RuntimeException ignored) {
            // not JSON — ignore
        }
        return null;
    }

    @NonNull
    private static String fallbackForStatus(int code) {
        if (code == 401) return "You’re signed out — please sign in again";
        if (code == 403) return "Your role can’t do this";
        if (code == 404) return "Not found on the server";
        if (code >= 500) return "The server hit a problem (" + code + ") — try again shortly";
        return "Request failed (" + code + ")";
    }
}
