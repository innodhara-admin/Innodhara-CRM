package com.yuvipep.app.feature.notifications;

import androidx.annotation.NonNull;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import com.yuvipep.app.core.db.AppDatabase;
import com.yuvipep.app.core.db.CachedNotification;
import com.yuvipep.app.core.db.CachedNotificationDao;
import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.OfflineQueue;
import com.yuvipep.app.core.net.dto.NotificationDto;
import com.yuvipep.app.core.util.AppExecutors;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Response;

/**
 * Server-truth notification feed mirrored into Room (07 §1–2). Polling is
 * delta-based (`?since=`) so the 60-second foreground loop stays cheap.
 */
@Singleton
public class NotificationRepository {

    private final ApiService api;
    private final CachedNotificationDao dao;
    private final OfflineQueue offlineQueue;
    private final AppExecutors executors;

    /** Fired with freshly-arrived (previously unseen) notifications. */
    private final MutableLiveData<List<CachedNotification>> newArrivals =
            new MutableLiveData<>();

    @Inject
    public NotificationRepository(ApiService api, AppDatabase database,
                                  OfflineQueue offlineQueue, AppExecutors executors) {
        this.api = api;
        this.dao = database.notificationDao();
        this.offlineQueue = offlineQueue;
        this.executors = executors;
    }

    public LiveData<List<CachedNotification>> observeAll() {
        return dao.observeAll();
    }

    public LiveData<Integer> observeUnreadCount() {
        return dao.observeUnreadCount();
    }

    public LiveData<List<CachedNotification>> newArrivals() {
        return newArrivals;
    }

    /** The newest page fetched on every refresh. */
    private static final int PAGE = 100;

    /** Async refresh for UI callers (poller, pull-to-refresh). */
    public void refreshAsync() {
        executors.io().execute(this::refreshBlocking);
    }

    /**
     * Delta-fetch new rows, then re-sync read flags on the newest page.
     * Returns the notifications that were new to this device (empty on
     * network trouble — the cache keeps serving).
     */
    @NonNull
    public List<CachedNotification> refreshBlocking() {
        List<CachedNotification> fresh = new ArrayList<>();
        try {
            String since = dao.newestCreatedAt();
            if (since != null) {
                Response<List<NotificationDto>> delta =
                        api.notifications(false, 200, 0, since).execute();
                if (delta.isSuccessful() && delta.body() != null) {
                    fresh = toRows(delta.body());
                    if (!fresh.isEmpty()) {
                        dao.upsertAll(fresh);
                        newArrivals.postValue(fresh);
                    }
                }
            }
            // Full newest page keeps read-flags honest across devices (and
            // is the initial load when the cache is empty).
            Response<List<NotificationDto>> page =
                    api.notifications(false, PAGE, 0, null).execute();
            if (page.isSuccessful() && page.body() != null) {
                List<CachedNotification> rows = toRows(page.body());
                if (since == null && !rows.isEmpty()) {
                    fresh = rows;
                    newArrivals.postValue(rows);
                }
                dao.upsertAll(rows);
                // Drop what the server deleted (24 Sep 2026: the daily-digest
                // flood was removed server-side and stayed on the phone).
                List<String> ids = new ArrayList<>();
                List<String> times = new ArrayList<>();
                for (CachedNotification r : rows) {
                    ids.add(r.id);
                    times.add(r.createdAt);
                }
                String cutoff = NotificationPrune.cutoff(times, PAGE);
                if (cutoff == null) {
                    if (ids.isEmpty()) dao.clear(); else dao.deleteAllExcept(ids);
                } else {
                    dao.deleteSinceExcept(cutoff, ids);
                }
            }
        } catch (IOException | RuntimeException ignored) {
            // Offline: cache-first screens carry on; poller will retry.
        }
        return fresh;
    }

    /** Optimistic mark-read; offline it queues (idempotent server-side). */
    public void markRead(@NonNull String notificationId) {
        executors.io().execute(() -> {
            dao.markRead(notificationId);
            try {
                api.markNotificationRead(notificationId).execute();
            } catch (IOException e) {
                offlineQueue.enqueue("POST",
                        "api/v1/notifications/" + notificationId + "/read",
                        "{}", OfflineQueue.mintKey(), null);
            }
        });
    }

    @NonNull
    private static List<CachedNotification> toRows(@NonNull List<NotificationDto> dtos) {
        List<CachedNotification> rows = new ArrayList<>(dtos.size());
        long now = System.currentTimeMillis();
        for (NotificationDto dto : dtos) {
            if (dto.id == null) continue;
            CachedNotification row = new CachedNotification();
            row.id = dto.id;
            row.title = dto.title;
            row.body = dto.body;
            row.kind = dto.kind;
            row.entityType = dto.entityType;
            row.entityId = dto.entityId;
            row.isRead = dto.isRead;
            row.createdAt = dto.createdAt;
            row.fetchedAt = now;
            rows.add(row);
        }
        return rows;
    }

    /** Unread rows straight from Room (worker use — call off-main). */
    @NonNull
    public List<CachedNotification> unreadCached() {
        return dao.getUnread();
    }

    /** All cached rows, newest first (call off-main). */
    @NonNull
    public List<CachedNotification> allCached() {
        return dao.getAll();
    }
}
