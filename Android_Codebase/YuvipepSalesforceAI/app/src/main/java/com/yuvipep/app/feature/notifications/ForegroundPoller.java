package com.yuvipep.app.feature.notifications;

import android.os.Handler;
import android.os.Looper;

import com.yuvipep.app.core.net.OfflineQueue;
import com.yuvipep.app.feature.approvals.ApprovalsRepository;

import javax.inject.Inject;
import javax.inject.Singleton;

/**
 * The polite 60-second foreground poll (07 §2): notifications delta +
 * approvals, plus an offline-queue drain nudge. Started/stopped with
 * MainActivity's lifecycle — never runs in the background.
 */
@Singleton
public class ForegroundPoller {

    private static final long INTERVAL_MS = 60_000L;

    private final NotificationRepository notifications;
    private final ApprovalsRepository approvals;
    private final OfflineQueue offlineQueue;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean running;

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            notifications.refreshAsync();
            approvals.refreshAsync();
            offlineQueue.drainAsync();
            handler.postDelayed(this, INTERVAL_MS);
        }
    };

    @Inject
    public ForegroundPoller(NotificationRepository notifications,
                            ApprovalsRepository approvals,
                            OfflineQueue offlineQueue) {
        this.notifications = notifications;
        this.approvals = approvals;
        this.offlineQueue = offlineQueue;
    }

    public void start() {
        if (running) return;
        running = true;
        handler.post(tick);
    }

    public void stop() {
        running = false;
        handler.removeCallbacks(tick);
    }
}
