package com.yuvipep.app.feature.tasks;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.dto.TaskDto;

/** One row in My Tasks: a section header or a task card. */
public class TaskRow {
    public enum Kind { HEADER, TASK }

    @NonNull public final Kind kind;
    @Nullable public final String header;
    @Nullable public final TaskDto task;

    private TaskRow(@NonNull Kind kind, @Nullable String header, @Nullable TaskDto task) {
        this.kind = kind;
        this.header = header;
        this.task = task;
    }

    public static TaskRow header(@NonNull String label) {
        return new TaskRow(Kind.HEADER, label, null);
    }

    public static TaskRow task(@NonNull TaskDto task) {
        return new TaskRow(Kind.TASK, null, task);
    }
}
