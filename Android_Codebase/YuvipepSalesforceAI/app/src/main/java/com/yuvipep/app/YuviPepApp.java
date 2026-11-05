package com.yuvipep.app;

import android.app.Application;

import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import com.yuvipep.app.feature.notifications.NotificationChannels;
import com.yuvipep.app.feature.notifications.NotificationPollWorker;

import java.time.Duration;

import dagger.hilt.android.HiltAndroidApp;

/** Application entry point — Hilt root. */
@HiltAndroidApp
public class YuviPepApp extends Application {

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationChannels.createAll(this);
        schedulePolling();
    }

    /**
     * The 15-minute background poll (07 §2) that carries notifications until
     * FCM lights up in Phase 8. The worker no-ops when signed out.
     */
    private void schedulePolling() {
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(
                NotificationPollWorker.class, Duration.ofMinutes(15))
                .setConstraints(new Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build())
                .build();
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
                NotificationPollWorker.WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP, request);
    }
}
