package com.yuvipep.app.core.net;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import dagger.hilt.EntryPoint;
import dagger.hilt.InstallIn;
import dagger.hilt.android.EntryPointAccessors;
import dagger.hilt.components.SingletonComponent;

/**
 * Drains the OfflineQueue when connectivity returns. Plain Worker +
 * Hilt EntryPoint (no androidx.hilt extension needed for Java).
 */
public class QueueDrainWorker extends Worker {

    @EntryPoint
    @InstallIn(SingletonComponent.class)
    public interface Deps {
        OfflineQueue offlineQueue();
    }

    public QueueDrainWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        OfflineQueue queue = EntryPointAccessors
                .fromApplication(getApplicationContext(), Deps.class)
                .offlineQueue();
        return queue.drainBlocking() ? Result.success() : Result.retry();
    }
}
