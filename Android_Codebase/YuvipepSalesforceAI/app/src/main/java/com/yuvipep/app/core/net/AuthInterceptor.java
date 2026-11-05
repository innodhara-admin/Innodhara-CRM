package com.yuvipep.app.core.net;

import androidx.annotation.NonNull;

import com.yuvipep.app.core.db.AppDatabase;
import com.yuvipep.app.feature.assistant.AssistantSession;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.inject.Inject;
import javax.inject.Singleton;

import dagger.Lazy;
import okhttp3.Interceptor;
import okhttp3.Request;
import okhttp3.Response;

/**
 * Injects the Bearer token; a 401 on an authenticated call wipes the
 * session and signals SessionBus (02 §4).
 *
 * Two deliberate exceptions to the 401 rule:
 *  - /auth/login       → 401 just means wrong credentials.
 *  - /auth/change-password → 401 means the current password was wrong;
 *    the session itself is still valid, so it must NOT be wiped.
 *
 * The wipe is the SAME wipe {@link com.yuvipep.app.feature.auth.AuthRepository#logout}
 * performs (finding F1). It used to clear only the token, which left the
 * previous user's cached notifications, approvals, tasks and Jarvis transcript
 * on the device: after a server-side reseed, signing in as a different person
 * showed a bell badge of 33 and a notification centre full of someone else's
 * rows that no longer existed on the server. On a shared or reassigned device
 * that is the previous person's data shown to the next one.
 *
 * It lives here rather than in the SessionBus observer because a 401 can arrive
 * with no Activity alive at all — the 15-minute notification worker is exactly
 * that case, and a wipe that only happens when a screen is watching is not a
 * wipe.
 */
@Singleton
public class AuthInterceptor implements Interceptor {

    private final TokenStore tokenStore;
    private final SessionBus sessionBus;
    /** Lazy: the interceptor is built with the OkHttp client at startup, and
     *  Room should not be opened just because the network stack exists. */
    private final Lazy<AppDatabase> database;
    private final Lazy<AssistantSession> assistantSession;
    /** Concurrent 401s are normal — the 60-second notification poll easily
     *  races a screen load — and must not each run a full Room wipe. */
    private final AtomicBoolean wiping = new AtomicBoolean(false);

    @Inject
    public AuthInterceptor(TokenStore tokenStore, SessionBus sessionBus,
                           Lazy<AppDatabase> database,
                           Lazy<AssistantSession> assistantSession) {
        this.tokenStore = tokenStore;
        this.sessionBus = sessionBus;
        this.database = database;
        this.assistantSession = assistantSession;
    }

    @NonNull
    @Override
    public Response intercept(@NonNull Chain chain) throws IOException {
        Request original = chain.request();
        String path = original.url().encodedPath();
        String token = tokenStore.getToken();

        Request request = original;
        if (token != null && !path.endsWith("/auth/login")) {
            request = original.newBuilder()
                    .header("Authorization", "Bearer " + token)
                    .build();
        }

        Response response = chain.proceed(request);

        boolean loginCall = path.endsWith("/auth/login");
        boolean changePasswordCall = path.endsWith("/auth/change-password");
        if (response.code() == 401 && !loginCall && !changePasswordCall) {
            wipeSession();
        }
        return response;
    }

    /**
     * Token + cached data + assistant transcript, the same three things
     * {@code AuthRepository.logout()} clears. Safe here: interceptors run on
     * OkHttp's dispatcher threads, never the main thread, so the Room wipe is
     * allowed to be synchronous.
     */
    private void wipeSession() {
        if (!wiping.compareAndSet(false, true)) {
            return;     // another 401 on a parallel call is already wiping
        }
        try {
            tokenStore.clear();
            database.get().clearAllTables();
            assistantSession.get().reset();
        } catch (RuntimeException wipeFailed) {
            // The token is already gone, so the session is dead either way —
            // never let a cache-wipe failure turn into a crash on a background
            // thread. Falling through still routes the user to Login.
            android.util.Log.w("AuthInterceptor",
                    "Session wipe incomplete after 401", wipeFailed);
        } finally {
            wiping.set(false);
        }
        sessionBus.notifySessionExpired();
    }
}
