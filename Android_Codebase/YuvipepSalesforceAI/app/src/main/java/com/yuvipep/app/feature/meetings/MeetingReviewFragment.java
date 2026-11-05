package com.yuvipep.app.feature.meetings;

import android.os.Bundle;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.MeetingReviewResponse;
import com.yuvipep.app.core.net.dto.ReviewConfirmRequest;
import com.yuvipep.app.databinding.FragmentMeetingReviewBinding;
import com.yuvipep.app.databinding.ItemReviewBinding;
import com.yuvipep.app.feature.home.WorkflowRepository;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The human review gate for extracted action items (03 §5): keep/drop with
 * a switch, tap to edit title/description, one confirm — nothing goes live
 * until a person says so. (Full editor with assignees/dues lands with the
 * Phase 2 recorder; this makes the Phase 1 feed act on it end-to-end.)
 */
@AndroidEntryPoint
public class MeetingReviewFragment extends Fragment {

    private static final String ARG_MEETING = "meeting_id";

    public static MeetingReviewFragment create(@NonNull String meetingId) {
        MeetingReviewFragment fragment = new MeetingReviewFragment();
        Bundle args = new Bundle();
        args.putString(ARG_MEETING, meetingId);
        fragment.setArguments(args);
        return fragment;
    }

    /** Mutable local copy of one extracted item. */
    private static class Row {
        String id;
        String title;
        String description;
        boolean keep = true;
        String duplicateWarning;   // F24: set when this item looks like an existing task
    }

    @Inject WorkflowRepository repository;

    private FragmentMeetingReviewBinding binding;
    private final List<Row> rows = new ArrayList<>();
    private final Adapter adapter = new Adapter();
    private String meetingId;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentMeetingReviewBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        meetingId = requireArguments().getString(ARG_MEETING, "");
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.reviewList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.reviewList.setAdapter(adapter);
        binding.confirmButton.setOnClickListener(v -> confirm());
        binding.addItemButton.setOnClickListener(v -> addItem());
        load();
    }

    private void load() {
        binding.stateView.showLoading();
        repository.meetingReview(meetingId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                rows.clear();
                if (result.data.items != null) {
                    for (MeetingReviewResponse.Item item : result.data.items) {
                        Row row = new Row();
                        row.id = item.id;
                        row.title = item.title;
                        row.description = item.description;
                        MeetingReviewResponse.Duplicate dup = item.possibleDuplicateOf;
                        if (dup != null && dup.title != null) {
                            String when = dup.at == null || dup.at.isEmpty()
                                    ? "" : " (" + dup.at + ")";
                            row.duplicateWarning = getString(
                                    R.string.review_possible_duplicate, dup.title, when);
                        }
                        rows.add(row);
                    }
                }
                adapter.notifyDataSetChanged();
                if (rows.isEmpty()) {
                    binding.stateView.showEmpty(getString(R.string.review_empty_title),
                            getString(R.string.review_empty_body),
                            R.drawable.ic_tab_tasks, null, null);
                    binding.confirmButton.setVisibility(View.GONE);
                    // A meeting still pending review can gain user-added items
                    // even when extraction found none.
                    binding.addItemButton.setVisibility(
                            "review_pending".equals(result.data.meetingStatus)
                                    ? View.VISIBLE : View.GONE);
                } else {
                    binding.stateView.hide();
                    updateConfirmLabel();
                    binding.confirmButton.setVisibility(View.VISIBLE);
                    binding.addItemButton.setVisibility(View.VISIBLE);
                }
            } else if (result.isError() && result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
                binding.confirmButton.setVisibility(View.GONE);
                binding.addItemButton.setVisibility(View.GONE);
            }
        });
    }

    private void updateConfirmLabel() {
        int kept = 0;
        for (Row row : rows) {
            if (row.keep) kept++;
        }
        binding.confirmButton.setText(getString(R.string.review_confirm, kept));
    }

    private void confirm() {
        List<ReviewConfirmRequest.Item> items = new ArrayList<>();
        for (Row row : rows) {
            items.add(new ReviewConfirmRequest.Item(
                    row.id, row.title, row.description, row.keep));
        }
        repository.confirmMeetingReview(meetingId, new ReviewConfirmRequest(items),
                result -> {
                    if (binding == null) return;
                    if (result.isSuccess() && result.data != null) {
                        // Confirming is also what starts the Planner, so say
                        // so — a silent "N tasks are live" would hide a
                        // project and a plan being built behind it.
                        Toast.makeText(requireContext(), getString(
                                        result.data.planning
                                                ? R.string.review_confirmed_planning_toast
                                                : R.string.review_confirmed_toast,
                                        result.data.actionItemsSaved),
                                result.data.planning
                                        ? Toast.LENGTH_LONG : Toast.LENGTH_SHORT).show();
                        requireActivity().getOnBackPressedDispatcher().onBackPressed();
                    } else if (result.isError() && result.error != null) {
                        Toast.makeText(requireContext(), result.error.message,
                                Toast.LENGTH_LONG).show();
                    }
                });
    }

    /** User-added item (id=null → backend creates it as OPEN on confirm). */
    private void addItem() {
        Row row = new Row();
        row.title = "";
        row.keep = true;
        editInto(row, () -> {
            if (row.title != null && !row.title.isEmpty()) {
                rows.add(row);
                adapter.notifyDataSetChanged();
                binding.stateView.hide();
                updateConfirmLabel();
                binding.confirmButton.setVisibility(View.VISIBLE);
            }
        });
    }

    private void edit(@NonNull Row row) {
        editInto(row, null);
    }

    private void editInto(@NonNull Row row, @Nullable Runnable onSaved) {
        // The add-a-missed-item path passes an onSaved callback; the edit path
        // does not. They shared one dialog that always said "Edit item" (F7).
        boolean adding = onSaved != null;
        float density = getResources().getDisplayMetrics().density;
        int pad = (int) (20 * density);
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        wrapper.setPadding(pad, pad / 2, pad, 0);
        EditText titleInput = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        titleInput.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        titleInput.setHint(R.string.review_item_title_hint);
        titleInput.setText(row.title);
        EditText descInput = new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        descInput.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        descInput.setHint(R.string.meeting_item_description_hint);
        descInput.setText(row.description);
        wrapper.addView(titleInput);
        wrapper.addView(descInput);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(adding ? R.string.review_add_title : R.string.review_edit_title)
                .setView(wrapper)
                .setPositiveButton(android.R.string.ok, (d, w) -> {
                    String title = titleInput.getText().toString().trim();
                    if (!title.isEmpty()) {
                        row.title = title;
                    }
                    row.description = descInput.getText().toString().trim();
                    adapter.notifyDataSetChanged();
                    if (onSaved != null) onSaved.run();
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private class Adapter extends RecyclerView.Adapter<Adapter.Holder> {
        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemReviewBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(rows.get(position));
        }

        @Override
        public int getItemCount() {
            return rows.size();
        }

        class Holder extends RecyclerView.ViewHolder {
            private final ItemReviewBinding row;

            Holder(ItemReviewBinding row) {
                super(row.getRoot());
                this.row = row;
            }

            void bind(Row item) {
                row.itemTitle.setText(item.title);
                row.itemDescription.setText(item.description);
                row.itemDescription.setVisibility(item.description == null
                        || item.description.isEmpty() ? View.GONE : View.VISIBLE);
                boolean hasWarning = item.duplicateWarning != null;
                row.itemDuplicateWarning.setText(item.duplicateWarning);
                row.itemDuplicateWarning.setVisibility(hasWarning ? View.VISIBLE : View.GONE);
                row.itemDuplicateWarning.setAlpha(item.keep ? 1f : 0.4f);
                row.itemTitle.setAlpha(item.keep ? 1f : 0.4f);
                row.itemDescription.setAlpha(item.keep ? 1f : 0.4f);
                row.keepSwitch.setOnCheckedChangeListener(null);
                row.keepSwitch.setChecked(item.keep);
                row.keepSwitch.setOnCheckedChangeListener((btn, checked) -> {
                    item.keep = checked;
                    row.itemTitle.setAlpha(checked ? 1f : 0.4f);
                    row.itemDescription.setAlpha(checked ? 1f : 0.4f);
                    row.itemDuplicateWarning.setAlpha(checked ? 1f : 0.4f);
                    updateConfirmLabel();
                });
                row.getRoot().setOnClickListener(v -> edit(item));
            }
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
