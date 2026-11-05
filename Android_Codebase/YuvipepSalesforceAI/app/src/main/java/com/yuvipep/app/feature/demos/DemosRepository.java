package com.yuvipep.app.feature.demos;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.DemoCalendarDto;
import com.yuvipep.app.core.net.dto.DemoDto;
import com.yuvipep.app.core.net.dto.DemoRequests;
import com.yuvipep.app.core.net.dto.DemoTeamDto;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.IOException;
import java.util.List;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Call;
import retrofit2.Response;

/** The /demos router: month calendar, booking, status/reschedule (03 §11). */
@Singleton
public class DemosRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public DemosRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    public void month(@NonNull String yyyyMm, @Nullable String teamId,
                      @NonNull RepoCallback<List<DemoDto>> callback) {
        run(api.demos(yyyyMm, teamId, false), callback);
    }

    public void calendar(int year, int month, @Nullable String teamId,
                         @NonNull RepoCallback<DemoCalendarDto> callback) {
        run(api.demoCalendar(year, month, teamId), callback);
    }

    public void book(@NonNull DemoRequests.Create body,
                     @NonNull RepoCallback<DemoDto> callback) {
        run(api.scheduleDemo(body), callback);
    }

    public void update(@NonNull String demoId, @NonNull DemoRequests.Update body,
                       @NonNull RepoCallback<DemoDto> callback) {
        run(api.updateDemo(demoId, body), callback);
    }

    public void teams(@NonNull RepoCallback<List<DemoTeamDto>> callback) {
        run(api.demoTeams(), callback);
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
