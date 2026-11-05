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
import com.yuvipep.app.core.net.dto.LeadRequests;
import com.yuvipep.app.core.net.dto.OrgUserDto;
import com.yuvipep.app.databinding.SheetNewLeadBinding;

import android.widget.ArrayAdapter;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * New lead by form (03 §4). Voice creation arrives with the assistant in
 * Phase 3 — this is the tap path. Publishes the created id as a fragment
 * result so the list can open the detail straight away.
 */
@AndroidEntryPoint
public class NewLeadSheet extends BottomSheetDialogFragment {

    public static final String RESULT_KEY = "new_lead";
    public static final String RESULT_LEAD_ID = "lead_id";

    public static void show(@NonNull FragmentManager fm) {
        new NewLeadSheet().show(fm, "new_lead");
    }

    @Inject LeadsRepository repository;

    private SheetNewLeadBinding binding;
    /** Parallel to the dropdown's rows; index 0 is "assign to me". */
    private final List<String> ownerIds = new ArrayList<>();
    @Nullable private String selectedOwnerId;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetNewLeadBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.createButton.setOnClickListener(v -> create());
        loadOwners();
    }

    /**
     * Fill the owner dropdown with the org's sales agents.
     *
     * The first row is always "assign to me", which is also the state the
     * field starts in: the backend has always defaulted an ownerless lead to
     * its creator, and a sales lead creating a lead for themselves should not
     * have to pick their own name. A failure here is not fatal for the same
     * reason — the lead is simply created the way it always was.
     */
    private void loadOwners() {
        ownerIds.clear();
        ownerIds.add(null);                       // row 0 = me
        List<String> labels = new ArrayList<>();
        labels.add(getString(R.string.lead_owner_unassigned));
        binding.ownerInput.setText(labels.get(0), false);

        repository.assignableOwners(result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                for (OrgUserDto user : result.data) {
                    ownerIds.add(user.id);
                    labels.add(user.name == null || user.name.isEmpty()
                            ? user.email : user.name);
                }
            } else {
                binding.ownerLayout.setHelperText(
                        getString(R.string.lead_owner_load_failed));
            }
            binding.ownerInput.setAdapter(new ArrayAdapter<>(requireContext(),
                    android.R.layout.simple_list_item_1, labels));
            binding.ownerInput.setOnItemClickListener((parent, v, position, id) ->
                    selectedOwnerId = position >= 0 && position < ownerIds.size()
                            ? ownerIds.get(position) : null);
        });
    }

    private void create() {
        String name = text(binding.nameInput.getText());
        if (name.length() < 2) {
            Toast.makeText(requireContext(), R.string.lead_name_required,
                    Toast.LENGTH_SHORT).show();
            return;
        }
        binding.createButton.setEnabled(false);
        LeadRequests.Create body = new LeadRequests.Create();
        body.name = name;
        body.city = nullable(text(binding.cityInput.getText()));
        body.source = nullable(text(binding.sourceInput.getText()));
        body.website = nullable(text(binding.websiteInput.getText()));
        body.notes = nullable(text(binding.notesInput.getText()));
        body.ownerId = selectedOwnerId;   // null = the backend's own fallback
        repository.create(body, result -> {
            if (binding == null) return;
            binding.createButton.setEnabled(true);
            if (result.isSuccess() && result.data != null) {
                Bundle out = new Bundle();
                out.putString(RESULT_LEAD_ID, result.data.id);
                getParentFragmentManager().setFragmentResult(RESULT_KEY, out);
                dismiss();
            } else if (result.isError() && result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
            }
        });
    }

    private static String text(@Nullable CharSequence value) {
        return value == null ? "" : value.toString().trim();
    }

    @Nullable
    private static String nullable(@NonNull String value) {
        return value.isEmpty() ? null : value;
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
