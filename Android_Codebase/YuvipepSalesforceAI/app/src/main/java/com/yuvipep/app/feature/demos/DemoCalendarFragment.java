package com.yuvipep.app.feature.demos;

import android.os.Bundle;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.snackbar.Snackbar;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.DemoCalendarDto;
import com.yuvipep.app.core.net.dto.DemoDto;
import com.yuvipep.app.core.net.dto.DemoRequests;
import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.core.voice.VoiceEditText;
import com.yuvipep.app.databinding.FragmentDemoCalendarBinding;
import com.yuvipep.app.databinding.ItemDayCellBinding;
import com.yuvipep.app.feature.leads.LeadStates;
import com.yuvipep.app.feature.leads.RowAdapter;
import com.yuvipep.app.feature.tasks.TasksRepository;

import java.time.LocalDate;
import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The 31-day demos calendar (03 §11): month grid with per-day demo dots and
 * free-day view, day tap → that day's demos, demo tap → status/reschedule
 * (update_demo_status roles; others get the honest explanation). Booking
 * starts from a lead screen or the assistant — a calendar day alone doesn't
 * know which client the demo is for.
 */
@AndroidEntryPoint
public class DemoCalendarFragment extends Fragment {

    @Inject DemosRepository repository;
    @Inject TasksRepository tasksRepository;
    @Inject TokenStore tokenStore;

    private FragmentDemoCalendarBinding binding;
    private RowAdapter dayAdapter;
    private DayGridAdapter gridAdapter;

    private YearMonth month = YearMonth.now();
    @Nullable private DemoCalendarDto data;
    private LocalDate selectedDay = LocalDate.now();
    /** This user's tasks bucketed by due day (yyyy-MM-dd) — drives the amber
     * task dots and the long-press "tasks due" dialog. */
    @NonNull private Map<String, List<TaskDto>> tasksByDate = new HashMap<>();

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentDemoCalendarBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.prevMonth.setOnClickListener(v -> {
            month = month.minusMonths(1);
            load();
        });
        binding.nextMonth.setOnClickListener(v -> {
            month = month.plusMonths(1);
            load();
        });

        String[] weekdays = {"M", "T", "W", "T", "F", "S", "S"};
        for (String day : weekdays) {
            TextView label = new TextView(requireContext());
            label.setText(day);
            label.setGravity(Gravity.CENTER);
            label.setTextAppearance(
                    com.google.android.material.R.style.TextAppearance_Material3_LabelSmall);
            label.setLayoutParams(new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            binding.weekdayRow.addView(label);
        }

        gridAdapter = new DayGridAdapter();
        binding.dayGrid.setLayoutManager(new GridLayoutManager(requireContext(), 7));
        binding.dayGrid.setAdapter(gridAdapter);
        binding.dayGrid.setNestedScrollingEnabled(false);

        dayAdapter = new RowAdapter();
        binding.dayList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.dayList.setAdapter(dayAdapter);

        load();
        loadTasks();
    }

    /** Fetch this user's tasks once and bucket them by due day; the grid then
     * dots those days (amber) and long-press lists them. Tasks span all months,
     * so this doesn't need to refetch as the user pages between months. */
    private void loadTasks() {
        tasksRepository.myTasks(result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                tasksByDate = CalendarPickerDialog.indexByDate(result.data.tasks);
                if (gridAdapter != null) gridAdapter.notifyDataSetChanged();
            }
        });
    }

    private void showTasksForDay(@NonNull LocalDate day) {
        List<TaskDto> dayTasks = tasksByDate.get(day.toString());
        if (dayTasks == null || dayTasks.isEmpty()) {
            new MaterialAlertDialogBuilder(requireContext())
                    .setMessage(getString(R.string.demos_day_no_tasks, day.toString()))
                    .setPositiveButton(android.R.string.ok, null)
                    .show();
            return;
        }
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(getString(R.string.demos_day_tasks_title, day.toString()))
                .setMessage(CalendarPickerDialog.describeTasks(dayTasks))
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    private void load() {
        binding.monthTitle.setText(month.format(
                DateTimeFormatter.ofPattern("MMMM yyyy", Locale.ENGLISH)));
        binding.monthMeta.setText("");
        binding.stateView.showLoading();
        repository.calendar(month.getYear(), month.getMonthValue(), null, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                data = result.data;
                binding.stateView.hide();
                binding.monthMeta.setText(getString(R.string.demos_month_meta,
                        data.totalDemos,
                        data.freeDays == null ? 0 : data.freeDays.size()));
                if (!month.equals(YearMonth.from(selectedDay))) {
                    selectedDay = month.atDay(1);
                }
                gridAdapter.rebuild();
                renderDay();
            } else if (result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    private void renderDay() {
        binding.dayTitle.setText(selectedDay.format(
                DateTimeFormatter.ofPattern("EEE d MMM", Locale.ENGLISH)));
        List<DemoDto> demos = demosOn(selectedDay);
        List<RowAdapter.Row> rows = new ArrayList<>();
        for (DemoDto demo : demos) {
            String meta = (demo.time == null || demo.time.isEmpty()
                    ? getString(R.string.demos_no_time) : demo.time)
                    + " · " + LeadStates.label(demo.status)
                    + (demo.team == null ? "" : " · " + demo.team);
            rows.add(new RowAdapter.Row(
                    demo.clientName == null ? getString(R.string.demos_title) : demo.clientName,
                    demo.notes, meta, null, () -> demoDialog(demo)));
        }
        dayAdapter.submit(rows);
        if (rows.isEmpty()) {
            binding.stateView.showEmpty(getString(R.string.demos_day_empty), null,
                    R.drawable.ic_calendar, null, null);
        } else {
            binding.stateView.hide();
        }
    }

    @NonNull
    private List<DemoDto> demosOn(@NonNull LocalDate day) {
        if (data == null || data.days == null) return Collections.emptyList();
        List<DemoDto> demos = data.days.get(day.toString());
        return demos == null ? Collections.emptyList() : demos;
    }

    // ── Demo detail: status updates + reschedule ─────────────────────

    private void demoDialog(@NonNull DemoDto demo) {
        String role = tokenStore.getRole();
        boolean canUpdate = RoleGate.has(role, RoleGate.UPDATE_DEMO_STATUS);
        StringBuilder body = new StringBuilder();
        if (demo.clientName != null) body.append(demo.clientName).append('\n');
        body.append(demo.date);
        if (demo.time != null && !demo.time.isEmpty()) body.append(" · ").append(demo.time);
        body.append('\n').append(LeadStates.label(demo.status));
        if (demo.team != null) body.append(" · ").append(demo.team);
        if (demo.notes != null && !demo.notes.isEmpty()) {
            body.append("\n\n").append(demo.notes);
        }

        MaterialAlertDialogBuilder builder = new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.demos_detail_title)
                .setMessage(body.toString())
                .setNegativeButton(android.R.string.cancel, null);
        if (canUpdate && "scheduled".equals(demo.status)) {
            builder.setPositiveButton(R.string.demos_action_reschedule,
                            (d, w) -> rescheduleDialog(demo))
                    .setNeutralButton(R.string.demos_action_update_status,
                            (d, w) -> statusDialog(demo));
        } else if (!canUpdate) {
            builder.setPositiveButton(R.string.demos_action_reschedule, (d, w) ->
                    Toast.makeText(requireContext(), R.string.demos_no_permission,
                            Toast.LENGTH_LONG).show());
        }
        builder.show();
    }

    private void statusDialog(@NonNull DemoDto demo) {
        String[] statuses = {"completed", "cancelled"};
        String[] labels = {getString(R.string.demos_status_completed),
                getString(R.string.demos_status_cancelled)};
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.demos_action_update_status)
                .setItems(labels, (d, which) -> {
                    DemoRequests.Update update = new DemoRequests.Update();
                    update.status = statuses[which];
                    submitUpdate(demo, update, "cancelled".equals(statuses[which])
                            ? getString(R.string.demos_cancelled)
                            : getString(R.string.demos_status_updated));
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void rescheduleDialog(@NonNull DemoDto demo) {
        LinearLayout wrapper = new LinearLayout(requireContext());
        wrapper.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);

        EditText date = new VoiceEditText(requireContext());
        date.setHint(R.string.demos_date_hint);
        date.setText(demo.date);
        wrapper.addView(date);
        EditText time = new VoiceEditText(requireContext());
        time.setHint(R.string.demos_time_hint);
        if (demo.time != null) time.setText(demo.time);
        wrapper.addView(time);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.demos_action_reschedule)
                .setView(wrapper)
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    String isoDate = date.getText() == null ? ""
                            : date.getText().toString().trim();
                    if (isoDate.isEmpty()) return;
                    DemoRequests.Update update = new DemoRequests.Update();
                    update.scheduledDate = isoDate;
                    String hhmm = time.getText() == null ? ""
                            : time.getText().toString().trim();
                    if (!hhmm.isEmpty()) update.scheduledTime = hhmm;
                    submitUpdate(demo, update, getString(R.string.demos_rescheduled));
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void submitUpdate(@NonNull DemoDto demo, @NonNull DemoRequests.Update update,
                              @NonNull String successMessage) {
        repository.update(demo.id, update, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                // Honest invite follow-through: only claim an invite was
                // drafted when the backend actually drafted one.
                String message = result.data.inviteMessageId != null
                        ? successMessage
                        : getString(R.string.demos_status_updated);
                Snackbar.make(binding.getRoot(), message, Snackbar.LENGTH_LONG).show();
                load();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message,
                        Snackbar.LENGTH_LONG).show();
            }
        });
    }

    // ── Month grid ───────────────────────────────────────────────────

    private class DayGridAdapter extends RecyclerView.Adapter<DayGridAdapter.CellHolder> {

        private final List<LocalDate> cells = new ArrayList<>();

        void rebuild() {
            cells.clear();
            // Monday-first offset of leading blanks (null = blank cell).
            int lead = month.atDay(1).getDayOfWeek().getValue() - 1;
            for (int i = 0; i < lead; i++) cells.add(null);
            for (int day = 1; day <= month.lengthOfMonth(); day++) {
                cells.add(month.atDay(day));
            }
            notifyDataSetChanged();
        }

        @NonNull
        @Override
        public CellHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new CellHolder(ItemDayCellBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull CellHolder holder, int position) {
            holder.bind(cells.get(position));
        }

        @Override
        public int getItemCount() {
            return cells.size();
        }

        class CellHolder extends RecyclerView.ViewHolder {
            private final ItemDayCellBinding cell;

            CellHolder(@NonNull ItemDayCellBinding cell) {
                super(cell.getRoot());
                this.cell = cell;
            }

            void bind(@Nullable LocalDate day) {
                if (day == null) {
                    cell.dayNumber.setText("");
                    cell.dayDots.setText("");
                    // Recycled cells may arrive with the selected-day circle.
                    cell.dayNumber.setBackgroundResource(0);
                    cell.getRoot().setOnClickListener(null);
                    cell.getRoot().setOnLongClickListener(null);
                    cell.getRoot().setClickable(false);
                    cell.getRoot().setLongClickable(false);
                    return;
                }
                cell.dayNumber.setText(String.valueOf(day.getDayOfMonth()));

                // Demo dots (primary colour) + task dots (amber) in one label.
                int demoCount = demosOn(day).size();
                List<TaskDto> dayTasks = tasksByDate.get(day.toString());
                int taskCount = dayTasks == null ? 0 : dayTasks.size();
                SpannableStringBuilder dots = new SpannableStringBuilder();
                for (int i = 0; i < Math.min(demoCount, 3); i++) dots.append('•');
                if (demoCount > 3) dots.append('+');
                if (taskCount > 0) {
                    int start = dots.length();
                    for (int i = 0; i < Math.min(taskCount, 3); i++) dots.append('•');
                    if (taskCount > 3) dots.append('+');
                    dots.setSpan(new ForegroundColorSpan(ContextCompat.getColor(
                                    requireContext(), R.color.amber_on_container)),
                            start, dots.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                }
                cell.dayDots.setText(dots);

                boolean selected = day.equals(selectedDay);
                cell.dayNumber.setBackgroundResource(selected
                        ? R.drawable.bg_day_selected : 0);
                cell.getRoot().setClickable(true);
                cell.getRoot().setOnClickListener(v -> {
                    selectedDay = day;
                    notifyDataSetChanged();
                    renderDay();
                });
                cell.getRoot().setLongClickable(true);
                cell.getRoot().setOnLongClickListener(v -> {
                    showTasksForDay(day);
                    return true;
                });
            }
        }
    }
}
