package com.yuvipep.app.core.net;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;

import com.yuvipep.app.BuildConfig;

import javax.inject.Inject;
import javax.inject.Singleton;

import dagger.hilt.android.qualifiers.ApplicationContext;

/**
 * Runtime base-URL override (01_BACKEND_CONTRACT: BuildConfig default +
 * login-screen environment sheet). Not secret — plain prefs, survives
 * logout so a dev/demo device keeps pointing at its server.
 */
@Singleton
public class EnvironmentStore {

    private static final String PREFS = "yuvipep_env";
    private static final String KEY_BASE_URL = "base_url";

    private final SharedPreferences prefs;

    @Inject
    public EnvironmentStore(@ApplicationContext Context context) {
        this.prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** Always returns a normalized URL without trailing slash. */
    @NonNull
    public String getBaseUrl() {
        String url = prefs.getString(KEY_BASE_URL, null);
        if (url == null || url.trim().isEmpty()) {
            url = BuildConfig.DEFAULT_BASE_URL;
        }
        return normalize(url);
    }

    public void setBaseUrl(@NonNull String url) {
        prefs.edit().putString(KEY_BASE_URL, normalize(url)).apply();
    }

    public void resetToDefault() {
        prefs.edit().remove(KEY_BASE_URL).apply();
    }

    public boolean isOverridden() {
        return prefs.getString(KEY_BASE_URL, null) != null;
    }

    @NonNull
    private static String normalize(@NonNull String url) {
        String u = url.trim();
        while (u.endsWith("/")) {
            u = u.substring(0, u.length() - 1);
        }
        return u;
    }
}
