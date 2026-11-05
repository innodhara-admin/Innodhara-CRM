package com.yuvipep.app.feature.auth;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.db.AppDatabase;
import com.yuvipep.app.core.db.CachedUser;
import com.yuvipep.app.core.db.CachedUserDao;
import com.yuvipep.app.core.net.ApiError;
import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.ChangePasswordRequest;
import com.yuvipep.app.core.net.dto.ChangedResponse;
import com.yuvipep.app.core.net.dto.LoginRequest;
import com.yuvipep.app.core.net.dto.LoginResponse;
import com.yuvipep.app.core.net.dto.MeResponse;
import com.yuvipep.app.core.util.AppExecutors;

import java.io.IOException;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Response;

/**
 * Auth flows: login, session restore, forced password change, logout wipe.
 * All methods run on the io executor and call back on main.
 */
@Singleton
public class AuthRepository {

    /** Session restore outcome for the splash router. */
    public static final class SessionState {
        public static final int NONE = 0;          // no token → Login
        public static final int ACTIVE = 1;        // fresh /auth/me → Home
        public static final int FORCED_CHANGE = 2; // must_change_password
        public static final int OFFLINE_CACHED = 3;// network down, cache exists
        public static final int EXPIRED = 4;       // 401 → wiped → Login

        public final int kind;
        @Nullable public final CachedUser user;
        @Nullable public final ApiError error;

        SessionState(int kind, @Nullable CachedUser user, @Nullable ApiError error) {
            this.kind = kind;
            this.user = user;
            this.error = error;
        }
    }

    public interface Callback<T> {
        void onResult(@NonNull com.yuvipep.app.core.util.Result<T> result);
    }

    private final ApiService api;
    private final TokenStore tokenStore;
    private final CachedUserDao cachedUserDao;
    private final AppDatabase database;
    private final AppExecutors executors;
    private final com.yuvipep.app.feature.assistant.AssistantSession assistantSession;

    @Inject
    public AuthRepository(ApiService api, TokenStore tokenStore,
                          CachedUserDao cachedUserDao, AppDatabase database,
                          AppExecutors executors,
                          com.yuvipep.app.feature.assistant.AssistantSession
                                  assistantSession) {
        this.api = api;
        this.tokenStore = tokenStore;
        this.cachedUserDao = cachedUserDao;
        this.database = database;
        this.executors = executors;
        this.assistantSession = assistantSession;
    }

    /** Login, then warm the /auth/me cache (03 §1). */
    public void login(@NonNull String email, @NonNull String password,
                      @NonNull Callback<LoginResponse> callback) {
        executors.io().execute(() -> {
            try {
                Response<LoginResponse> response =
                        api.login(new LoginRequest(email.trim(), password)).execute();
                if (!response.isSuccessful() || response.body() == null) {
                    post(callback, com.yuvipep.app.core.util.Result.error(
                            ErrorMapper.fromResponse(response)));
                    return;
                }
                LoginResponse body = response.body();
                tokenStore.saveSession(body.accessToken, body.userId, body.role,
                        body.name, email.trim().toLowerCase(), body.orgName,
                        body.mustChangePassword);
                // Warm the session cache; login already succeeded, so a
                // failure here only skips branding — never blocks sign-in.
                try {
                    Response<MeResponse> me = api.me().execute();
                    if (me.isSuccessful() && me.body() != null) {
                        cachedUserDao.upsert(toCachedUser(me.body()));
                    }
                } catch (IOException ignored) {
                }
                post(callback, com.yuvipep.app.core.util.Result.success(body));
            } catch (IOException e) {
                post(callback, com.yuvipep.app.core.util.Result.error(
                        ErrorMapper.fromThrowable(e)));
            }
        });
    }

    /** Splash: token check → /auth/me → route (03 §0). */
    public void restoreSession(@NonNull java.util.function.Consumer<SessionState> callback) {
        executors.io().execute(() -> {
            if (!tokenStore.hasSession()) {
                postState(callback, new SessionState(SessionState.NONE, null, null));
                return;
            }
            try {
                Response<MeResponse> response = api.me().execute();
                if (response.isSuccessful() && response.body() != null) {
                    MeResponse me = response.body();
                    CachedUser user = toCachedUser(me);
                    cachedUserDao.upsert(user);
                    int kind = tokenStore.mustChangePassword()
                            ? SessionState.FORCED_CHANGE : SessionState.ACTIVE;
                    postState(callback, new SessionState(kind, user, null));
                } else if (response.code() == 401) {
                    // AuthInterceptor already wiped the token.
                    postState(callback, new SessionState(SessionState.EXPIRED, null,
                            ErrorMapper.fromResponse(response)));
                } else {
                    // Server trouble ≠ invalid session: fall back to cache.
                    fallBackToCache(callback, ErrorMapper.fromResponse(response));
                }
            } catch (IOException e) {
                fallBackToCache(callback, ErrorMapper.fromThrowable(e));
            }
        });
    }

    private void fallBackToCache(@NonNull java.util.function.Consumer<SessionState> callback,
                                 @NonNull ApiError error) {
        CachedUser cached = cachedUserDao.get(
                tokenStore.getUserId() != null ? tokenStore.getUserId() : "");
        if (cached != null) {
            postState(callback, new SessionState(SessionState.OFFLINE_CACHED, cached, error));
        } else {
            // No cache to stand on — honest: back to login with the reason.
            postState(callback, new SessionState(SessionState.NONE, null, error));
        }
    }

    public void changePassword(@NonNull String current, @NonNull String newPassword,
                               @NonNull Callback<ChangedResponse> callback) {
        executors.io().execute(() -> {
            try {
                Response<ChangedResponse> response = api.changePassword(
                        new ChangePasswordRequest(current, newPassword)).execute();
                if (response.isSuccessful() && response.body() != null) {
                    tokenStore.setMustChangePassword(false);
                    post(callback, com.yuvipep.app.core.util.Result.success(response.body()));
                } else {
                    post(callback, com.yuvipep.app.core.util.Result.error(
                            ErrorMapper.fromResponse(response)));
                }
            } catch (IOException e) {
                post(callback, com.yuvipep.app.core.util.Result.error(
                        ErrorMapper.fromThrowable(e)));
            }
        });
    }

    /** Logout = token + cache wipe (org isolation, 09 §3). The assistant's
     *  conversation goes too: the backend keys turns by user, but the bubbles
     *  and recent-command chips already on this device are the previous
     *  person's words and must not greet the next one. */
    public void logout(@NonNull Runnable onDone) {
        executors.io().execute(() -> {
            tokenStore.clear();
            database.clearAllTables();
            assistantSession.reset();
            executors.main().execute(onDone);
        });
    }

    private static CachedUser toCachedUser(@NonNull MeResponse me) {
        CachedUser user = new CachedUser();
        user.userId = me.userId != null ? me.userId : "";
        user.email = me.email;
        user.name = me.name;
        user.role = me.role;
        user.orgId = me.orgId;
        user.orgName = me.orgName;
        user.orgSlug = me.orgSlug;
        user.orgLogoUrl = me.orgLogoUrl;
        if (me.orgBrandColors != null) {
            user.brandPrimary = me.orgBrandColors.get("primary");
            user.brandAccent = me.orgBrandColors.get("accent");
        }
        user.phone = me.phone;
        user.designation = me.designation;
        user.department = me.department;
        user.orgTimezone = me.orgTimezone;
        user.hasEmailAppPassword = me.hasEmailAppPassword;
        user.fetchedAt = System.currentTimeMillis();
        return user;
    }

    private <T> void post(@NonNull Callback<T> callback,
                          @NonNull com.yuvipep.app.core.util.Result<T> result) {
        executors.main().execute(() -> callback.onResult(result));
    }

    private void postState(@NonNull java.util.function.Consumer<SessionState> callback,
                           @NonNull SessionState state) {
        executors.main().execute(() -> callback.accept(state));
    }
}
