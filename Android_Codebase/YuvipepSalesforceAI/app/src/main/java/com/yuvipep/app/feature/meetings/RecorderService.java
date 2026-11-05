package com.yuvipep.app.feature.meetings;

import android.app.Notification;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;

import java.io.File;
import java.io.IOException;

/**
 * Foreground meeting recorder (08 §1): AAC .m4a, 44.1kHz mono 96kbps,
 * pause/resume, elapsed + amplitude published via LiveData; the persistent
 * notification satisfies mic-use compliance and keeps recording alive with
 * the screen off. The file stays app-private until the upload worker
 * confirms, then is deleted.
 */
public class RecorderService extends Service {

    public static final String ACTION_START = "start";
    public static final String ACTION_PAUSE = "pause";
    public static final String ACTION_RESUME = "resume";
    public static final String ACTION_STOP = "stop";
    public static final String EXTRA_LEAD_NAME = "lead_name";

    public static final String CHANNEL_RECORDING = "recording";
    private static final int NOTIFICATION_ID = 41;

    /** IDLE → RECORDING ⇄ PAUSED → STOPPED (file ready). */
    public enum Status { IDLE, RECORDING, PAUSED, STOPPED }

    /** Immutable snapshot for the UI. */
    public static class State {
        public final Status status;
        public final long elapsedMs;
        public final int amplitude;
        @Nullable public final String filePath;

        State(Status status, long elapsedMs, int amplitude, @Nullable String filePath) {
            this.status = status;
            this.elapsedMs = elapsedMs;
            this.amplitude = amplitude;
            this.filePath = filePath;
        }
    }

    private static final MutableLiveData<State> STATE =
            new MutableLiveData<>(new State(Status.IDLE, 0, 0, null));

    public static LiveData<State> state() {
        return STATE;
    }

    /** Clears a finished session (after upload was queued or discarded). */
    public static void resetState() {
        STATE.postValue(new State(Status.IDLE, 0, 0, null));
    }

    private MediaRecorder recorder;
    private File outputFile;
    private long startedAt;
    private long pausedTotal;
    private long pauseStartedAt;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            publish();
            handler.postDelayed(this, 400);
        }
    };

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_START.equals(action)) {
            start(intent.getStringExtra(EXTRA_LEAD_NAME));
        } else if (ACTION_PAUSE.equals(action)) {
            pause();
        } else if (ACTION_RESUME.equals(action)) {
            resume();
        } else if (ACTION_STOP.equals(action)) {
            stop();
        }
        return START_NOT_STICKY;
    }

    private void start(@Nullable String leadName) {
        if (recorder != null) return;
        File dir = new File(getFilesDir(), "recordings");
        if (!dir.exists() && !dir.mkdirs()) {
            fail("Could not create recordings directory");
            return;
        }
        outputFile = new File(dir,
                "meeting_" + System.currentTimeMillis() + ".m4a");
        recorder = new MediaRecorder();
        try {
            recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            recorder.setAudioSamplingRate(44100);
            recorder.setAudioChannels(1);
            recorder.setAudioEncodingBitRate(96000);
            recorder.setOutputFile(outputFile.getAbsolutePath());
            recorder.prepare();
            recorder.start();
        } catch (IOException | RuntimeException e) {
            release();
            fail(e.getMessage() == null ? "Recorder failed to start" : e.getMessage());
            return;
        }
        startedAt = SystemClock.elapsedRealtime();
        pausedTotal = 0;

        Notification notification = buildNotification(leadName);
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
        handler.post(ticker);
        publish();
    }

    private void pause() {
        if (recorder == null || current().status != Status.RECORDING) return;
        recorder.pause();
        pauseStartedAt = SystemClock.elapsedRealtime();
        STATE.postValue(new State(Status.PAUSED, elapsed(), 0, null));
    }

    private void resume() {
        if (recorder == null || current().status != Status.PAUSED) return;
        recorder.resume();
        pausedTotal += SystemClock.elapsedRealtime() - pauseStartedAt;
        // Finding F39 — the most serious defect of Round 7.
        //
        // This used to call publish(), which early-returns while the status is
        // PAUSED — and PAUSED is exactly what it always is at this moment. So
        // the state never left PAUSED, the ticker (which also goes through
        // publish()) early-returned on every subsequent tick, and the screen
        // stayed frozen on "Paused" for the rest of the session — while
        // recorder.resume() above had ALREADY restarted the microphone.
        //
        // Observed on the device: the file grew ~12 KB/s for the whole "paused"
        // period, and stop() then reported "Recorded 00:26" for three minutes of
        // audio. On a screen whose entire purpose is DPDP consent, the app was
        // telling everyone in the room something false.
        //
        // Post RECORDING directly, and compute the elapsed time INLINE rather
        // than calling elapsed(): elapsed() branches on current().status, and
        // postValue() is asynchronous, so current() can still read PAUSED here —
        // which would republish the frozen value and re-freeze the timer.
        long resumedElapsed = SystemClock.elapsedRealtime() - startedAt - pausedTotal;
        STATE.postValue(new State(Status.RECORDING, resumedElapsed, 0, null));
    }

    private void stop() {
        if (recorder == null) return;
        long elapsed = elapsed();
        try {
            recorder.stop();
        } catch (RuntimeException e) {
            // Stop before any audio was written — treat as a failed session.
            release();
            if (outputFile != null) //noinspection ResultOfMethodCallIgnored
                outputFile.delete();
            fail("Nothing was recorded");
            return;
        }
        release();
        STATE.postValue(new State(Status.STOPPED, elapsed, 0,
                outputFile.getAbsolutePath()));
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private void fail(String message) {
        STATE.postValue(new State(Status.IDLE, 0, 0, null));
        handler.removeCallbacks(ticker);
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
        android.widget.Toast.makeText(this, message,
                android.widget.Toast.LENGTH_LONG).show();
    }

    private void release() {
        handler.removeCallbacks(ticker);
        if (recorder != null) {
            recorder.release();
            recorder = null;
        }
    }

    private State current() {
        State state = STATE.getValue();
        return state == null ? new State(Status.IDLE, 0, 0, null) : state;
    }

    private long elapsed() {
        State state = current();
        if (state.status == Status.PAUSED) return state.elapsedMs;
        return SystemClock.elapsedRealtime() - startedAt - pausedTotal;
    }

    private void publish() {
        if (recorder == null) return;
        if (current().status == Status.PAUSED) return;
        int amplitude;
        try {
            amplitude = recorder.getMaxAmplitude();
        } catch (RuntimeException e) {
            amplitude = 0;
        }
        STATE.postValue(new State(Status.RECORDING, elapsed(), amplitude, null));
    }

    private Notification buildNotification(@Nullable String leadName) {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent tap = PendingIntent.getActivity(this, 40, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new NotificationCompat.Builder(this, CHANNEL_RECORDING)
                .setSmallIcon(R.drawable.ic_tab_mic)
                .setContentTitle(getString(R.string.recording_notification_title))
                .setContentText(leadName == null || leadName.isEmpty()
                        ? getString(R.string.recording_notification_body)
                        : leadName)
                .setOngoing(true)
                .setContentIntent(tap)
                .build();
    }

    public static void send(Context context, String action) {
        Intent intent = new Intent(context, RecorderService.class);
        intent.setAction(action);
        context.startService(intent);
    }

    public static void startRecording(Context context, String leadName) {
        Intent intent = new Intent(context, RecorderService.class);
        intent.setAction(ACTION_START);
        intent.putExtra(EXTRA_LEAD_NAME, leadName);
        androidx.core.content.ContextCompat.startForegroundService(context, intent);
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        // Killed mid-recording: keep whatever audio made it to disk honest —
        // the recorder screen will offer the file if it is playable.
        release();
        super.onDestroy();
    }
}
