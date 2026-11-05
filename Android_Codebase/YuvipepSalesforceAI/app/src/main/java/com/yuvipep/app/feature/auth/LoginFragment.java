package com.yuvipep.app.feature.auth;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.EnvironmentStore;
import com.yuvipep.app.databinding.FragmentLoginBinding;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Login — no self-signup, honest copy (03 §1). Backend error messages are
 * shown verbatim.
 */
@AndroidEntryPoint
public class LoginFragment extends Fragment {

    @Inject EnvironmentStore environmentStore;

    private FragmentLoginBinding binding;
    private AuthViewModel viewModel;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentLoginBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        viewModel = new ViewModelProvider(requireActivity()).get(AuthViewModel.class);

        // The server address is NOT a debug-only concern. The backend is
        // self-hosted and its address is whatever the operator is running
        // today — a LAN IP, or a tunnel URL that rotates on every restart.
        // Gating this on BuildConfig.DEBUG made release builds permanently
        // unusable: no chip, no long-press, and therefore no way to reach any
        // server other than the one hardcoded at build time.
        binding.loginServerChip.setVisibility(View.VISIBLE);
        refreshServerChip();
        // F36: onResume() does not fire when a dialog is dismissed, so the
        // chip kept showing the old server after Apply. Listen instead.
        getParentFragmentManager().setFragmentResultListener(
                EnvironmentSheet.RESULT_APPLIED, getViewLifecycleOwner(),
                (key, bundle) -> refreshServerChip());
        binding.loginServerChip.setOnClickListener(v ->
                EnvironmentSheet.show(getParentFragmentManager()));
        binding.loginLogo.setOnLongClickListener(v -> {
            EnvironmentSheet.show(getParentFragmentManager());
            return true;
        });

        binding.signInButton.setOnClickListener(v -> submit());
        binding.passwordInput.setOnEditorActionListener((tv, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                submit();
                return true;
            }
            return false;
        });

        binding.noAccountLink.setOnClickListener(v -> showNoAccountSheet());

        viewModel.loginState().observe(getViewLifecycleOwner(), result -> {
            if (result == null) return;
            boolean loading = result.isLoading();
            binding.loginProgress.setVisibility(loading ? View.VISIBLE : View.GONE);
            binding.signInButton.setEnabled(!loading);
            if (result.isError() && result.error != null) {
                binding.loginError.setText(result.error.message);
                binding.loginError.setVisibility(View.VISIBLE);
            } else {
                binding.loginError.setVisibility(View.GONE);
            }
            if (result.isSuccess() && result.data != null) {
                ((AuthActivity) requireActivity()).onLoginSuccess(result.data);
            }
        });
    }

    private void refreshServerChip() {
        binding.loginServerChip.setText(getString(
                R.string.login_server_chip,
                SplashFragment.shortHost(environmentStore.getBaseUrl())));
    }

    @Override
    public void onResume() {
        super.onResume();
        refreshServerChip();
    }

    private void submit() {
        String email = text(binding.emailInput.getText());
        String password = text(binding.passwordInput.getText());
        if (email.isEmpty()) {
            binding.emailLayout.setError(getString(R.string.hint_email));
            return;
        }
        binding.emailLayout.setError(null);
        if (password.isEmpty()) {
            binding.passwordLayout.setError(getString(R.string.hint_password));
            return;
        }
        binding.passwordLayout.setError(null);
        viewModel.login(email, password);
    }

    private void showNoAccountSheet() {
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.no_account_title)
                .setMessage(R.string.no_account_body)
                .setPositiveButton(R.string.no_account_copy_template, (d, w) -> {
                    ClipboardManager cm = (ClipboardManager)
                            requireContext().getSystemService(Context.CLIPBOARD_SERVICE);
                    String template = getString(R.string.no_account_template)
                            + text(binding.emailInput.getText());
                    cm.setPrimaryClip(ClipData.newPlainText("account request", template));
                    Toast.makeText(requireContext(), R.string.copied, Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private static String text(@Nullable CharSequence cs) {
        return cs == null ? "" : cs.toString().trim();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
