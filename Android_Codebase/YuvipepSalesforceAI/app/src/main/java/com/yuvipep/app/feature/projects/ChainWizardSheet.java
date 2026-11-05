package com.yuvipep.app.feature.projects;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import com.google.android.material.chip.Chip;
import com.yuvipep.app.R;
import com.yuvipep.app.databinding.SheetChainWizardBinding;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Chain deals (03 §6 "Chain wizard", Workflow 27): name each branch, pick
 * how invoicing works, POST /projects/{id}/children — commercials stay on
 * the parent, each branch gets its own lead + delivery plan.
 */
@AndroidEntryPoint
public class ChainWizardSheet extends BottomSheetDialogFragment {

    public static final String RESULT_KEY = "chain_created";

    private static final String ARG_PROJECT = "project_id";

    public static void open(@NonNull FragmentManager fm, @NonNull String projectId) {
        ChainWizardSheet sheet = new ChainWizardSheet();
        Bundle args = new Bundle();
        args.putString(ARG_PROJECT, projectId);
        sheet.setArguments(args);
        sheet.show(fm, "chain_wizard");
    }

    @Inject ProjectsRepository repository;

    private SheetChainWizardBinding binding;
    private final List<String> branches = new ArrayList<>();

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetChainWizardBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.addBranchButton.setOnClickListener(v -> addBranch());
        binding.createButton.setOnClickListener(v -> create());
    }

    private void addBranch() {
        String name = binding.branchInput.getText() == null ? ""
                : binding.branchInput.getText().toString().trim();
        if (name.isEmpty()) return;
        branches.add(name);
        binding.branchInput.setText("");
        Chip chip = new Chip(requireContext());
        chip.setText(name);
        chip.setCloseIconVisible(true);
        chip.setOnCloseIconClickListener(v -> {
            branches.remove(name);
            binding.branchChips.removeView(chip);
        });
        binding.branchChips.addView(chip);
    }

    private void create() {
        if (branches.isEmpty()) {
            Toast.makeText(requireContext(), R.string.chain_wizard_need_one,
                    Toast.LENGTH_SHORT).show();
            return;
        }
        String mode = binding.invoicingPerBranch.isChecked() ? "per_branch" : "group";
        String projectId = requireArguments().getString(ARG_PROJECT, "");
        binding.createButton.setEnabled(false);
        repository.createChildren(projectId, branches, mode, result -> {
            if (binding == null) return;
            binding.createButton.setEnabled(true);
            if (result.isSuccess() && result.data != null) {
                Toast.makeText(requireContext(),
                        getString(R.string.chain_wizard_created, result.data.children.size()),
                        Toast.LENGTH_LONG).show();
                getParentFragmentManager().setFragmentResult(RESULT_KEY, new Bundle());
                dismiss();
            } else if (result.error != null) {
                Toast.makeText(requireContext(), result.error.message, Toast.LENGTH_LONG).show();
            }
        });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
