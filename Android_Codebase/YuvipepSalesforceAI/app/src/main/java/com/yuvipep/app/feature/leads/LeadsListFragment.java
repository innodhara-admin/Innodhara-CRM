package com.yuvipep.app.feature.leads;

import android.net.Uri;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.chip.Chip;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.LeadDto;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentLeadsListBinding;
import com.yuvipep.app.databinding.ItemLeadBinding;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Type;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Leads list (03 §4): search, state chips + Mine/Important toggles,
 * state-colored dots, last-activity age. FAB opens the New-lead sheet.
 */
@AndroidEntryPoint
public class LeadsListFragment extends Fragment {

    @Inject LeadsRepository repository;
    @Inject Gson gson;

    private static final Type BULK_LEAD_LIST_TYPE =
            new TypeToken<List<BulkLeadImport.Lead>>() { }.getType();

    private FragmentLeadsListBinding binding;
    private final List<LeadDto> leads = new ArrayList<>();
    private final Adapter adapter = new Adapter();
    private ActivityResultLauncher<String[]> bulkUploadPicker;

    private String stateFilter;
    private boolean mineOnly;
    private boolean importantOnly;
    private final Runnable searchRunnable = this::load;

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        bulkUploadPicker = registerForActivityResult(
                new ActivityResultContracts.OpenDocument(), this::onBulkFilePicked);
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentLeadsListBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.leadList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.leadList.setAdapter(adapter);
        binding.swipeRefresh.setOnRefreshListener(this::load);
        binding.newLeadFab.setOnClickListener(v ->
                NewLeadSheet.show(getParentFragmentManager()));
        binding.bulkUploadFab.setOnClickListener(v -> bulkUploadPicker.launch(
                new String[]{"application/json", "text/plain"}));
        getParentFragmentManager().setFragmentResultListener(
                NewLeadSheet.RESULT_KEY, this, (key, result) -> {
                    String leadId = result.getString(NewLeadSheet.RESULT_LEAD_ID);
                    if (leadId != null) {
                        open(leadId);
                    }
                });
        buildChips();
        binding.searchInput.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int a, int b, int c) { }
            @Override public void onTextChanged(CharSequence s, int a, int b, int c) { }

            @Override
            public void afterTextChanged(Editable s) {
                binding.searchInput.removeCallbacks(searchRunnable);
                binding.searchInput.postDelayed(searchRunnable, 350);
            }
        });
    }

    @Override
    public void onResume() {
        super.onResume();
        load();
    }

    private void buildChips() {
        Chip mine = toggleChip(getString(R.string.leads_filter_mine));
        mine.setOnCheckedChangeListener((c, checked) -> {
            mineOnly = checked;
            load();
        });
        binding.filterChips.addView(mine);

        Chip important = toggleChip(getString(R.string.leads_filter_important));
        important.setOnCheckedChangeListener((c, checked) -> {
            importantOnly = checked;
            load();
        });
        binding.filterChips.addView(important);

        for (String state : LeadStates.ALL) {
            Chip chip = toggleChip(LeadStates.label(state));
            chip.setTag(state);
            chip.setOnCheckedChangeListener((c, checked) -> {
                if (checked) {
                    stateFilter = state;
                    // State chips act single-select without a separate group.
                    for (int i = 0; i < binding.filterChips.getChildCount(); i++) {
                        View child = binding.filterChips.getChildAt(i);
                        if (child instanceof Chip && child.getTag() != null
                                && child != c) {
                            ((Chip) child).setChecked(false);
                        }
                    }
                } else if (state.equals(stateFilter)) {
                    stateFilter = null;
                }
                load();
            });
            binding.filterChips.addView(chip);
        }
    }

    private Chip toggleChip(String label) {
        Chip chip = new Chip(requireContext(), null,
                com.google.android.material.R.attr.chipStyle);
        chip.setText(label);
        chip.setCheckable(true);
        return chip;
    }

    private void load() {
        if (binding == null) return;
        if (leads.isEmpty()) binding.stateView.showLoading();
        String query = binding.searchInput.getText() == null ? null
                : binding.searchInput.getText().toString();
        repository.list(stateFilter, query, mineOnly, importantOnly, 100, 0, result -> {
            if (binding == null) return;
            binding.swipeRefresh.setRefreshing(false);
            if (result.isSuccess() && result.data != null) {
                leads.clear();
                leads.addAll(result.data);
                adapter.notifyDataSetChanged();
                if (leads.isEmpty()) {
                    binding.stateView.showEmpty(getString(R.string.leads_empty_title),
                            getString(R.string.leads_empty_body),
                            R.drawable.ic_tab_people, null, null);
                } else {
                    binding.stateView.hide();
                }
            } else if (result.isError() && result.error != null) {
                if (leads.isEmpty()) {
                    binding.stateView.showError(result.error.message, this::load);
                } else {
                    com.google.android.material.snackbar.Snackbar.make(binding.getRoot(),
                            result.error.message,
                            com.google.android.material.snackbar.Snackbar.LENGTH_LONG).show();
                }
            }
        });
    }

    private void open(@NonNull String leadId) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(LeadDetailFragment.create(leadId));
        }
    }

    private void onBulkFilePicked(@Nullable Uri uri) {
        if (uri == null || binding == null) return;
        String json;
        try (InputStream in = requireContext().getContentResolver().openInputStream(uri)) {
            if (in == null) throw new IOException("Cannot open the picked file");
            json = readAll(in);
        } catch (IOException e) {
            showBulkFileError(e.getMessage());
            return;
        }

        List<BulkLeadImport.Lead> parsed;
        try {
            parsed = gson.fromJson(json, BULK_LEAD_LIST_TYPE);
        } catch (RuntimeException e) {
            showBulkFileError(e.getMessage());
            return;
        }

        if (parsed == null || parsed.isEmpty()) {
            Toast.makeText(requireContext(), R.string.leads_bulk_upload_empty,
                    Toast.LENGTH_LONG).show();
            return;
        }

        runBulkImport(parsed);
    }

    private void showBulkFileError(@Nullable String reason) {
        Toast.makeText(requireContext(),
                getString(R.string.leads_bulk_upload_bad_file, reason == null ? "" : reason),
                Toast.LENGTH_LONG).show();
    }

    private void runBulkImport(@NonNull List<BulkLeadImport.Lead> entries) {
        binding.newLeadFab.setEnabled(false);
        binding.bulkUploadFab.setEnabled(false);
        binding.stateView.showLoading(
                getString(R.string.leads_bulk_upload_progress, 1, entries.size()));
        // Rows may name an owner, so the agent list has to be in hand before
        // the batch starts. A failed fetch does not stop the import: rows
        // without an owner still load, and rows with one fail by name.
        repository.assignableOwners(ownersResult -> {
            if (binding == null) return;
            startBulkImport(entries, ownersResult.isSuccess() && ownersResult.data != null
                    ? ownersResult.data
                    : new java.util.ArrayList<>());
        });
    }

    private void startBulkImport(@NonNull List<BulkLeadImport.Lead> entries,
                                 @NonNull List<com.yuvipep.app.core.net.dto.OrgUserDto> owners) {
        new BulkLeadImporter(repository, entries, owners, new BulkLeadImporter.Listener() {
            @Override
            public void onProgress(int done, int total) {
                if (binding == null) return;
                binding.stateView.showLoading(
                        getString(R.string.leads_bulk_upload_progress, done + 1, total));
            }

            @Override
            public void onFinished(@NonNull BulkLeadImporter.Outcome outcome) {
                if (binding == null) return;
                binding.newLeadFab.setEnabled(true);
                binding.bulkUploadFab.setEnabled(true);
                showBulkResult(outcome, entries.size());
                load();
            }
        }).start();
    }

    private void showBulkResult(@NonNull BulkLeadImporter.Outcome outcome, int total) {
        StringBuilder message = new StringBuilder(getString(
                R.string.leads_bulk_upload_done_summary, outcome.created, total));
        if (!outcome.failures.isEmpty()) {
            message.append("\n\n")
                    .append(getString(R.string.leads_bulk_upload_failures_title))
                    .append(":");
            for (BulkLeadImporter.Failure failure : outcome.failures) {
                message.append("\n").append(getString(
                        R.string.leads_bulk_upload_failure_row, failure.label, failure.reason));
            }
        }
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.leads_bulk_upload_done_title)
                .setMessage(message.toString())
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    @NonNull
    private static String readAll(@NonNull InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[8 * 1024];
        int read;
        while ((read = in.read(buffer)) != -1) {
            out.write(buffer, 0, read);
        }
        return out.toString(StandardCharsets.UTF_8.name());
    }

    private class Adapter extends RecyclerView.Adapter<Adapter.Holder> {
        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemLeadBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(leads.get(position));
        }

        @Override
        public int getItemCount() {
            return leads.size();
        }

        class Holder extends RecyclerView.ViewHolder {
            private final ItemLeadBinding row;

            Holder(ItemLeadBinding row) {
                super(row.getRoot());
                this.row = row;
            }

            void bind(LeadDto lead) {
                row.leadName.setText(lead.name);
                row.importantStar.setVisibility(lead.isImportant
                        ? View.VISIBLE : View.GONE);
                row.stateDot.setBackgroundTintList(
                        ContextCompat.getColorStateList(requireContext(),
                                LeadStates.color(lead.state)));
                StringBuilder meta = new StringBuilder(LeadStates.label(lead.state));
                if (lead.city != null && !lead.city.isEmpty()) {
                    meta.append(" · ").append(lead.city);
                }
                if (lead.lastActivityAt != null) {
                    meta.append(" · ").append(
                            Times.ago(Times.parseUtc(lead.lastActivityAt)));
                }
                row.leadMeta.setText(meta);
                row.getRoot().setOnClickListener(v -> open(lead.id));
            }
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
