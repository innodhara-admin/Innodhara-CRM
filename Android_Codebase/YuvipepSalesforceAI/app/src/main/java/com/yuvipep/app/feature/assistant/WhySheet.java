package com.yuvipep.app.feature.assistant;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import com.yuvipep.app.R;
import com.yuvipep.app.databinding.SheetWhyBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The Why chip's sheet (04 §2): GET /why/{type}/{id} rendered verbatim —
 * inputs, decision, reason, confidence come from the backend's decision log,
 * including the honest "No AI decision is recorded for this record."
 */
@AndroidEntryPoint
public class WhySheet extends BottomSheetDialogFragment {

    private static final String ARG_TYPE = "entity_type";
    private static final String ARG_ID = "entity_id";

    public static void open(@NonNull FragmentManager fm, @NonNull String entityType,
                            @NonNull String entityId) {
        WhySheet sheet = new WhySheet();
        Bundle args = new Bundle();
        args.putString(ARG_TYPE, entityType);
        args.putString(ARG_ID, entityId);
        sheet.setArguments(args);
        sheet.show(fm, "why");
    }

    @Inject AssistantRepository repository;

    private SheetWhyBinding binding;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetWhyBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        String type = requireArguments().getString(ARG_TYPE, "");
        String id = requireArguments().getString(ARG_ID, "");
        binding.whySubtitle.setText(getString(R.string.why_subtitle,
                LeadStates.label(type)));
        binding.whyProgress.setVisibility(View.VISIBLE);
        repository.why(type, id, result -> {
            if (binding == null) return;
            binding.whyProgress.setVisibility(View.GONE);
            if (result.isSuccess() && result.data != null) {
                binding.whyTrace.setText(result.data.trace == null
                        || result.data.trace.isEmpty()
                        ? getString(R.string.why_empty) : result.data.trace);
            } else if (result.error != null) {
                binding.whyTrace.setText(result.error.message);
            }
        });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
