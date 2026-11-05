package com.yuvipep.app.feature.followups;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.FollowUpDto;
import com.yuvipep.app.core.net.dto.FollowUpRequests;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.IOException;
import java.util.List;
import java.util.Map;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Call;
import retrofit2.Response;

/** The /followups router: due queue + complete (03 §12). Completing one
 * auto-schedules the next reminder server-side — the app just says so. */
@Singleton
public class FollowupsRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public FollowupsRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    /** due: today | overdue | this_week | all_pending | all */
    public void list(@NonNull String due, boolean mine,
                     @NonNull RepoCallback<List<FollowUpDto>> callback) {
        run(api.followups(due, mine), callback);
    }

    public void complete(@NonNull String followupId, @Nullable String note,
                         boolean scheduleNext,
                         @NonNull RepoCallback<Map<String, Object>> callback) {
        FollowUpRequests.Complete body = new FollowUpRequests.Complete();
        body.note = note;
        body.scheduleNext = scheduleNext;
        run(api.completeFollowup(followupId, body), callback);
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
