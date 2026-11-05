package com.yuvipep.app.core.net;

import androidx.annotation.NonNull;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

import javax.inject.Inject;
import javax.inject.Singleton;

import okhttp3.Interceptor;
import okhttp3.Request;
import okhttp3.Response;

/**
 * Per-route timeouts (02 §4): LLM-backed calls wait 120s, the meeting audio
 * upload gets 600s of write time; everything else keeps the client defaults.
 */
@Singleton
public class TimeoutInterceptor implements Interceptor {

    @Inject
    public TimeoutInterceptor() {
    }

    @NonNull
    @Override
    public Response intercept(@NonNull Chain chain) throws IOException {
        Request request = chain.request();
        String path = request.url().encodedPath();
        if (path.endsWith("/meetings/upload")) {
            return chain
                    .withWriteTimeout(600, TimeUnit.SECONDS)
                    .withReadTimeout(120, TimeUnit.SECONDS)
                    .proceed(request);
        }
        if (path.endsWith("/meetings/notes") || path.endsWith("/assistant/command")
                || path.endsWith("/assistant/voice/turn")
                || path.contains("/contacts/from-card")
                || (path.contains("/proposals/") && (path.endsWith("/edit")
                        || path.endsWith("/download") || path.endsWith("/approve-send")
                        || path.endsWith("/upload-revision")))
                || (path.contains("/projects/") && (path.endsWith("/phase-shift")
                        || path.endsWith("/whats-blocking") || path.endsWith("/brief")
                        || path.endsWith("/weekly-report") || path.endsWith("/members")))) {
            // These route through the LLM-backed assistant/planner engines
            // (onboarding brief, blocking summary, phase-shift replan, weekly
            // report) — same 120s allowance as the assistant command path.
            return chain.withReadTimeout(120, TimeUnit.SECONDS).proceed(request);
        }
        return chain.proceed(request);
    }
}
