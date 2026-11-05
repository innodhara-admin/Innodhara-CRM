package com.yuvipep.app.feature.leads;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import com.yuvipep.app.R;
import com.yuvipep.app.databinding.SheetConsentBinding;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The DPDP consent gate before recording (08 §1): method + note →
 * POST /leads/{id}/consent, then a fragment result lets the caller proceed
 * to the recorder. Recording never starts before the backend has the row.
 */
@AndroidEntryPoint
public class ConsentSheet extends BottomSheetDialogFragment {

    public static final String RESULT_KEY = "consent_recorded";

    private static final String ARG_LEAD = "lead_id";

    public static void open(@NonNull FragmentManager fm, @NonNull String leadId) {
        ConsentSheet sheet = new ConsentSheet();
        Bundle args = new Bundle();
        args.putString(ARG_LEAD, leadId);
        sheet.setArguments(args);
        sheet.show(fm, "consent");
    }

    @Inject LeadsRepository repository;

    private SheetConsentBinding binding;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetConsentBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.confirmButton.setOnClickListener(v -> confirm());
    }

    private void confirm() {
        String method = binding.methodWritten.isChecked() ? "written"
                : binding.methodInApp.isChecked() ? "in_app" : "verbal";
        String note = binding.noteInput.getText() == null ? null
                : binding.noteInput.getText().toString().trim();
        binding.confirmButton.setEnabled(false);
        repository.recordConsent(requireArguments().getString(ARG_LEAD, ""), method,
                note == null || note.isEmpty() ? null : note, result -> {
                    if (binding == null) return;
                    binding.confirmButton.setEnabled(true);
                    if (result.isSuccess()) {
                        getParentFragmentManager().setFragmentResult(RESULT_KEY,
                                new Bundle());
                        dismiss();
                    } else if (result.error != null) {
                        Toast.makeText(requireContext(), result.error.message,
                                Toast.LENGTH_LONG).show();
                    }
                });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
