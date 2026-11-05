package com.yuvipep.app.feature.tasks;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.recyclerview.widget.RecyclerView;

import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.databinding.ItemTaskCardBinding;
import com.yuvipep.app.databinding.ItemTaskSectionHeaderBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import java.util.List;

/** Today / This week / Blocked groups (03 §7) — two view types, one list. */
public class MyTasksAdapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {

    public interface Listener {
        void onOpenTask(@NonNull TaskDto task);

        /** The client chip on a card: open that task's lead. */
        void onOpenLead(@NonNull String leadId);
    }

    /**
     * The school to show on the card's client chip, or null for no chip.
     *
     * <p>Customer ask, 21 Sep 2026: a task about "ABC School" should say so and
     * lead there. The meta line used to show the project and fall back to the
     * school only when there was none, so a task out of a meeting (which
     * usually has a project) never named its client. A chip needs a lead to
     * open, hence no lead id, no chip.
     */
    @Nullable
    static String clientOf(@NonNull TaskDto task) {
        if (task.leadId == null || task.leadName == null) return null;
        String name = task.leadName.trim();
        return name.isEmpty() ? null : name;
    }

    /**
     * The first part of the meta line: the project, or the school when there
     * is no chip to carry it. Null when neither applies.
     */
    @Nullable
    static String contextOf(@NonNull TaskDto task) {
        if (task.projectName != null) return task.projectName;
        if (clientOf(task) != null) return null;
        return task.leadName;
    }

    private static final int TYPE_HEADER = 0;
    private static final int TYPE_TASK = 1;

    private final List<TaskRow> rows;
    private final Listener listener;

    public MyTasksAdapter(@NonNull List<TaskRow> rows, @NonNull Listener listener) {
        this.rows = rows;
        this.listener = listener;
    }

    @Override
    public int getItemViewType(int position) {
        return rows.get(position).kind == TaskRow.Kind.HEADER ? TYPE_HEADER : TYPE_TASK;
    }

    @NonNull
    @Override
    public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        LayoutInflater inflater = LayoutInflater.from(parent.getContext());
        if (viewType == TYPE_HEADER) {
            return new HeaderHolder(ItemTaskSectionHeaderBinding.inflate(inflater, parent, false));
        }
        return new TaskHolder(ItemTaskCardBinding.inflate(inflater, parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull RecyclerView.ViewHolder holder, int position) {
        TaskRow row = rows.get(position);
        if (holder instanceof HeaderHolder) {
            ((HeaderHolder) holder).bind(row.header);
        } else {
            ((TaskHolder) holder).bind(row.task, listener);
        }
    }

    @Override
    public int getItemCount() {
        return rows.size();
    }

    static class HeaderHolder extends RecyclerView.ViewHolder {
        private final ItemTaskSectionHeaderBinding row;

        HeaderHolder(ItemTaskSectionHeaderBinding row) {
            super(row.getRoot());
            this.row = row;
        }

        void bind(String label) {
            ((android.widget.TextView) row.getRoot()).setText(label);
        }
    }

    static class TaskHolder extends RecyclerView.ViewHolder {
        private final ItemTaskCardBinding row;

        TaskHolder(ItemTaskCardBinding row) {
            super(row.getRoot());
            this.row = row;
        }

        void bind(TaskDto task, Listener listener) {
            row.taskTitle.setText(task.title);

            StringBuilder meta = new StringBuilder();
            String context = contextOf(task);
            if (context != null) meta.append(context);
            if (task.phase != null) {
                if (meta.length() > 0) meta.append(" · ");
                meta.append(LeadStates.label(task.phase));
            }
            if (task.dueDate != null) {
                if (meta.length() > 0) meta.append(" · ");
                meta.append("due ").append(
                        com.yuvipep.app.core.util.Times.dateLabel(task.dueDate));
            } else {
                if (meta.length() > 0) meta.append(" · ");
                meta.append(row.getRoot().getContext()
                        .getString(com.yuvipep.app.R.string.my_tasks_no_due));
            }
            row.taskMeta.setText(meta);

            if (task.blocked) {
                row.taskBadge.setText(com.yuvipep.app.R.string.my_tasks_blocked);
                row.taskBadge.setVisibility(View.VISIBLE);
            } else if (!task.rich) {
                row.taskBadge.setVisibility(View.GONE);
            } else {
                row.taskBadge.setVisibility(View.GONE);
            }

            row.priorityEdge.setVisibility("P1".equals(task.priority) ? View.VISIBLE : View.GONE);

            if (task.progressPercent != null) {
                row.taskProgress.setVisibility(View.VISIBLE);
                row.taskProgress.setProgress(task.progressPercent);
            } else {
                row.taskProgress.setVisibility(View.GONE);
            }

            String client = clientOf(task);
            if (client != null) {
                row.taskClient.setText(client);
                row.taskClient.setContentDescription(row.getRoot().getContext()
                        .getString(com.yuvipep.app.R.string.my_tasks_open_client, client));
                row.taskClient.setVisibility(View.VISIBLE);
                row.taskClient.setOnClickListener(v -> listener.onOpenLead(task.leadId));
            } else {
                row.taskClient.setVisibility(View.GONE);
                row.taskClient.setOnClickListener(null);
            }

            row.getRoot().setOnClickListener(v -> listener.onOpenTask(task));
        }
    }
}
