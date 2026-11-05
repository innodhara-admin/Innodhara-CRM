package com.yuvipep.app.feature.auth;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import com.yuvipep.app.BuildConfig;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.EnvironmentStore;
import com.yuvipep.app.databinding.SheetEnvironmentBinding;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/** Debug-build server override (01: "long-press logo → environment sheet"). */
@AndroidEntryPoint
public class EnvironmentSheet extends BottomSheetDialogFragment {

    private static final String TAG = "EnvironmentSheet";
    /** F36: the login screen's `server:` chip refreshed only in onResume(), and
     *  dismissing a dialog never fires onResume() on the host fragment — so
     *  after Apply the chip kept showing the OLD address. It misleads on the one
     *  screen you use precisely when the backend is unreachable. Hosts listen
     *  for this and re-read the store. */
    public static final String RESULT_APPLIED = "environment_applied";

    @Inject EnvironmentStore environmentStore;

    private SheetEnvironmentBinding binding;

    public static void show(@NonNull FragmentManager fm) {
        new EnvironmentSheet().show(fm, TAG);
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetEnvironmentBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        refreshCurrent();
        binding.envUrlInput.setText(environmentStore.getBaseUrl());

        binding.envPresetEmulator.setOnClickListener(v ->
                binding.envUrlInput.setText(BuildConfig.EMULATOR_BASE_URL));

        binding.envReset.setOnClickListener(v -> {
            environmentStore.resetToDefault();
            binding.envUrlInput.setText(environmentStore.getBaseUrl());
            refreshCurrent();
            // F36: reset changes the address just as much as Apply does.
            getParentFragmentManager().setFragmentResult(RESULT_APPLIED, new Bundle());
        });

        binding.envApply.setOnClickListener(v -> {
            CharSequence text = binding.envUrlInput.getText();
            if (text != null && text.length() > 0) {
                environmentStore.setBaseUrl(text.toString());
            }
            // F36: tell whoever opened us that the address changed, BEFORE the
            // dismiss — a host that only refreshes in onResume() never hears
            // about it otherwise.
            getParentFragmentManager().setFragmentResult(RESULT_APPLIED, new Bundle());
            dismiss();
        });
    }

    private void refreshCurrent() {
        binding.envCurrent.setText(
                getString(R.string.env_current, environmentStore.getBaseUrl()));
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
