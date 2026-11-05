package com.yuvipep.app.feature.approvals;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.lifecycle.LiveData;

import com.google.gson.Gson;
import com.yuvipep.app.core.db.AppDatabase;
import com.yuvipep.app.core.db.CachedApproval;
import com.yuvipep.app.core.db.CachedApprovalDao;
import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.OfflineQueue;
import com.yuvipep.app.core.net.dto.ApprovalDto;
import com.yuvipep.app.core.net.dto.DecideRequest;
import com.yuvipep.app.core.net.dto.DecideResponse;
import com.yuvipep.app.core.net.dto.MessageDto;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Response;

/**
 * Pending approvals, cache-first (07 §4). Deciding while offline queues the
 * decision with an idempotency key minted now — the card shows "queued" and
 * the OfflineQueue applies it when connectivity returns.
 */
@Singleton
public class ApprovalsRepository {

    /** What happened to a decide call. */
    public static final class DecideOutcome {
        public final boolean queuedOffline;
        @Nullable public final DecideResponse response;

        DecideOutcome(boolean queuedOffline, @Nullable DecideResponse response) {
            this.queuedOffline = queuedOffline;
            this.response = response;
        }
    }

    private final ApiService api;
    private final CachedApprovalDao dao;
    private final OfflineQueue offlineQueue;
    private final AppExecutors executors;
    private final Gson gson = new Gson();

    @Inject
    public ApprovalsRepository(ApiService api, AppDatabase database,
                               OfflineQueue offlineQueue, AppExecutors executors) {
        this.api = api;
        this.dao = database.approvalDao();
        this.offlineQueue = offlineQueue;
        this.executors = executors;
    }

    public LiveData<List<CachedApproval>> observePending() {
        return dao.observeAll();
    }

    public void refreshAsync() {
        executors.io().execute(this::refreshBlocking);
    }

    /** Pull my pending approvals into Room; prune ones the server closed. */
    public void refreshBlocking() {
        try {
            Response<List<ApprovalDto>> response = api.approvals("pending", true).execute();
            if (!response.isSuccessful() || response.body() == null) return;
            List<CachedApproval> rows = new ArrayList<>();
            List<String> ids = new ArrayList<>();
            long now = System.currentTimeMillis();
            for (ApprovalDto dto : response.body()) {
                if (dto.id == null) continue;
                CachedApproval existing = dao.byId(dto.id);
                CachedApproval row = new CachedApproval();
                row.id = dto.id;
                row.entityType = dto.entityType;
                row.entityId = dto.entityId;
                row.projectId = dto.projectId;
                row.stage = dto.stage;
                row.status = dto.status;
                row.reason = dto.reason;
                row.recommendation = dto.recommendation;
                row.jointWithUserId = dto.jointWithUserId;
                row.jointStatus = dto.jointStatus;
                row.bundledEntitiesJson = dto.bundledEntities != null
                        ? gson.toJson(dto.bundledEntities) : null;
                row.expiresAt = dto.expiresAt;
                // A locally queued/failed decision outlives the server copy
                // until it is drained or the user dismisses it.
                row.localState = existing != null ? existing.localState : "";
                rows.add(row);
                ids.add(dto.id);
            }
            dao.upsertAll(rows);
            if (ids.isEmpty()) {
                ids.add("__none__");    // NOT IN () is invalid SQL
            }
            dao.pruneExcept(ids);
        } catch (IOException | RuntimeException ignored) {
            // Offline — the cached feed stands.
        }
    }

    /**
     * Approve/reject. Online: applied immediately and the card leaves the
     * feed. Offline: queued with its idempotency key; the card flips to
     * "queued" until the drain lands it.
     */
    public void decide(@NonNull String approvalId, boolean approve,
                       @Nullable String note, @NonNull RepoCallback<DecideOutcome> callback) {
        decide(approvalId, approve, note, false, callback);
    }

    public void decide(@NonNull String approvalId, boolean approve,
                       @Nullable String note, boolean allowBlanks,
                       @NonNull RepoCallback<DecideOutcome> callback) {
        executors.io().execute(() -> {
            DecideRequest body = new DecideRequest(approve, note, allowBlanks);
            String key = OfflineQueue.mintKey();
            try {
                Response<DecideResponse> response =
                        api.decideApproval(approvalId, body, key).execute();
                if (response.isSuccessful() && response.body() != null) {
                    dao.delete(approvalId);
                    post(callback, Result.success(new DecideOutcome(false, response.body())));
                } else {
                    post(callback, Result.error(ErrorMapper.fromResponse(response)));
                }
            } catch (IOException e) {
                offlineQueue.enqueue("POST", "api/v1/approvals/" + approvalId + "/decide",
                        gson.toJson(body), key, "approval:" + approvalId);
                dao.setLocalState(approvalId, "queued");
                post(callback, Result.success(new DecideOutcome(true, null)));
            }
        });
    }

    /** Full draft preview for message approvals (03 §8). */
    public void messagePreview(@NonNull String messageId,
                               @NonNull RepoCallback<MessageDto> callback) {
        executors.io().execute(() -> {
            try {
                Response<MessageDto> response = api.message(messageId).execute();
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

    /** One cached approval row for the detail screen. */
    public void approval(@NonNull String approvalId,
                         @NonNull RepoCallback<CachedApproval> callback) {
        executors.io().execute(() -> {
            CachedApproval row = dao.byId(approvalId);
            executors.main().execute(() -> callback.onResult(row != null
                    ? Result.success(row)
                    : Result.error(new com.yuvipep.app.core.net.ApiError(
                            404, "This approval is no longer pending", false))));
        });
    }

    /** Clear a failed-queued marker after the user has seen the reason. */
    public void dismissLocalFailure(@NonNull String approvalId) {
        executors.io().execute(() -> dao.setLocalState(approvalId, ""));
    }

    private <T> void post(@NonNull RepoCallback<T> callback, @NonNull Result<T> result) {
        executors.main().execute(() -> callback.onResult(result));
    }
}
