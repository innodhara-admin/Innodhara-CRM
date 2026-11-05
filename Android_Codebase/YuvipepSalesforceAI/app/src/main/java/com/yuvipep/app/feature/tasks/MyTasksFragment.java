package com.yuvipep.app.feature.tasks;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.snackbar.Snackbar;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.core.util.WorkDay;
import com.yuvipep.app.databinding.FragmentMyTasksBinding;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * My Tasks (03 §7): Blocked / Today / This week / Later, P1 pinned within
 * each group. There is no "waiting on vendor" group — neither task surface
 * the backend exposes (GET /action-items, GET /projects/{id}.tasks[])
 * returns the vendor external_wait field, so the app can't tell a vendor
 * wait apart from any other open task (11 §6e); showing an always-empty
 * section would be exactly the kind of fake the app promises never to do.
 */
@AndroidEntryPoint
public class MyTasksFragment extends Fragment implements MyTasksAdapter.Listener {

    @Inject TasksRepository repository;
    @Inject com.yuvipep.app.core.db.CachedUserDao cachedUserDao;
    @Inject com.yuvipep.app.core.util.AppExecutors executors;

    private FragmentMyTasksBinding binding;
    private MyTasksAdapter adapter;
    private final List<TaskRow> rows = new ArrayList<>();
    @Nullable private String orgTimezone;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentMyTasksBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        adapter = new MyTasksAdapter(rows, this);
        binding.taskList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.taskList.setAdapter(adapter);
        binding.swipeRefresh.setOnRefreshListener(this::load);
    }

    @Override
    public void onResume() {
        super.onResume();
        refreshOrgTimezone();
        load();
    }

    /**
     * Read the organisation's zone from the cached session.
     *
     * <p>Room forbids main-thread queries, and this is a cache read that must
     * not delay the list: it lands before or shortly after the tasks do, and a
     * null simply means "use the device", which is what this screen did before
     * the server started sending one.
     */
    private void refreshOrgTimezone() {
        executors.io().execute(() -> {
            com.yuvipep.app.core.db.CachedUser cached = cachedUserDao.getAny();
            String zone = cached != null ? cached.orgTimezone : null;
            executors.main().execute(() -> {
                if (binding == null) return;
                if (zone != null && !zone.equals(orgTimezone)) {
                    orgTimezone = zone;
                    load();
                } else {
                    orgTimezone = zone;
                }
            });
        });
    }

    private void load() {
        if (binding == null) return;
        if (rows.isEmpty()) binding.stateView.showLoading();
        repository.myTasks(result -> {
            if (binding == null) return;
            binding.swipeRefresh.setRefreshing(false);
            if (result.isSuccess() && result.data != null) {
                group(result.data.tasks);
                if (result.data.warning != null) {
                    Snackbar.make(binding.getRoot(), result.data.warning,
                            Snackbar.LENGTH_LONG).show();
                }
            } else if (result.isError() && result.error != null) {
                if (rows.isEmpty()) {
                    binding.stateView.showError(result.error.message, this::load);
                } else {
                    Snackbar.make(binding.getRoot(), result.error.message,
                            Snackbar.LENGTH_LONG).show();
                }
            }
        });
    }

    private void group(@NonNull List<TaskDto> tasks) {
        List<TaskDto> active = new ArrayList<>();
        for (TaskDto t : tasks) {
            if ("open".equals(t.status) || "in_progress".equals(t.status)) active.add(t);
        }

        List<TaskDto> blocked = new ArrayList<>();
        // F53: there was no Overdue bucket at all, so `due <= today` swept late
        // work into "Today" — Baski's tasks due 31 Jul, 1 Aug and 3 Aug all sat
        // under "Today" on 5 Aug, one of them five days late, with nothing on
        // the row to say so. Ships with [F52], which fixed the opposite error on
        // Home: the briefing was calling today's work overdue while this screen
        // called overdue work today.
        List<TaskDto> overdue = new ArrayList<>();
        List<TaskDto> today = new ArrayList<>();
        List<TaskDto> week = new ArrayList<>();
        List<TaskDto> later = new ArrayList<>();

        // The ORGANISATION's zone, not the phone's. The backend answers
        // "which day is that?" in it (app/core/clock.py), and the two naming
        // different days for one row is the F65 mix one layer out. Falls back
        // to the device when the server did not say, which is what this screen
        // did before — so an older backend behaves exactly as it used to.
        ZoneId zone = WorkDay.zoneOf(orgTimezone);
        LocalDate todayDate = LocalDate.now(zone);

        for (TaskDto t : active) {
            switch (WorkDay.bucketOf(t.dueDate, todayDate, zone, t.blocked)) {
                case BLOCKED: blocked.add(t); break;
                case OVERDUE: overdue.add(t); break;
                case TODAY: today.add(t); break;
                case WEEK: week.add(t); break;
                default: later.add(t); break;
            }
        }

        Comparator<TaskDto> priorityFirst = Comparator.comparingInt(this::priorityRank)
                .thenComparing(t -> t.dueDate == null ? "9999" : t.dueDate);
        blocked.sort(priorityFirst);
        overdue.sort(priorityFirst);
        today.sort(priorityFirst);
        week.sort(priorityFirst);
        later.sort(priorityFirst);

        rows.clear();
        addSection(getString(R.string.my_tasks_blocked), blocked);
        // After Blocked, before Today: something you cannot start outranks
        // something you are already late on, which outranks today's work.
        addSection(getString(R.string.my_tasks_overdue), overdue);
        addSection(getString(R.string.my_tasks_today), today);
        addSection(getString(R.string.my_tasks_week), week);
        addSection(getString(R.string.my_tasks_later), later);
        adapter.notifyDataSetChanged();

        if (rows.isEmpty()) {
            binding.stateView.showEmpty(getString(R.string.my_tasks_empty_title),
                    getString(R.string.my_tasks_empty_body), R.drawable.ic_tab_tasks, null, null);
        } else {
            binding.stateView.hide();
        }
    }

    private void addSection(@NonNull String label, @NonNull List<TaskDto> tasks) {
        if (tasks.isEmpty()) return;
        rows.add(TaskRow.header(label));
        for (TaskDto t : tasks) rows.add(TaskRow.task(t));
    }

    private int priorityRank(@NonNull TaskDto t) {
        if ("P1".equals(t.priority)) return 0;
        if ("P2".equals(t.priority)) return 1;
        if ("P3".equals(t.priority)) return 2;
        return 3;
    }

    @Nullable
    @Override
    public void onOpenTask(@NonNull TaskDto task) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(
                    TaskDetailFragment.create(task.projectId, task.id));
        }
    }

    @Override
    public void onOpenLead(@NonNull String leadId) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(
                    com.yuvipep.app.feature.leads.LeadDetailFragment.create(leadId));
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
