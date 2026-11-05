package com.yuvipep.app.feature.tasks;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.ProjectDetailDto;
import com.yuvipep.app.core.net.dto.ProjectDto;
import com.yuvipep.app.core.net.dto.TaskDto;
import com.yuvipep.app.core.net.dto.TaskRequests;
import com.yuvipep.app.core.net.dto.TaskResponses;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Call;
import retrofit2.Response;

/**
 * My tasks + the task lifecycle (/tasks/{id}/... in workflow.py, 03 §7).
 *
 * There is no single "my tasks, fully detailed" endpoint (11 §6e): GET
 * /action-items is thin (no phase/priority/blocked/progress/assignment_
 * reason/depends_on_ids), and the rich shape only exists embedded in
 * GET /projects/{id}.tasks[]. {@link #myTasks} therefore walks every project
 * the org has, keeps this user's tasks from each (rich), then unions in
 * whatever GET /action-items reports that wasn't already found (project-less
 * tasks, rendered honestly with the richer fields left blank rather than
 * guessed). Fine at demo/org scale; a real "my tasks" endpoint would replace
 * this if the backend ever adds one.
 */
@Singleton
public class TasksRepository {

    /** Aggregated My Tasks result: the best list we could build, plus an
     * optional non-fatal warning when one of the underlying calls failed
     * but we still had something to show. */
    public static class MyTasks {
        @NonNull public final List<TaskDto> tasks;
        @Nullable public final String warning;

        MyTasks(@NonNull List<TaskDto> tasks, @Nullable String warning) {
            this.tasks = tasks;
            this.warning = warning;
        }
    }

    private final ApiService api;
    private final AppExecutors executors;
    private final TokenStore tokenStore;

    @Inject
    public TasksRepository(ApiService api, AppExecutors executors, TokenStore tokenStore) {
        this.api = api;
        this.executors = executors;
        this.tokenStore = tokenStore;
    }

    public void myTasks(@NonNull RepoCallback<MyTasks> callback) {
        executors.io().execute(() -> {
            String myId = tokenStore.getUserId();
            List<TaskDto> tasks = new ArrayList<>();
            Set<String> seenIds = new HashSet<>();
            String warning = null;

            try {
                Response<List<ProjectDto>> projectsResponse = api.projects(null).execute();
                if (projectsResponse.isSuccessful() && projectsResponse.body() != null) {
                    for (ProjectDto project : projectsResponse.body()) {
                        try {
                            Response<ProjectDetailDto> detail =
                                    api.project(project.id).execute();
                            if (!detail.isSuccessful() || detail.body() == null) continue;
                            List<TaskDto> projectTasks = detail.body().tasks;
                            if (projectTasks == null) continue;
                            for (TaskDto task : projectTasks) {
                                if (myId == null || !myId.equals(task.assigneeId)) continue;
                                task.projectId = project.id;
                                task.projectName = project.name;
                                task.rich = true;
                                tasks.add(task);
                                seenIds.add(task.id);
                            }
                        } catch (IOException perProjectFailure) {
                            // One project's detail failing shouldn't blank the
                            // whole screen — skip it, note nothing (best-effort).
                        }
                    }
                } else {
                    warning = ErrorMapper.fromResponse(projectsResponse).message;
                }
            } catch (IOException e) {
                warning = ErrorMapper.fromThrowable(e).message;
            }

            try {
                Response<List<TaskDto>> thin =
                        api.actionItems("all", "me", null, 200, 0).execute();
                if (thin.isSuccessful() && thin.body() != null) {
                    for (TaskDto task : thin.body()) {
                        if (seenIds.contains(task.id)) continue;
                        task.rich = false;
                        tasks.add(task);
                    }
                } else if (tasks.isEmpty()) {
                    warning = ErrorMapper.fromResponse(thin).message;
                }
            } catch (IOException e) {
                if (tasks.isEmpty()) warning = ErrorMapper.fromThrowable(e).message;
            }

            if (tasks.isEmpty() && warning != null) {
                post(callback, Result.error(
                        new com.yuvipep.app.core.net.ApiError(0, warning, false)));
            } else {
                post(callback, Result.success(new MyTasks(tasks, warning)));
            }
        });
    }

    /** The thin /action-items list scoped to one owner — used by
     * TaskDetailFragment to backfill description/result_note/completed_at
     * onto a task discovered via a project's richer (but narrative-less)
     * embedded shape (11 §6e). */
    public void actionItemsForOwner(@NonNull String ownerId,
                                    @NonNull RepoCallback<List<TaskDto>> callback) {
        run(api.actionItems("all", ownerId, null, 200, 0), callback);
    }

    public void complete(@NonNull String taskId, @Nullable String resultNote,
                         @NonNull RepoCallback<TaskResponses.Complete> callback) {
        TaskRequests.Complete body = new TaskRequests.Complete();
        body.resultNote = resultNote;
        run(api.completeTask(taskId, body), callback);
    }

    public void decline(@NonNull String taskId, @NonNull String reason,
                        @Nullable String note,
                        @NonNull RepoCallback<TaskResponses.Decline> callback) {
        run(api.declineTask(taskId, new TaskRequests.Decline(reason, note)), callback);
    }

    public void block(@NonNull String taskId, @NonNull String reason,
                      @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.blockTask(taskId, new TaskRequests.Block(reason)), callback);
    }

    public void unblock(@NonNull String taskId,
                        @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.unblockTask(taskId), callback);
    }

    public void progress(@NonNull String taskId, int percent, @Nullable String note,
                         @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.updateTaskProgress(taskId, new TaskRequests.Progress(percent, note)), callback);
    }

    public void newDate(@NonNull String taskId, @NonNull String isoDate,
                        @Nullable String reason,
                        @NonNull RepoCallback<TaskResponses.NewDate> callback) {
        run(api.newTaskDate(taskId, new TaskRequests.NewDate(isoDate, reason)), callback);
    }

    public void split(@NonNull String taskId, @NonNull List<Map<String, Object>> parts,
                      @NonNull RepoCallback<TaskResponses.Split> callback) {
        run(api.splitTask(taskId, new TaskRequests.Split(parts)), callback);
    }

    public void vendorPromise(@NonNull String taskId, @NonNull String vendorName,
                              @NonNull String isoDate,
                              @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.vendorPromise(taskId, new TaskRequests.VendorPromise(vendorName, isoDate)),
                callback);
    }

    public void vendorSlip(@NonNull String taskId, @NonNull String isoDate,
                           @Nullable String note,
                           @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.vendorSlip(taskId, new TaskRequests.VendorSlip(isoDate, note)), callback);
    }

    private <T> void run(@NonNull Call<T> call, @NonNull RepoCallback<T> callback) {
        executors.io().execute(() -> {
            try {
                Response<T> response = call.execute();
                if (response.isSuccessful() && response.body() != null) {
                    post(callback, Result.success(response.body()));
                } else {
                    post(callback, Result.error(ErrorMapper.fromResponse(response)));
                }
            } catch (IOException e) {
                post(callback, Result.error(ErrorMapper.fromThrowable(e)));
            }
        });
    }

    private <T> void post(@NonNull RepoCallback<T> callback, @NonNull Result<T> result) {
        executors.main().execute(() -> callback.onResult(result));
    }
}
