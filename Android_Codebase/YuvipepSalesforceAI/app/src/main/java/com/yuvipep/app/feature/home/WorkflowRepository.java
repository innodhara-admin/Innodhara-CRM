package com.yuvipep.app.feature.home;

import androidx.annotation.NonNull;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.ConfirmBatchRequest;
import com.yuvipep.app.core.net.dto.ConfirmBatchResponse;
import com.yuvipep.app.core.net.dto.DigestResponse;
import com.yuvipep.app.core.net.dto.MeetingReviewResponse;
import com.yuvipep.app.core.net.dto.OrgUserDto;
import com.yuvipep.app.core.net.dto.ProposedAssignmentDto;
import com.yuvipep.app.core.net.dto.ReviewConfirmRequest;
import com.yuvipep.app.core.net.dto.ReviewConfirmResponse;
import com.yuvipep.app.core.net.dto.TriageItemDto;
import com.yuvipep.app.core.net.dto.TriageResolveRequest;
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

/**
 * The rest of the Phase 1 pulse: daily digest, proposed-assignment batches,
 * inbound triage and the meeting review gate — thin typed wrappers over the
 * backend workflow router, one generic execute path.
 */
@Singleton
public class WorkflowRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public WorkflowRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    public void dailyDigest(@NonNull RepoCallback<DigestResponse> callback) {
        run(api.dailyDigest(), callback);
    }

    public void proposedAssignments(@NonNull RepoCallback<List<ProposedAssignmentDto>> callback) {
        run(api.proposedAssignments(), callback);
    }

    public void waitingOnMe(
            @NonNull RepoCallback<com.yuvipep.app.core.net.dto.WaitingOnMeDto> callback) {
        run(api.waitingOnMe(), callback);
    }

    public void confirmAssignmentBatch(@NonNull ConfirmBatchRequest body,
                                       @NonNull RepoCallback<ConfirmBatchResponse> callback) {
        run(api.confirmAssignmentBatch(body), callback);
    }

    public void triageQueue(@NonNull RepoCallback<List<TriageItemDto>> callback) {
        run(api.triageQueue(), callback);
    }

    public void resolveTriage(@NonNull String messageId, @NonNull TriageResolveRequest body,
                              @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.resolveTriage(messageId, body), callback);
    }

    public void meetingReview(@NonNull String meetingId,
                              @NonNull RepoCallback<MeetingReviewResponse> callback) {
        run(api.meetingReview(meetingId), callback);
    }

    public void confirmMeetingReview(@NonNull String meetingId,
                                     @NonNull ReviewConfirmRequest body,
                                     @NonNull RepoCallback<ReviewConfirmResponse> callback) {
        run(api.confirmMeetingReview(meetingId, body), callback);
    }

    public void orgUsers(@NonNull RepoCallback<List<OrgUserDto>> callback) {
        run(api.orgUsers(), callback);
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
