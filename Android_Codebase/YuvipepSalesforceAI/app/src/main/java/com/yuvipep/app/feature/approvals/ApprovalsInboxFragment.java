package com.yuvipep.app.feature.approvals;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.chip.Chip;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.db.CachedApproval;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.databinding.FragmentApprovalsBinding;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Approvals inbox (03 §8): entity-type filter chips, stage filter, age +
 * expiry on cards, inline Approve / Reject-with-note, tap for facts.
 */
@AndroidEntryPoint
public class ApprovalsInboxFragment extends Fragment {

    // Backend ApprovalEntityType values (constants.py §approvals).
    private static final String[] ENTITY_TYPES = {
            "outbound_message", "proposal", "price_change", "plan_change", "invoice"};
    private static final String[] ENTITY_LABELS = {
            "message", "proposal", "price change", "plan change", "invoice"};

    @Inject TokenStore tokenStore;

    private FragmentApprovalsBinding binding;
    private ApprovalsViewModel viewModel;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentApprovalsBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        viewModel = new ViewModelProvider(this).get(ApprovalsViewModel.class);

        ApprovalAdapter adapter = new ApprovalAdapter(new ApprovalAdapter.Listener() {
            @Override
            public void onApprove(@NonNull CachedApproval approval) {
                viewModel.decide(approval.id, true, null);
            }

            @Override
            public void onReject(@NonNull CachedApproval approval) {
                DecideDialogs.rejectWithNote(requireContext(), note ->
                        viewModel.decide(approval.id, false, note));
            }

            @Override
            public void onOpen(@NonNull CachedApproval approval) {
                if (getActivity() instanceof MainActivity) {
                    ((MainActivity) getActivity())
                            .push(ApprovalDetailFragment.create(approval.id));
                }
            }

            @Override
            public void onDismissFailure(@NonNull CachedApproval approval) {
                viewModel.dismissLocalFailure(approval.id);
            }
        });
        binding.approvalList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.approvalList.setAdapter(adapter);

        buildChips();

        binding.swipeRefresh.setOnRefreshListener(() -> {
            viewModel.refresh();
            binding.swipeRefresh.setRefreshing(false);
        });

        viewModel.approvals().observe(getViewLifecycleOwner(), rows -> {
            adapter.submitList(rows);
            if (rows == null || rows.isEmpty()) {
                binding.stateView.showEmpty(getString(R.string.approvals_empty_title),
                        getString(R.string.approvals_empty_body),
                        R.drawable.ic_tab_approvals, null, null);
            } else {
                binding.stateView.hide();
            }
        });
        viewModel.decideEvent().observe(getViewLifecycleOwner(), result -> {
            if (result == null) return;
            if (result.isSuccess() && result.data != null) {
                Toast.makeText(requireContext(), result.data.queuedOffline
                                ? getString(R.string.approval_queued_offline)
                                : getString(R.string.approval_decided_toast,
                                result.data.response != null
                                        ? result.data.response.status : "applied"),
                        Toast.LENGTH_SHORT).show();
            } else if (result.isError() && result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
                viewModel.refresh();
            }
        });
    }

    private void buildChips() {
        // Stage chip first: leads land on stage=decide by default (05 §3).
        Chip decideChip = newChip(getString(R.string.approval_stage_decide) + " stage");
        boolean leadDefault = RoleGate.SALES_LEAD.equals(tokenStore.getRole());
        decideChip.setChecked(leadDefault);
        viewModel.setDecideOnly(leadDefault);
        decideChip.setOnCheckedChangeListener((btn, checked) ->
                viewModel.setDecideOnly(checked));
        binding.filterChips.addView(decideChip);

        final Chip[] entityChips = new Chip[ENTITY_TYPES.length];
        for (int i = 0; i < ENTITY_TYPES.length; i++) {
            String type = ENTITY_TYPES[i];
            Chip chip = newChip(ENTITY_LABELS[i]);
            entityChips[i] = chip;
            chip.setOnCheckedChangeListener((btn, checked) -> {
                if (checked) {
                    for (Chip other : entityChips) {
                        if (other != chip) other.setChecked(false);
                    }
                    viewModel.setEntityFilter(type);
                } else if (type.equals(currentFilter)) {
                    viewModel.setEntityFilter(null);
                }
                currentFilter = checked ? type : null;
            });
            binding.filterChips.addView(chip);
        }
    }

    private String currentFilter;

    private Chip newChip(String label) {
        Chip chip = new Chip(requireContext(), null,
                com.google.android.material.R.attr.chipStyle);
        chip.setText(label);
        chip.setCheckable(true);
        return chip;
    }

    @Override
    public void onResume() {
        super.onResume();
        viewModel.refresh();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
