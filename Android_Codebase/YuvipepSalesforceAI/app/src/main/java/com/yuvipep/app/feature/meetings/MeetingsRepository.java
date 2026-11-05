package com.yuvipep.app.feature.meetings;

import androidx.annotation.NonNull;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.MeetingDto;
import com.yuvipep.app.core.net.dto.MeetingNotesRequest;
import com.yuvipep.app.core.net.dto.MeetingNotesResponse;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.IOException;
import java.util.Map;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Call;
import retrofit2.Response;

/**
 * Meeting pipeline reads and the typed-notes path. The audio upload itself
 * lives in {@link UploadMeetingWorker} (WorkManager — survives app death).
 */
@Singleton
public class MeetingsRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public MeetingsRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    public void meeting(@NonNull String meetingId,
                        @NonNull RepoCallback<MeetingDto> callback) {
        run(api.meeting(meetingId), callback);
    }

    public void retry(@NonNull String meetingId,
                      @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.retryMeeting(meetingId), callback);
    }

    public void notes(@NonNull MeetingNotesRequest body,
                      @NonNull RepoCallback<MeetingNotesResponse> callback) {
        run(api.meetingNotes(body), callback);
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
