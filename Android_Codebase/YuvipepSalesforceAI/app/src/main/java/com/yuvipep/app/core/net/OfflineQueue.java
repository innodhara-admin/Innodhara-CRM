package com.yuvipep.app.core.net;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;

import com.yuvipep.app.core.db.AppDatabase;
import com.yuvipep.app.core.db.CachedApprovalDao;
import com.yuvipep.app.core.db.QueuedWrite;
import com.yuvipep.app.core.db.QueuedWriteDao;
import com.yuvipep.app.core.util.AppExecutors;

import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.UUID;

import javax.inject.Inject;
import javax.inject.Singleton;

import dagger.hilt.android.qualifiers.ApplicationContext;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

/**
 * The OfflineQueue (07 §4): state-changing calls captured while offline,
 * drained FIFO on connectivity. Fully generic — it replays {method, path,
 * body} with the idempotency key minted at intent time, so any feature can
 * queue any write without new queue code.
 *
 * Honesty rules: a 4xx on replay marks the write failed with the backend's
 * own message (never a silent drop); 5xx/network keeps it pending for the
 * next drain.
 */
@Singleton
public class OfflineQueue {

    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final String WORK_NAME = "offline-queue-drain";

    private final Context appContext;
    private final QueuedWriteDao dao;
    private final CachedApprovalDao approvalDao;
    private final OkHttpClient client;
    private final EnvironmentStore environmentStore;
    private final AppExecutors executors;

    @Inject
    public OfflineQueue(@ApplicationContext Context appContext,
                        AppDatabase database,
                        OkHttpClient client,
                        EnvironmentStore environmentStore,
                        AppExecutors executors) {
        this.appContext = appContext;
        this.dao = database.queuedWriteDao();
        this.approvalDao = database.approvalDao();
        this.client = client;
        this.environmentStore = environmentStore;
        this.executors = executors;
    }

    public static String mintKey() {
        return UUID.randomUUID().toString();
    }

    /** Queue a write (call from a background thread). Schedules the drain. */
    public void enqueue(@NonNull String method, @NonNull String path,
                        @NonNull String bodyJson, @NonNull String idempotencyKey,
                        @Nullable String entityHint) {
        QueuedWrite write = new QueuedWrite();
        write.method = method;
        write.path = path;
        write.bodyJson = bodyJson;
        write.idempotencyKey = idempotencyKey;
        write.entityHint = entityHint;
        write.createdAt = System.currentTimeMillis();
        dao.enqueue(write);
        scheduleDrain();
    }

    /** WorkManager one-shot, network-constrained, survives process death. */
    public void scheduleDrain() {
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(QueueDrainWorker.class)
                .setConstraints(new Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, Duration.ofSeconds(30))
                .build();
        WorkManager.getInstance(appContext)
                .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.KEEP, request);
    }

    /** Fire-and-forget drain attempt from app code (e.g. on foreground). */
    public void drainAsync() {
        executors.io().execute(this::drainBlocking);
    }

    /**
     * Replay pending writes in order. Returns true when the queue is empty
     * afterwards (drained or nothing to do), false when network trouble
     * stopped the drain (WorkManager will retry).
     */
    public boolean drainBlocking() {
        List<QueuedWrite> pending = dao.pending();
        for (QueuedWrite write : pending) {
            String base = environmentStore.getBaseUrl();
            Request request = new Request.Builder()
                    .url(base + "/" + write.path)
                    .method(write.method, RequestBody.create(write.bodyJson, JSON))
                    .header("Idempotency-Key", write.idempotencyKey)
                    .build();
            try (Response response = client.newCall(request).execute()) {
                if (response.isSuccessful()) {
                    dao.delete(write.seq);
                    onApplied(write);
                } else if (response.code() >= 400 && response.code() < 500
                        && response.code() != 401) {
                    // The server understood and refused — surface it honestly.
                    String detail = null;
                    if (response.body() != null) {
                        detail = ErrorMapper.extractDetail(response.body().string());
                    }
                    if (detail == null || detail.isEmpty()) {
                        detail = "Request failed (" + response.code() + ")";
                    }
                    write.state = QueuedWrite.STATE_FAILED;
                    write.lastError = detail;
                    write.attempts++;
                    dao.update(write);
                    onRefused(write, detail);
                } else {
                    // 401 (token being refreshed) or 5xx — retry later.
                    write.attempts++;
                    dao.update(write);
                    return false;
                }
            } catch (IOException e) {
                write.attempts++;
                dao.update(write);
                return false;   // still offline; WorkManager retries
            }
        }
        return true;
    }

    /** A queued write landed — update the local mirror it was about. */
    private void onApplied(@NonNull QueuedWrite write) {
        String approvalId = approvalIdFrom(write.entityHint);
        if (approvalId != null) {
            // Decision applied server-side: the card leaves the pending feed.
            approvalDao.delete(approvalId);
        }
    }

    private void onRefused(@NonNull QueuedWrite write, @NonNull String message) {
        String approvalId = approvalIdFrom(write.entityHint);
        if (approvalId != null) {
            approvalDao.setLocalState(approvalId, "failed:" + message);
        }
    }

    @Nullable
    private static String approvalIdFrom(@Nullable String entityHint) {
        if (entityHint != null && entityHint.startsWith("approval:")) {
            return entityHint.substring("approval:".length());
        }
        return null;
    }
}
