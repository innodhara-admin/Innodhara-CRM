package com.yuvipep.app.feature.inbox;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.google.android.material.tabs.TabLayout;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.databinding.FragmentInboxBinding;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The Inbox (03 §9, 02 architecture `inbox/`): outbound messages on one side,
 * inbound triage on the other, and "Log client reply" above both.
 *
 * `GET /messages` requires the send_messages permission, so a role that cannot
 * send never sees a Messages tab it would only get a 403 from — it gets the
 * triage queue alone, with no tab strip at all (§7 rule 3: no empty screens).
 */
@AndroidEntryPoint
public class InboxFragment extends Fragment {

    private static final int TAB_MESSAGES = 0;

    @Inject TokenStore tokenStore;

    private FragmentInboxBinding binding;
    private boolean canSend;
    /** Survives a tab switch away and back, which recreates this fragment. */
    private int currentTab;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentInboxBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        canSend = RoleGate.has(tokenStore.getRole(), RoleGate.SEND_MESSAGES);

        // Only the sales agent has an Inbox tab; every other role arrives here
        // pushed on top of their own screen and needs a way back.
        boolean pushed = getParentFragmentManager().getBackStackEntryCount() > 0;
        binding.backButton.setVisibility(pushed ? View.VISIBLE : View.GONE);
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());

        binding.logReplyButton.setOnClickListener(v ->
                LogClientReplySheet.open(getChildFragmentManager()));
        // A logged reply can land straight in triage — show it immediately.
        getChildFragmentManager().setFragmentResultListener(
                LogClientReplySheet.RESULT_KEY, this,
                (key, bundle) -> showTab(currentTab));

        if (!canSend) {
            binding.inboxTabs.setVisibility(View.GONE);
            showTab(1);
            return;
        }

        binding.inboxTabs.addTab(binding.inboxTabs.newTab()
                .setText(getString(R.string.inbox_tab_messages)));
        binding.inboxTabs.addTab(binding.inboxTabs.newTab()
                .setText(getString(R.string.inbox_tab_triage)));
        binding.inboxTabs.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override
            public void onTabSelected(TabLayout.Tab tab) {
                showTab(tab.getPosition());
            }

            @Override
            public void onTabUnselected(TabLayout.Tab tab) {
            }

            @Override
            public void onTabReselected(TabLayout.Tab tab) {
            }
        });
        // Select the tab AFTER the listener is attached, so the indicator and
        // the content can never disagree (the Phase 2 wart in handoff §6).
        TabLayout.Tab tab = binding.inboxTabs.getTabAt(currentTab);
        if (tab != null) {
            tab.select();
        }
        showTab(currentTab);
    }

    private void showTab(int position) {
        currentTab = position;
        Fragment child = position == TAB_MESSAGES && canSend
                ? new MessageCenterFragment()
                : new InboundTriageFragment();
        getChildFragmentManager().beginTransaction()
                .replace(binding.inboxContent.getId(), child)
                .commitAllowingStateLoss();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
