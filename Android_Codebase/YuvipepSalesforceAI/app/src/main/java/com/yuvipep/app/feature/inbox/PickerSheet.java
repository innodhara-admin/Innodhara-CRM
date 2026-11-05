package com.yuvipep.app.feature.inbox;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import com.yuvipep.app.databinding.ItemPickerBinding;
import com.yuvipep.app.databinding.SheetPickerBinding;

import java.util.ArrayList;
import java.util.List;

/**
 * One reusable "pick one of these" sheet — leads, contacts, projects, intents,
 * channels. The rows are supplied by the caller, so a vocabulary the backend
 * grows tomorrow needs no new screen.
 */
public class PickerSheet extends BottomSheetDialogFragment {

    /** One choice: an id to send back, and what the human reads. */
    public static class Option {
        public final String id;
        public final String label;
        @Nullable public final String sublabel;

        public Option(@NonNull String id, @NonNull String label,
                      @Nullable String sublabel) {
            this.id = id;
            this.label = label;
            this.sublabel = sublabel;
        }
    }

    public interface Listener {
        void onPicked(@NonNull Option option);
    }

    /** Rows are handed over directly rather than through arguments — this
     * sheet is always opened from a live screen that already has them. */
    public static void open(@NonNull FragmentManager fm, @NonNull String title,
                            @Nullable String hint, @NonNull List<Option> options,
                            @NonNull Listener listener) {
        PickerSheet sheet = new PickerSheet();
        sheet.title = title;
        sheet.hint = hint;
        sheet.options.addAll(options);
        sheet.listener = listener;
        sheet.show(fm, "picker");
    }

    private SheetPickerBinding binding;
    private final List<Option> options = new ArrayList<>();
    private String title = "";
    @Nullable private String hint;
    @Nullable private Listener listener;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetPickerBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        // A rotation drops the listener the caller handed over; rather than
        // showing a sheet whose taps do nothing, close it.
        if (listener == null) {
            dismissAllowingStateLoss();
            return;
        }
        binding.pickerTitle.setText(title);
        if (hint != null && !hint.isEmpty()) {
            binding.pickerHint.setText(hint);
            binding.pickerHint.setVisibility(View.VISIBLE);
        }
        binding.pickerList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.pickerList.setAdapter(new Adapter());
        binding.stateView.hide();
    }

    private class Adapter extends RecyclerView.Adapter<Adapter.Holder> {
        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemPickerBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(options.get(position));
        }

        @Override
        public int getItemCount() {
            return options.size();
        }

        class Holder extends RecyclerView.ViewHolder {
            private final ItemPickerBinding row;

            Holder(ItemPickerBinding row) {
                super(row.getRoot());
                this.row = row;
            }

            void bind(Option option) {
                row.pickerLabel.setText(option.label);
                if (option.sublabel != null && !option.sublabel.isEmpty()) {
                    row.pickerSublabel.setText(option.sublabel);
                    row.pickerSublabel.setVisibility(View.VISIBLE);
                } else {
                    row.pickerSublabel.setVisibility(View.GONE);
                }
                row.getRoot().setOnClickListener(v -> {
                    if (listener != null) listener.onPicked(option);
                    dismiss();
                });
            }
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
