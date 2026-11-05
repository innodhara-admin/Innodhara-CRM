package com.yuvipep.app.feature.auth;

import android.content.Intent;
import android.os.Bundle;
import android.view.WindowManager;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.Fragment;

import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.LoginResponse;
import com.yuvipep.app.databinding.ActivityAuthBinding;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Auth world: splash → login → forced password change → MainActivity.
 * FLAG_SECURE keeps credentials off screenshots (09 §3).
 */
@AndroidEntryPoint
public class AuthActivity extends AppCompatActivity {

    public static final String EXTRA_OFFLINE_SESSION = "offline_session";
    public static final String EXTRA_SESSION_EXPIRED = "session_expired";

    private ActivityAuthBinding binding;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // FLAG_SECURE keeps credentials off screenshots (09 §3). Debug
        // builds allow capture — needed for UI verification tooling.
        if (!com.yuvipep.app.BuildConfig.DEBUG) {
            getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE,
                    WindowManager.LayoutParams.FLAG_SECURE);
        }
        setTheme(R.style.Theme_YuviPep);
        binding = ActivityAuthBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        if (savedInstanceState == null) {
            if (getIntent().getBooleanExtra(EXTRA_SESSION_EXPIRED, false)) {
                Toast.makeText(this, R.string.session_expired, Toast.LENGTH_LONG).show();
                showFragment(new LoginFragment());
            } else {
                showFragment(new SplashFragment());
            }
        }
    }

    /** Splash router. */
    void onSessionState(@NonNull AuthRepository.SessionState state) {
        switch (state.kind) {
            case AuthRepository.SessionState.ACTIVE:
                goToMain(false);
                break;
            case AuthRepository.SessionState.OFFLINE_CACHED:
                goToMain(true);
                break;
            case AuthRepository.SessionState.FORCED_CHANGE:
                showFragment(new ForcedPasswordChangeFragment());
                break;
            case AuthRepository.SessionState.EXPIRED:
                Toast.makeText(this, R.string.session_expired, Toast.LENGTH_LONG).show();
                showFragment(new LoginFragment());
                break;
            case AuthRepository.SessionState.NONE:
            default:
                if (state.error != null) {
                    Toast.makeText(this, state.error.message, Toast.LENGTH_LONG).show();
                }
                showFragment(new LoginFragment());
                break;
        }
    }

    void onLoginSuccess(@NonNull LoginResponse login) {
        if (login.mustChangePassword) {
            showFragment(new ForcedPasswordChangeFragment());
        } else {
            goToMain(false);
        }
    }

    void onPasswordChanged() {
        goToMain(false);
    }

    private void goToMain(boolean offline) {
        Intent intent = new Intent(this, MainActivity.class);
        intent.putExtra(EXTRA_OFFLINE_SESSION, offline);
        startActivity(intent);
        finish();
    }

    private void showFragment(@NonNull Fragment fragment) {
        getSupportFragmentManager().beginTransaction()
                .replace(binding.authContainer.getId(), fragment)
                .commitAllowingStateLoss();
    }
}
