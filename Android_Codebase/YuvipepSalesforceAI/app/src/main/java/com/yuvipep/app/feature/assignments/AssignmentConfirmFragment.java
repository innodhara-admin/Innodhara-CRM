package com.yuvipep.app.feature.assignments;

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
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.OrgUserDto;
import com.yuvipep.app.core.net.dto.ProposedAssignmentDto;
import com.yuvipep.app.databinding.FragmentAssignmentsBinding;
import com.yuvipep.app.databinding.ItemAssignmentBinding;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Confirm-assignments batch (03 §8): per-task AI reason, tap-to-override
 * (staff-directory roles only — others get an honest explanation), one
 * confirm for the whole batch.
 */
@AndroidEntryPoint
public class AssignmentConfirmFragment extends Fragment {

    private FragmentAssignmentsBinding binding;
    private AssignmentsViewModel viewModel;
    private final Adapter adapter = new Adapter();

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentAssignmentsBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        viewModel = new ViewModelProvider(this).get(AssignmentsViewModel.class);

        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.assignmentList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.assignmentList.setAdapter(adapter);
        binding.confirmButton.setOnClickListener(v -> viewModel.confirmAll());

        viewModel.assignments().observe(getViewLifecycleOwner(), result -> {
            if (result == null) return;
            if (result.isLoading()) {
                binding.stateView.showLoading();
                binding.confirmButton.setVisibility(View.GONE);
            } else if (result.isSuccess() && result.data != null) {
                adapter.submit(result.data);
                if (result.data.isEmpty()) {
                    binding.stateView.showEmpty(
                            getString(R.string.assignments_empty_title),
                            getString(R.string.assignments_empty_body),
                            R.drawable.ic_tab_tasks, null, null);
                    binding.confirmButton.setVisibility(View.GONE);
                } else {
                    binding.stateView.hide();
                    binding.confirmButton.setText(getString(
                            R.string.action_confirm_batch, result.data.size()));
                    binding.confirmButton.setVisibility(View.VISIBLE);
                }
            } else if (result.isError() && result.error != null) {
                binding.stateView.showError(result.error.message, viewModel::load);
                binding.confirmButton.setVisibility(View.GONE);
            }
        });
        viewModel.staff().observe(getViewLifecycleOwner(),
                staff -> adapter.notifyDataSetChanged());
        viewModel.overrides().observe(getViewLifecycleOwner(),
                overrides -> adapter.notifyDataSetChanged());
        viewModel.confirmEvent().observe(getViewLifecycleOwner(), result -> {
            if (result == null || result.isLoading()) return;
            if (result.isSuccess() && result.data != null) {
                Toast.makeText(requireContext(), getString(
                                R.string.assignments_confirmed_toast, result.data.confirmed),
                        Toast.LENGTH_SHORT).show();
                requireActivity().getOnBackPressedDispatcher().onBackPressed();
            } else if (result.isError() && result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
            }
        });

        viewModel.load();
    }

    private void pickOverride(@NonNull ProposedAssignmentDto assignment) {
        List<OrgUserDto> staff = viewModel.staff().getValue();
        if (staff == null || staff.isEmpty()) {
            new MaterialAlertDialogBuilder(requireContext())
                    .setTitle(R.string.assignment_override)
                    .setMessage(R.string.assignment_override_unavailable)
                    .setPositiveButton(android.R.string.ok, null)
                    .show();
            return;
        }
        List<OrgUserDto> active = new ArrayList<>();
        List<String> labels = new ArrayList<>();
        for (OrgUserDto user : staff) {
            if (!user.isActive) continue;
            active.add(user);
            labels.add(user.name + " (" + user.role.replace('_', ' ') + ")");
        }
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.assignment_override)
                .setItems(labels.toArray(new String[0]), (d, which) ->
                        viewModel.setOverride(assignment.id, active.get(which)))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private class Adapter extends RecyclerView.Adapter<Adapter.Holder> {
        private final List<ProposedAssignmentDto> items = new ArrayList<>();

        void submit(List<ProposedAssignmentDto> rows) {
            items.clear();
            items.addAll(rows);
            notifyDataSetChanged();
        }

        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemAssignmentBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(items.get(position));
        }

        @Override
        public int getItemCount() {
            return items.size();
        }

        class Holder extends RecyclerView.ViewHolder {
            private final ItemAssignmentBinding row;

            Holder(ItemAssignmentBinding row) {
                super(row.getRoot());
                this.row = row;
            }

            void bind(ProposedAssignmentDto assignment) {
                row.taskTitle.setText(assignment.taskTitle != null
                        ? assignment.taskTitle : assignment.actionItemId);
                if (assignment.phase != null && !assignment.phase.isEmpty()) {
                    row.phaseChip.setText(assignment.phase.replace('_', ' '));
                    row.phaseChip.setVisibility(View.VISIBLE);
                } else {
                    row.phaseChip.setVisibility(View.GONE);
                }
                row.reasonText.setText(assignment.reason);
                Map<String, OrgUserDto> overrides = viewModel.overrides().getValue();
                OrgUserDto override = overrides != null
                        ? overrides.get(assignment.id) : null;
                if (override != null) {
                    row.overrideText.setText(getString(
                            R.string.assignment_overridden_to, override.name));
                    row.overrideText.setVisibility(View.VISIBLE);
                } else {
                    row.overrideText.setVisibility(View.GONE);
                }
                row.overrideButton.setOnClickListener(v -> pickOverride(assignment));
            }
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
