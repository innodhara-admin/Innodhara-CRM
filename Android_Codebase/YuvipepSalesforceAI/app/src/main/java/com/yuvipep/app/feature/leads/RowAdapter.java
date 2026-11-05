package com.yuvipep.app.feature.leads;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.recyclerview.widget.RecyclerView;

import com.yuvipep.app.databinding.ItemLeadRowBinding;

import java.util.ArrayList;
import java.util.List;

/**
 * One generic card row (title / body / meta / amber badge / tap) — every
 * lead-detail tab renders through it, so a new backend field is one line of
 * mapping, not a new layout.
 */
public class RowAdapter extends RecyclerView.Adapter<RowAdapter.Holder> {

    /** One rendered row. */
    public static class Row {
        public final String title;
        @Nullable public final String body;
        @Nullable public final String meta;
        @Nullable public final String badge;
        @Nullable public final Runnable onClick;

        public Row(@NonNull String title, @Nullable String body,
                   @Nullable String meta, @Nullable String badge,
                   @Nullable Runnable onClick) {
            this.title = title;
            this.body = body;
            this.meta = meta;
            this.badge = badge;
            this.onClick = onClick;
        }
    }

    private final List<Row> rows = new ArrayList<>();

    public void submit(@NonNull List<Row> fresh) {
        rows.clear();
        rows.addAll(fresh);
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        return new Holder(ItemLeadRowBinding.inflate(
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

    static class Holder extends RecyclerView.ViewHolder {
        private final ItemLeadRowBinding row;

        Holder(ItemLeadRowBinding row) {
            super(row.getRoot());
            this.row = row;
        }

        void bind(Row item) {
            row.rowTitle.setText(item.title);
            bindOptional(row.rowBody, item.body);
            bindOptional(row.rowMeta, item.meta);
            bindOptional(row.rowBadge, item.badge);
            row.getRoot().setOnClickListener(
                    item.onClick == null ? null : v -> item.onClick.run());
            row.getRoot().setClickable(item.onClick != null);
        }

        private static void bindOptional(@NonNull android.widget.TextView view,
                                         @Nullable String value) {
            if (value == null || value.isEmpty()) {
                view.setVisibility(View.GONE);
            } else {
                view.setText(value);
                view.setVisibility(View.VISIBLE);
            }
        }
    }
}
