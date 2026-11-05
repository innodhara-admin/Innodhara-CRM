package com.yuvipep.app.feature.auth;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import com.yuvipep.app.R;
import com.yuvipep.app.databinding.FragmentForcedChangeBinding;

import dagger.hilt.android.AndroidEntryPoint;

/** Forced first-login password change — honored before any other screen. */
@AndroidEntryPoint
public class ForcedPasswordChangeFragment extends Fragment {

    private FragmentForcedChangeBinding binding;
    private AuthViewModel viewModel;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentForcedChangeBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        viewModel = new ViewModelProvider(requireActivity()).get(AuthViewModel.class);

        binding.savePasswordButton.setOnClickListener(v -> submit());

        viewModel.changeState().observe(getViewLifecycleOwner(), result -> {
            if (result == null) return;
            boolean loading = result.isLoading();
            binding.changeProgress.setVisibility(loading ? View.VISIBLE : View.GONE);
            binding.savePasswordButton.setEnabled(!loading);
            if (result.isError() && result.error != null) {
                binding.changeError.setText(result.error.message);
                binding.changeError.setVisibility(View.VISIBLE);
            } else {
                binding.changeError.setVisibility(View.GONE);
            }
            if (result.isSuccess()) {
                ((AuthActivity) requireActivity()).onPasswordChanged();
            }
        });
    }

    private void submit() {
        String current = text(binding.currentPasswordInput.getText());
        String fresh = text(binding.newPasswordInput.getText());
        String confirm = text(binding.confirmPasswordInput.getText());

        binding.confirmPasswordLayout.setError(null);
        if (!fresh.equals(confirm)) {
            binding.confirmPasswordLayout.setError(
                    getString(R.string.error_passwords_differ));
            return;
        }
        // Length etc. is the backend's rule — its message is shown verbatim.
        viewModel.changePassword(current, fresh);
    }

    private static String text(@Nullable CharSequence cs) {
        return cs == null ? "" : cs.toString();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
