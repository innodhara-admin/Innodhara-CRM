package com.yuvipep.app.feature.home;

import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.databinding.FragmentRoleHomeBinding;
import com.yuvipep.app.feature.auth.AuthActivity;
import com.yuvipep.app.feature.auth.AuthRepository;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Phase 0 role home: greeting + honest "what's coming" + sign out. The
 * Morning Briefing replaces this in Phase 1.
 */
@AndroidEntryPoint
public class RoleHomeFragment extends Fragment {

    @Inject TokenStore tokenStore;
    @Inject AuthRepository authRepository;

    private FragmentRoleHomeBinding binding;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentRoleHomeBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        String name = tokenStore.getName() != null ? tokenStore.getName() : "";
        String role = tokenStore.getRole();
        String orgName = tokenStore.getOrgName();

        binding.homeGreeting.setText(getString(R.string.home_greeting, firstName(name)));
        StringBuilder subtitle = new StringBuilder(roleLabel(role));
        if (orgName != null && !orgName.isEmpty()) {
            subtitle.append(" · ").append(orgName);
        }
        binding.homeSubtitle.setText(subtitle.toString());

        binding.homeCardTitle.setText(R.string.home_foundation_ready);
        binding.homeCardBody.setText(comingCopy(role));

        binding.logoutButton.setOnClickListener(v -> confirmLogout());
    }

    private void confirmLogout() {
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.logout_confirm_title)
                .setMessage(R.string.logout_confirm_body)
                .setPositiveButton(R.string.action_logout, (d, w) ->
                        authRepository.logout(() -> {
                            Intent intent = new Intent(requireContext(), AuthActivity.class);
                            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                                    | Intent.FLAG_ACTIVITY_CLEAR_TASK);
                            startActivity(intent);
                        }))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private static String firstName(@NonNull String name) {
        int space = name.indexOf(' ');
        return space > 0 ? name.substring(0, space) : name;
    }

    static String roleLabel(@Nullable String role) {
        if (role == null) return "Member";
        switch (role) {
            case RoleGate.SUPER_ADMIN: return "Platform Super Admin";
            case RoleGate.ORG_ADMIN: return "Org Admin";
            case RoleGate.SALES_AGENT: return "Sales Agent";
            case RoleGate.SALES_LEAD: return "Sales Lead";
            case RoleGate.OPERATIONS_AGENT: return "Operations Agent";
            case RoleGate.OPERATIONS_LEAD: return "Operations Lead";
            case RoleGate.RELATIONSHIP_MANAGER: return "Relationship Manager";
            default:
                // Unknown roles render verbatim — generic, never a crash.
                return role.replace('_', ' ');
        }
    }

    private String comingCopy(@Nullable String role) {
        if (RoleGate.SUPER_ADMIN.equals(role)) {
            return "The platform console (organisations, stats) ships in "
                    + "Phase 7 as its own build.\n\n"
                    + getString(R.string.platform_note);
        }
        return "You're signed in and your session is secure on this device."
                + "\n\nNext up in the build plan:"
                + "\n• Phase 1 — morning briefing, notifications and the "
                + "approvals inbox"
                + "\n• Phase 2 — leads, business-card scan and meeting "
                + "recording"
                + "\n• Phase 3 — the Jarvis assistant";
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
