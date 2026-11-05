package com.yuvipep.app.feature.meetings;

import android.app.NotificationManager;
import android.content.Context;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;
import androidx.work.Constraints;
import androidx.work.Data;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import com.yuvipep.app.R;
import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.MeetingDto;
import com.yuvipep.app.feature.notifications.NotificationChannels;

import java.io.File;
import java.io.IOException;
import java.util.UUID;

import dagger.hilt.EntryPoint;
import dagger.hilt.InstallIn;
import dagger.hilt.android.EntryPointAccessors;
import dagger.hilt.components.SingletonComponent;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.RequestBody;
import retrofit2.Response;

/**
 * Uploads a finished recording to /meetings/upload (08 §1). Network loss →
 * WorkManager retry with the SAME idempotency key (minted at enqueue), so
 * the backend can never process the meeting twice. A backend refusal is
 * terminal and surfaces its message verbatim (screen + notification).
 * The local file is deleted only after the server has the audio.
 */
public class UploadMeetingWorker extends Worker {

    public static final String KEY_FILE = "file";
    public static final String KEY_LEAD = "lead_id";
    public static final String KEY_TITLE = "title";
    public static final String KEY_DURATION = "duration_seconds";
    public static final String KEY_IDEMPOTENCY = "idempotency";
    /** Optional. Null/absent means the old behaviour: a sales meeting. */
    public static final String KEY_MEETING_TYPE = "meeting_type";
    /** Optional. Absent means a live recording, which is always audio/mp4. */
    public static final String KEY_MIME = "mime";
    public static final String OUT_MEETING_ID = "meeting_id";
    public static final String OUT_ERROR = "error";

    private static final int NOTIFICATION_ID = 42;

    @EntryPoint
    @InstallIn(SingletonComponent.class)
    public interface Deps {
        ApiService api();
    }

    public UploadMeetingWorker(@NonNull Context context,
                               @NonNull WorkerParameters params) {
        super(context, params);
    }

    /** Enqueues the upload and returns the work id for progress tracking. */
    public static UUID enqueue(@NonNull Context context, @NonNull String filePath,
                               @NonNull String leadId, @NonNull String title,
                               long durationSeconds,
                               @Nullable String meetingType) {
        return enqueue(context, filePath, leadId, title, durationSeconds, meetingType, null);
    }

    /**
     * Same, for a file chosen from the phone: {@code mime} is its real type
     * and {@code durationSeconds} may be 0 when the length could not be read,
     * in which case the field is left out (the server accepts that).
     */
    public static UUID enqueue(@NonNull Context context, @NonNull String filePath,
                               @NonNull String leadId, @NonNull String title,
                               long durationSeconds,
                               @Nullable String meetingType,
                               @Nullable String mime) {
        Data input = new Data.Builder()
                .putString(KEY_FILE, filePath)
                .putString(KEY_LEAD, leadId)
                .putString(KEY_TITLE, title)
                .putLong(KEY_DURATION, durationSeconds)
                .putString(KEY_IDEMPOTENCY, UUID.randomUUID().toString())
                .putString(KEY_MEETING_TYPE, meetingType)
                .putString(KEY_MIME, mime)
                .build();
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(
                UploadMeetingWorker.class)
                .setInputData(input)
                .setConstraints(new Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build())
                .build();
        WorkManager.getInstance(context).enqueue(request);
        return request.getId();
    }

    @NonNull
    @Override
    public Result doWork() {
        String path = getInputData().getString(KEY_FILE);
        String leadId = getInputData().getString(KEY_LEAD);
        if (path == null || leadId == null) {
            return Result.failure(error("Missing upload input"));
        }
        File file = new File(path);
        if (!file.exists()) {
            return Result.failure(error("Recording file is gone from disk"));
        }
        notifyProgress();

        ApiService api = EntryPointAccessors
                .fromApplication(getApplicationContext(), Deps.class).api();
        String mime = getInputData().getString(KEY_MIME);
        MultipartBody.Part part = MultipartBody.Part.createFormData(
                "file", file.getName(),
                RequestBody.create(file, MediaType.parse(mime == null ? "audio/mp4" : mime)));
        long duration = getInputData().getLong(KEY_DURATION, 0);
        String title = getInputData().getString(KEY_TITLE);
        String meetingType = getInputData().getString(KEY_MEETING_TYPE);
        try {
            Response<MeetingDto> response = api.uploadMeeting(
                    part,
                    plain(leadId),
                    plain("true"),
                    duration > 0 ? plain(String.valueOf(duration)) : null,
                    plain(title == null ? "" : title),
                    // Left null for every ordinary recording, so the request is
                    // byte-for-byte the one the server has always handled.
                    meetingType == null ? null : plain(meetingType),
                    getInputData().getString(KEY_IDEMPOTENCY)).execute();
            if (response.isSuccessful() && response.body() != null) {
                //noinspection ResultOfMethodCallIgnored
                file.delete();
                notifyDone(true, null);
                return Result.success(new Data.Builder()
                        .putString(OUT_MEETING_ID, response.body().id)
                        .build());
            }
            String message = ErrorMapper.fromResponse(response).message;
            notifyDone(false, message);
            return Result.failure(error(message));
        } catch (IOException e) {
            // Connectivity — retry later with the same key; the file stays.
            return Result.retry();
        }
    }

    private static RequestBody plain(@NonNull String value) {
        return RequestBody.create(value, MediaType.parse("text/plain"));
    }

    private static Data error(@NonNull String message) {
        return new Data.Builder().putString(OUT_ERROR, message).build();
    }

    private void notifyProgress() {
        NotificationManager manager = getApplicationContext()
                .getSystemService(NotificationManager.class);
        if (manager == null) return;
        manager.notify(NOTIFICATION_ID, new NotificationCompat.Builder(
                getApplicationContext(), NotificationChannels.UPLOADS)
                .setSmallIcon(R.drawable.ic_tab_mic)
                .setContentTitle(getApplicationContext()
                        .getString(R.string.upload_notification_uploading))
                .setProgress(0, 0, true)
                .setOngoing(true)
                .build());
    }

    private void notifyDone(boolean success, String message) {
        NotificationManager manager = getApplicationContext()
                .getSystemService(NotificationManager.class);
        if (manager == null) return;
        if (success) {
            manager.cancel(NOTIFICATION_ID);
            return;
        }
        manager.notify(NOTIFICATION_ID, new NotificationCompat.Builder(
                getApplicationContext(), NotificationChannels.UPLOADS)
                .setSmallIcon(R.drawable.ic_tab_mic)
                .setContentTitle(getApplicationContext()
                        .getString(R.string.upload_notification_failed))
                .setContentText(message)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(message))
                .setAutoCancel(true)
                .build());
    }
}
