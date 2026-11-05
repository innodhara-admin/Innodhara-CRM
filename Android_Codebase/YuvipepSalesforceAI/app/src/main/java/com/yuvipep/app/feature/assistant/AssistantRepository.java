package com.yuvipep.app.feature.assistant;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.AssistantDtos;
import com.yuvipep.app.core.net.dto.MessageRequests;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.File;
import java.io.IOException;
import java.util.List;
import java.util.Map;

import javax.inject.Inject;
import javax.inject.Singleton;

import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.RequestBody;
import retrofit2.Call;
import retrofit2.Response;

/** /assistant/command, voice mode's HTTP calls, /why and the inline message approve/reject. */
@Singleton
public class AssistantRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public AssistantRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    public void command(@NonNull String text, @Nullable String sessionId,
                        @Nullable String leadId,
                        @Nullable String proposalId, @Nullable String meetingId,
                        @NonNull RepoCallback<AssistantDtos.CommandResponse> callback) {
        run(api.assistantCommand(new AssistantDtos.CommandRequest(
                text, sessionId, leadId, proposalId, meetingId)), callback);
    }

    /** The turns the backend kept for this conversation, oldest first. */
    public void history(@NonNull String sessionId,
                        @NonNull RepoCallback<List<AssistantDtos.Turn>> callback) {
        run(api.assistantHistory(sessionId), callback);
    }

    /** Ask the backend to forget a conversation ("new chat"). */
    public void clearHistory(@NonNull String sessionId,
                             @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.clearAssistantHistory(sessionId), callback);
    }

    /** What voice mode can do on this server right now. */
    public void voiceConfig(@NonNull RepoCallback<AssistantDtos.VoiceConfig> callback) {
        run(api.voiceConfig(), callback);
    }

    /**
     * Voice mode over plain HTTP: one recorded clip in, one answer out. The
     * clip is deleted once the request is over, whatever happened — voice
     * audio is not kept on the phone either.
     */
    public void voiceTurn(@NonNull File clip, @NonNull String sessionId,
                          @Nullable String leadId, @Nullable String proposalId,
                          @Nullable String meetingId, boolean speak, @Nullable String voice,
                          @NonNull RepoCallback<AssistantDtos.VoiceTurnResponse> callback) {
        MultipartBody.Part file = MultipartBody.Part.createFormData("file", clip.getName(),
                RequestBody.create(clip, MediaType.parse("audio/m4a")));
        Call<AssistantDtos.VoiceTurnResponse> call = api.voiceTurn(file,
                form(sessionId), form(leadId), form(proposalId), form(meetingId),
                form(String.valueOf(speak)), form(voice));
        run(call, result -> {
            //noinspection ResultOfMethodCallIgnored
            clip.delete();
            callback.onResult(result);
        });
    }

    /**
     * {@code text} spoken in {@code voice}, as WAV bytes. Samples are small and
     * repeat, so each (voice, text) is kept in the app's cache after the first
     * fetch.
     */
    public void voiceSample(@NonNull File cacheDir, @NonNull String text, @NonNull String voice,
                            @NonNull RepoCallback<byte[]> callback) {
        File dir = new File(cacheDir, "voice_samples");
        File cached = new File(dir, voice + "_" + Integer.toHexString(text.hashCode()) + ".wav");
        executors.io().execute(() -> {
            try {
                if (cached.isFile() && cached.length() > 44) {
                    post(callback, Result.success(java.nio.file.Files.readAllBytes(cached.toPath())));
                    return;
                }
                Response<okhttp3.ResponseBody> response =
                        api.voiceSpeak(new AssistantDtos.SpeakRequest(text, voice)).execute();
                if (!response.isSuccessful() || response.body() == null) {
                    post(callback, Result.error(ErrorMapper.fromResponse(response)));
                    return;
                }
                byte[] wav = response.body().bytes();
                //noinspection ResultOfMethodCallIgnored
                dir.mkdirs();
                java.nio.file.Files.write(cached.toPath(), wav);
                post(callback, Result.success(wav));
            } catch (IOException e) {
                post(callback, Result.error(ErrorMapper.fromThrowable(e)));
            }
        });
    }

    @Nullable
    private static RequestBody form(@Nullable String value) {
        // Retrofit leaves a null part out of the form entirely.
        return value == null ? null : RequestBody.create(value, MediaType.parse("text/plain"));
    }

    public void why(@NonNull String entityType, @NonNull String entityId,
                    @NonNull RepoCallback<AssistantDtos.WhyResponse> callback) {
        run(api.why(entityType, entityId), callback);
    }

    public void approveMessage(@NonNull String messageId, boolean allowBlanks,
                               @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.approveMessage(messageId, allowBlanks), callback);
    }

    public void rejectMessage(@NonNull String messageId, @NonNull String reason,
                              @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.rejectMessage(messageId, new MessageRequests.Reject(reason)), callback);
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
