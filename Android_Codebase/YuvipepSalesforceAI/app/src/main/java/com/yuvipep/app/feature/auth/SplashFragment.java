package com.yuvipep.app.feature.auth;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import com.yuvipep.app.BuildConfig;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.EnvironmentStore;
import com.yuvipep.app.databinding.FragmentSplashBinding;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Splash: token check → /auth/me → route (03 §0). Long-press the logo in
 * debug builds for the Environment sheet.
 */
@AndroidEntryPoint
public class SplashFragment extends Fragment {

    @Inject EnvironmentStore environmentStore;

    private FragmentSplashBinding binding;
    private AuthViewModel viewModel;
    private boolean navigated = false;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentSplashBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        viewModel = new ViewModelProvider(requireActivity()).get(AuthViewModel.class);

        String envLabel = shortHost(environmentStore.getBaseUrl());
        binding.splashVersion.setText(
                getString(R.string.splash_version, BuildConfig.VERSION_NAME, envLabel));

        // Available in every build — see the note in LoginFragment. A splash
        // that cannot be re-pointed strands the user when the stored address
        // has gone stale, which is exactly when they need it.
        binding.splashLogo.setOnLongClickListener(v -> {
            EnvironmentSheet.show(getParentFragmentManager());
            return true;
        });

        viewModel.sessionState().observe(getViewLifecycleOwner(), state -> {
            if (state == null || navigated) return;
            navigated = true;
            ((AuthActivity) requireActivity()).onSessionState(state);
        });
        viewModel.restoreSession();
    }

    static String shortHost(String url) {
        String host = url.replaceFirst("^https?://", "");
        int slash = host.indexOf('/');
        if (slash > 0) host = host.substring(0, slash);
        return host;
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
