package com.yuvipep.app.core.net;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import java.io.IOException;
import java.security.GeneralSecurityException;

import javax.inject.Inject;
import javax.inject.Singleton;

import dagger.hilt.android.qualifiers.ApplicationContext;

/**
 * JWT + session identity in EncryptedSharedPreferences (Keystore-backed,
 * 09_SECURITY §1). Falls back to plain prefs only if the Keystore is
 * broken on this device — logged, never silent.
 */
@Singleton
public class TokenStore {

    private static final String PREFS = "yuvipep_secure";
    private static final String KEY_TOKEN = "jwt";
    private static final String KEY_USER_ID = "user_id";
    private static final String KEY_ROLE = "role";
    private static final String KEY_NAME = "name";
    private static final String KEY_EMAIL = "email";
    private static final String KEY_ORG_NAME = "org_name";
    private static final String KEY_MUST_CHANGE = "must_change_password";

    private final SharedPreferences prefs;

    @Inject
    public TokenStore(@ApplicationContext Context context) {
        SharedPreferences p;
        try {
            MasterKey masterKey = new MasterKey.Builder(context)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build();
            p = EncryptedSharedPreferences.create(
                    context,
                    PREFS,
                    masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
        } catch (GeneralSecurityException | IOException e) {
            android.util.Log.e("TokenStore",
                    "Keystore unavailable — falling back to plain prefs", e);
            p = context.getSharedPreferences(PREFS + "_plain", Context.MODE_PRIVATE);
        }
        this.prefs = p;
    }

    public synchronized void saveSession(@NonNull String token, @NonNull String userId,
                                         @NonNull String role, @NonNull String name,
                                         @NonNull String email, @Nullable String orgName,
                                         boolean mustChangePassword) {
        prefs.edit()
                .putString(KEY_TOKEN, token)
                .putString(KEY_USER_ID, userId)
                .putString(KEY_ROLE, role)
                .putString(KEY_NAME, name)
                .putString(KEY_EMAIL, email)
                .putString(KEY_ORG_NAME, orgName)
                .putBoolean(KEY_MUST_CHANGE, mustChangePassword)
                .apply();
    }

    public synchronized void updateToken(@NonNull String token) {
        prefs.edit().putString(KEY_TOKEN, token).apply();
    }

    public synchronized void setMustChangePassword(boolean value) {
        prefs.edit().putBoolean(KEY_MUST_CHANGE, value).apply();
    }

    @Nullable public String getToken() { return prefs.getString(KEY_TOKEN, null); }
    @Nullable public String getUserId() { return prefs.getString(KEY_USER_ID, null); }
    @Nullable public String getRole() { return prefs.getString(KEY_ROLE, null); }
    @Nullable public String getName() { return prefs.getString(KEY_NAME, null); }
    @Nullable public String getEmail() { return prefs.getString(KEY_EMAIL, null); }
    @Nullable public String getOrgName() { return prefs.getString(KEY_ORG_NAME, null); }
    public boolean mustChangePassword() { return prefs.getBoolean(KEY_MUST_CHANGE, false); }

    public boolean hasSession() {
        String t = getToken();
        return t != null && !t.isEmpty();
    }

    /** Wipe on logout / session expiry — org isolation on shared devices. */
    public synchronized void clear() {
        prefs.edit().clear().apply();
    }
}
