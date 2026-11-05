package com.yuvipep.app.feature.demos;

import android.content.Context;
import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.databinding.ItemDayCellBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import java.time.LocalDate;
import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * A reusable month calendar shown as a dialog: per-day dots on days that have
 * tasks due, tap a day to select it, long-press a day to see that day's tasks,
 * OK to return the chosen date (yyyy-MM-dd). Used by Book Demo as its date
 * picker — the same behaviour the Demos calendar screen carries inline. A plain
 * DatePickerDialog can render neither dots nor a per-day long-press, which is
 * why this exists.
 */
public final class CalendarPickerDialog {

    public interface OnPicked {
        void onPicked(@NonNull String isoDate);
    }

    private CalendarPickerDialog() {
    }

    /** Group tasks by their due day (yyyy-MM-dd). Shared with the Demos
     * calendar screen so both render the same task dots. */
    @NonNull
    public static Map<String, List<TaskDto>> indexByDate(@Nullable List<TaskDto> tasks) {
        Map<String, List<TaskDto>> byDate = new HashMap<>();
        if (tasks == null) return byDate;
        for (TaskDto task : tasks) {
            if (task == null || task.dueDate == null || task.dueDate.length() < 10) continue;
            String key = task.dueDate.substring(0, 10);
            List<TaskDto> list = byDate.get(key);
            if (list == null) {
                list = new ArrayList<>();
                byDate.put(key, list);
            }
            list.add(task);
        }
        return byDate;
    }

    /** Multi-line summary of a day's tasks for the long-press dialog. */
    @NonNull
    public static CharSequence describeTasks(@NonNull List<TaskDto> tasks) {
        StringBuilder sb = new StringBuilder();
        for (TaskDto task : tasks) {
            if (sb.length() > 0) sb.append('\n');
            sb.append("• ").append(task.title);
            String meta = "";
            if (task.projectName != null) meta = task.projectName;
            else if (task.leadName != null) meta = task.leadName;
            if (task.status != null && !task.status.isEmpty()) {
                String status = LeadStates.label(task.status);
                meta = meta.isEmpty() ? status : meta + " · " + status;
            }
            if (!meta.isEmpty()) sb.append("\n   ").append(meta);
        }
        return sb.toString();
    }

    public static void show(@NonNull Context context, @Nullable String initialIso,
                            @Nullable List<TaskDto> tasks, @NonNull OnPicked callback) {
        float density = context.getResources().getDisplayMetrics().density;
        Map<String, List<TaskDto>> tasksByDate = indexByDate(tasks);

        LocalDate initial;
        try {
            initial = (initialIso == null || initialIso.length() < 10)
                    ? LocalDate.now() : LocalDate.parse(initialIso.substring(0, 10));
        } catch (Exception ignored) {
            initial = LocalDate.now();
        }
        final LocalDate[] selected = {initial};
        final YearMonth[] month = {YearMonth.from(initial)};

        LinearLayout root = new LinearLayout(context);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (12 * density);
        root.setPadding(pad, pad, pad, 0);

        // Header: ‹  Month Year  ›
        LinearLayout header = new LinearLayout(context);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        Button prev = new Button(context, null, android.R.attr.borderlessButtonStyle);
        prev.setText("‹");
        Button next = new Button(context, null, android.R.attr.borderlessButtonStyle);
        next.setText("›");
        TextView title = new TextView(context);
        title.setGravity(Gravity.CENTER);
        title.setTextAppearance(
                com.google.android.material.R.style.TextAppearance_Material3_TitleMedium);
        title.setLayoutParams(new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        header.addView(prev);
        header.addView(title);
        header.addView(next);
        root.addView(header);

        // Weekday labels, Monday first (matches the Demos calendar).
        LinearLayout weekRow = new LinearLayout(context);
        weekRow.setOrientation(LinearLayout.HORIZONTAL);
        for (String d : new String[]{"M", "T", "W", "T", "F", "S", "S"}) {
            TextView label = new TextView(context);
            label.setText(d);
            label.setGravity(Gravity.CENTER);
            label.setTextAppearance(
                    com.google.android.material.R.style.TextAppearance_Material3_LabelSmall);
            label.setLayoutParams(new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            weekRow.addView(label);
        }
        root.addView(weekRow);

        RecyclerView grid = new RecyclerView(context);
        grid.setLayoutManager(new GridLayoutManager(context, 7));
        grid.setNestedScrollingEnabled(false);
        grid.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, (int) (310 * density)));
        root.addView(grid);

        GridAdapter adapter = new GridAdapter(context, tasksByDate, selected, month);
        grid.setAdapter(adapter);

        Runnable refresh = () -> {
            title.setText(month[0].format(
                    DateTimeFormatter.ofPattern("MMMM yyyy", Locale.ENGLISH)));
            adapter.rebuild();
        };
        prev.setOnClickListener(v -> {
            month[0] = month[0].minusMonths(1);
            refresh.run();
        });
        next.setOnClickListener(v -> {
            month[0] = month[0].plusMonths(1);
            refresh.run();
        });
        refresh.run();

        new MaterialAlertDialogBuilder(context)
                .setTitle(R.string.demos_pick_date_title)
                .setView(root)
                .setPositiveButton(android.R.string.ok, (d, w) ->
                        callback.onPicked(selected[0].toString()))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private static final class GridAdapter extends RecyclerView.Adapter<GridAdapter.Cell> {
        private final Context context;
        private final Map<String, List<TaskDto>> tasksByDate;
        private final LocalDate[] selected;
        private final YearMonth[] month;
        private final List<LocalDate> cells = new ArrayList<>();

        GridAdapter(Context context, Map<String, List<TaskDto>> tasksByDate,
                    LocalDate[] selected, YearMonth[] month) {
            this.context = context;
            this.tasksByDate = tasksByDate;
            this.selected = selected;
            this.month = month;
            rebuild();
        }

        void rebuild() {
            cells.clear();
            int lead = month[0].atDay(1).getDayOfWeek().getValue() - 1; // Monday-first blanks
            for (int i = 0; i < lead; i++) cells.add(null);
            for (int day = 1; day <= month[0].lengthOfMonth(); day++) {
                cells.add(month[0].atDay(day));
            }
            notifyDataSetChanged();
        }

        @NonNull
        @Override
        public Cell onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Cell(ItemDayCellBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Cell holder, int position) {
            holder.bind(cells.get(position));
        }

        @Override
        public int getItemCount() {
            return cells.size();
        }

        final class Cell extends RecyclerView.ViewHolder {
            private final ItemDayCellBinding cell;

            Cell(@NonNull ItemDayCellBinding cell) {
                super(cell.getRoot());
                this.cell = cell;
            }

            void bind(@Nullable LocalDate day) {
                if (day == null) {
                    cell.dayNumber.setText("");
                    cell.dayDots.setText("");
                    cell.dayNumber.setBackgroundResource(0);
                    cell.getRoot().setOnClickListener(null);
                    cell.getRoot().setOnLongClickListener(null);
                    cell.getRoot().setClickable(false);
                    cell.getRoot().setLongClickable(false);
                    return;
                }
                cell.dayNumber.setText(String.valueOf(day.getDayOfMonth()));
                List<TaskDto> dayTasks = tasksByDate.get(day.toString());
                int count = dayTasks == null ? 0 : dayTasks.size();
                StringBuilder dots = new StringBuilder();
                for (int i = 0; i < Math.min(count, 3); i++) dots.append('•');
                if (count > 3) dots.append('+');
                cell.dayDots.setText(dots.toString());
                cell.dayNumber.setBackgroundResource(day.equals(selected[0])
                        ? R.drawable.bg_day_selected : 0);
                cell.getRoot().setClickable(true);
                cell.getRoot().setOnClickListener(v -> {
                    selected[0] = day;
                    notifyDataSetChanged();
                });
                cell.getRoot().setLongClickable(true);
                cell.getRoot().setOnLongClickListener(v -> {
                    List<TaskDto> t = tasksByDate.get(day.toString());
                    if (t == null || t.isEmpty()) {
                        new MaterialAlertDialogBuilder(context)
                                .setMessage(context.getString(
                                        R.string.demos_day_no_tasks, day.toString()))
                                .setPositiveButton(android.R.string.ok, null)
                                .show();
                    } else {
                        new MaterialAlertDialogBuilder(context)
                                .setTitle(context.getString(
                                        R.string.demos_day_tasks_title, day.toString()))
                                .setMessage(describeTasks(t))
                                .setPositiveButton(android.R.string.ok, null)
                                .show();
                    }
                    return true;
                });
            }
        }
    }
}
