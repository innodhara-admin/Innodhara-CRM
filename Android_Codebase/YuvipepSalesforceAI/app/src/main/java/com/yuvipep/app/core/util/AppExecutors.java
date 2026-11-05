package com.yuvipep.app.core.util;

import android.os.Handler;
import android.os.Looper;

import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

import javax.inject.Inject;
import javax.inject.Singleton;

/** io / db / main executors — no raw threads in features (02 §6). */
@Singleton
public class AppExecutors {

    private final Executor io = Executors.newFixedThreadPool(3);
    private final Executor db = Executors.newSingleThreadExecutor();
    private final Executor main = new Executor() {
        private final Handler handler = new Handler(Looper.getMainLooper());

        @Override
        public void execute(Runnable command) {
            handler.post(command);
        }
    };

    @Inject
    public AppExecutors() {
    }

    public Executor io() { return io; }
    public Executor db() { return db; }
    public Executor main() { return main; }
}
