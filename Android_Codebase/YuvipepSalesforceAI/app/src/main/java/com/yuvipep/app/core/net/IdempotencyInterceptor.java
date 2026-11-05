package com.yuvipep.app.core.net;

import androidx.annotation.NonNull;

import java.io.IOException;
import java.util.UUID;

import javax.inject.Inject;
import javax.inject.Singleton;

import okhttp3.Interceptor;
import okhttp3.Request;
import okhttp3.Response;

/**
 * Adds an Idempotency-Key to every state-changing request so a retry can
 * never duplicate a send or a task (backend: idempotency_records).
 *
 * Callers that queue work offline (Phase 1+ OfflineQueue) mint the key at
 * intent time and set the header themselves — an explicit header always
 * wins; this interceptor only fills the gap.
 */
@Singleton
public class IdempotencyInterceptor implements Interceptor {

    public static final String HEADER = "Idempotency-Key";

    @Inject
    public IdempotencyInterceptor() {
    }

    @NonNull
    @Override
    public Response intercept(@NonNull Chain chain) throws IOException {
        Request request = chain.request();
        String method = request.method();
        boolean stateChanging = method.equals("POST") || method.equals("PATCH")
                || method.equals("PUT") || method.equals("DELETE");
        if (stateChanging && request.header(HEADER) == null) {
            request = request.newBuilder()
                    .header(HEADER, UUID.randomUUID().toString())
                    .build();
        }
        return chain.proceed(request);
    }
}
