package com.yuvipep.app.feature.leads;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.CardScanResponse;
import com.yuvipep.app.core.net.dto.ContactDto;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.net.dto.LeadDto;
import com.yuvipep.app.core.net.dto.LeadRequests;
import com.yuvipep.app.core.net.dto.OrgUserDto;
import com.yuvipep.app.core.net.dto.RecentlyOpenedDto;
import com.yuvipep.app.core.net.dto.ProjectDto;
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

/** Leads, contacts (incl. card scan), notebook and consent — /leads router. */
@Singleton
public class LeadsRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public LeadsRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    public void list(@Nullable String state, @Nullable String query, boolean mine,
                     boolean important, int limit, int offset,
                     @NonNull RepoCallback<List<LeadDto>> callback) {
        run(api.leads(state, emptyToNull(query), mine, important, limit, offset), callback);
    }

    public void detail(@NonNull String leadId,
                       @NonNull RepoCallback<LeadDetailResponse> callback) {
        run(api.leadDetail(leadId), callback);
    }

    public void create(@NonNull LeadRequests.Create body,
                       @NonNull RepoCallback<LeadDto> callback) {
        run(api.createLead(body), callback);
    }

    /** Sales agents a new lead can be handed to. */
    public void assignableOwners(@NonNull RepoCallback<List<OrgUserDto>> callback) {
        run(api.assignableOwners(), callback);
    }

    /** Leads opened recently enough to still be announced on Home. */
    public void recentlyOpened(@NonNull RepoCallback<List<RecentlyOpenedDto>> callback) {
        run(api.recentlyOpenedLeads(), callback);
    }

    public void update(@NonNull String leadId, @NonNull LeadRequests.Update body,
                       @NonNull RepoCallback<LeadDto> callback) {
        run(api.updateLead(leadId, body), callback);
    }

    public void changeState(@NonNull String leadId, @NonNull String state,
                            @Nullable String reason,
                            @NonNull RepoCallback<LeadDto> callback) {
        run(api.changeLeadState(leadId, new LeadRequests.StateChange(state, reason)),
                callback);
    }

    public void addContact(@NonNull String leadId, @NonNull LeadRequests.Contact body,
                           @NonNull RepoCallback<ContactDto> callback) {
        run(api.addContact(leadId, body), callback);
    }

    public void updateContact(@NonNull String contactId,
                              @NonNull LeadRequests.Contact body,
                              @NonNull RepoCallback<ContactDto> callback) {
        run(api.updateContact(contactId, body), callback);
    }

    public void scanCard(@NonNull String leadId, @NonNull File jpeg,
                         @NonNull RepoCallback<CardScanResponse> callback) {
        RequestBody image = RequestBody.create(jpeg, MediaType.parse("image/jpeg"));
        MultipartBody.Part part =
                MultipartBody.Part.createFormData("file", jpeg.getName(), image);
        RequestBody draftIntro =
                RequestBody.create("true", MediaType.parse("text/plain"));
        run(api.contactFromCard(leadId, part, draftIntro), callback);
    }

    public void addIntelligence(@NonNull String leadId, @NonNull String note,
                                @Nullable String category,
                                @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.addIntelligence(leadId, new LeadRequests.Intelligence(note, category)),
                callback);
    }

    public void recordConsent(@NonNull String leadId, @NonNull String method,
                              @Nullable String note,
                              @NonNull RepoCallback<Map<String, Object>> callback) {
        run(api.recordConsent(leadId, new LeadRequests.Consent(method, note)), callback);
    }

    public void projectsForLead(@NonNull String leadId,
                                @NonNull RepoCallback<List<ProjectDto>> callback) {
        run(api.projects(leadId), callback);
    }

    @Nullable
    private static String emptyToNull(@Nullable String value) {
        return value == null || value.trim().isEmpty() ? null : value.trim();
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
