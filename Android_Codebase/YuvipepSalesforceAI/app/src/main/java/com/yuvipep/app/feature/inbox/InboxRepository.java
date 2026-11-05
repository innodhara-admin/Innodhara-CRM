package com.yuvipep.app.feature.inbox;

import androidx.annotation.NonNull;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.InboundIngestRequest;
import com.yuvipep.app.core.net.dto.InboundIngestResponse;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.net.dto.LeadDto;
import com.yuvipep.app.core.net.dto.MessageDto;
import com.yuvipep.app.core.net.dto.ProjectDto;
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
 * The Inbox's data (03 §9): the outbound message centre with its delivery
 * trace, and the inbound triage queue.
 *
 * The lead/project lookups are here too because triage's "attach to…" pickers
 * need them: the backend resolves a message's client from one of its contacts,
 * so attaching means picking a lead and then one of its contacts.
 */
@Singleton
public class InboxRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public InboxRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    /** @param status any MessageStatus value, or "all". */
    public void messages(@NonNull String status, int limit, int offset,
                         @NonNull RepoCallback<List<MessageDto>> callback) {
        run(api.messages(status, limit, offset), callback);
    }

    public void message(@NonNull String messageId,
                        @NonNull RepoCallback<MessageDto> callback) {
        run(api.message(messageId), callback);
    }

    public void triageQueue(@NonNull RepoCallback<List<TriageItemDto>> callback) {
        run(api.triageQueue(), callback);
    }

    public void resolveTriage(@NonNull String messageId, @NonNull TriageResolveRequest body,
                              @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.resolveTriage(messageId, body), callback);
    }

    public void logClientReply(@NonNull InboundIngestRequest body,
                               @NonNull RepoCallback<InboundIngestResponse> callback) {
        run(api.ingestInbound(body), callback);
    }

    public void leads(@NonNull RepoCallback<List<LeadDto>> callback) {
        run(api.leads(null, null, false, false, 200, 0), callback);
    }

    public void lead(@NonNull String leadId,
                     @NonNull RepoCallback<LeadDetailResponse> callback) {
        run(api.leadDetail(leadId), callback);
    }

    public void projects(@NonNull RepoCallback<List<ProjectDto>> callback) {
        run(api.projectsPortfolio(null), callback);
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
