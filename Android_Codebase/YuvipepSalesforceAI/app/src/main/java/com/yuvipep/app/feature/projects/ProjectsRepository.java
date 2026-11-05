package com.yuvipep.app.feature.projects;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.ConflictDto;
import com.yuvipep.app.core.net.dto.DraftMessageResponse;
import com.yuvipep.app.core.net.dto.MessageRequests;
import com.yuvipep.app.core.net.dto.PlanVersionDto;
import com.yuvipep.app.core.net.dto.ProjectDetailDto;
import com.yuvipep.app.core.net.dto.ProjectDto;
import com.yuvipep.app.core.net.dto.ProjectRequests;
import com.yuvipep.app.core.net.dto.ProjectResponses;
import com.yuvipep.app.core.net.dto.TimelineEventDto;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.Map;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Call;
import retrofit2.Response;

/** Projects, plans, timeline, people, team, conflicts, chain deals, reports
 * — the /projects router (Phase 4, 03 §6). */
@Singleton
public class ProjectsRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public ProjectsRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    public void portfolio(@Nullable String status,
                          @NonNull RepoCallback<List<ProjectDto>> callback) {
        run(api.projectsPortfolio(status), callback);
    }

    /** F58: resolve a conflict/plan id to its project so a notification can
     *  open the tab that already renders it. */
    public void resolveProjectForEntity(
            @NonNull String entityType, @NonNull String entityId,
            @NonNull RepoCallback<com.yuvipep.app.core.net.dto.ResolvedProject> callback) {
        run(api.resolveProjectForEntity(entityType, entityId), callback);
    }

    public void detail(@NonNull String projectId,
                       @NonNull RepoCallback<ProjectDetailDto> callback) {
        run(api.project(projectId), callback);
    }

    public void timeline(@NonNull String projectId,
                         @NonNull RepoCallback<List<TimelineEventDto>> callback) {
        run(api.projectTimeline(projectId, 100), callback);
    }

    public void plans(@NonNull String projectId,
                      @NonNull RepoCallback<List<PlanVersionDto>> callback) {
        run(api.projectPlans(projectId), callback);
    }

    public void setStatus(@NonNull String projectId, @NonNull String status,
                          @Nullable String reason,
                          @NonNull RepoCallback<ProjectDto> callback) {
        run(api.setProjectStatus(projectId, new ProjectRequests.Status(status, reason)),
                callback);
    }

    public void phaseShift(@NonNull String projectId, @NonNull String phase,
                           @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.phaseShift(projectId, new ProjectRequests.PhaseShift(phase)), callback);
    }

    public void whatsBlocking(@NonNull String projectId,
                              @NonNull RepoCallback<ProjectResponses.WhatsBlocking> callback) {
        run(api.whatsBlocking(projectId), callback);
    }

    public void brief(@NonNull String projectId,
                      @NonNull RepoCallback<ProjectResponses.Brief> callback) {
        run(api.projectBrief(projectId), callback);
    }

    public void addStakeholder(@NonNull String projectId,
                               @NonNull ProjectRequests.Stakeholder body,
                               @NonNull RepoCallback<ProjectResponses.StakeholderSaved> callback) {
        run(api.addStakeholder(projectId, body), callback);
    }

    public void conflicts(@NonNull String projectId,
                          @NonNull RepoCallback<List<ConflictDto>> callback) {
        run(api.projectConflicts(projectId), callback);
    }

    public void resolveConflict(@NonNull String projectId, @NonNull String conflictId,
                                @NonNull String note,
                                @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.resolveConflict(projectId, conflictId,
                new ProjectRequests.ResolveConflict(note)), callback);
    }

    public void createChildren(@NonNull String projectId, @NonNull List<String> branchNames,
                               @NonNull String invoicingMode,
                               @NonNull RepoCallback<ProjectResponses.Children> callback) {
        run(api.createChildProjects(projectId,
                new ProjectRequests.Children(branchNames, invoicingMode)), callback);
    }

    public void weeklyReport(@NonNull String projectId, @NonNull String kind,
                             @NonNull RepoCallback<ProjectResponses.WeeklyReport> callback) {
        run(api.weeklyReport(projectId, kind), callback);
    }

    public void addMember(@NonNull String projectId, @NonNull String userId,
                          @Nullable String roleInProject,
                          @NonNull RepoCallback<ProjectResponses.MemberAdded> callback) {
        run(api.addProjectMember(projectId, new ProjectRequests.Member(userId, roleInProject)),
                callback);
    }

    public void removeMember(@NonNull String projectId, @NonNull String userId,
                             @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.removeProjectMember(projectId, userId), callback);
    }

    public void draftMessage(@NonNull MessageRequests.Draft body,
                             @NonNull RepoCallback<DraftMessageResponse> callback) {
        run(api.draftMessage(body), callback);
    }

    static <T> List<T> emptyIfNull(@Nullable List<T> list) {
        return list == null ? Collections.emptyList() : list;
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
