package com.yuvipep.app.feature.relationships;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.dto.RelationshipDto;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.IOException;
import java.util.List;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Call;
import retrofit2.Response;

/**
 * Who looks after a client once the selling stops — the /relationship routes.
 *
 * <p>Kept apart from {@link com.yuvipep.app.feature.leads.LeadsRepository}
 * because these calls belong to the relationship side of the product and the
 * relationship manager's own screens will use them without touching the lead
 * pipeline at all.
 */
@Singleton
public class RelationshipRepository {

    private final ApiService api;
    private final AppExecutors executors;

    @Inject
    public RelationshipRepository(ApiService api, AppExecutors executors) {
        this.api = api;
        this.executors = executors;
    }

    /**
     * The relationship manager's Home.
     *
     * <p>Returned worst-neglected first by the server. Callers render in the
     * order received — re-sorting here would silently undo the one thing the
     * screen is for.
     */
    public void myClients(
            @NonNull RepoCallback<List<com.yuvipep.app.core.net.dto.RelationshipClientDto>> cb) {
        run(api.myRelationshipClients(), cb);
    }

    /** Everyone who could look after a client, for the manual picker. */
    public void managers(@NonNull RepoCallback<List<RelationshipDto.Manager>> cb) {
        run(api.relationshipManagers(), cb);
    }

    /**
     * Hand a closed client over.
     *
     * @param managerId null to let the assistant choose, which is the usual
     *                  path; a specific id when a person has overruled it.
     */
    public void handOver(@NonNull String leadId, @Nullable String managerId,
                         @NonNull RepoCallback<RelationshipDto> cb) {
        run(api.handToRelationshipManager(
                leadId, new RelationshipDto.HandoverRequest(managerId)), cb);
    }

    /** Correct a bad pick without starting a second engagement. */
    public void reassign(@NonNull String leadId, @NonNull String managerId,
                         @Nullable String reason,
                         @NonNull RepoCallback<RelationshipDto> cb) {
        run(api.reassignRelationshipManager(
                leadId, new RelationshipDto.ReassignRequest(managerId, reason)), cb);
    }

    /**
     * The manager agrees the client wants to buy again.
     *
     * <p>Tells every sales lead. Does NOT move the lead — `closed -> open`
     * and the new sales cycle are still to come, and the server says so in
     * its `lead_state` field rather than implying otherwise.
     */
    public void acceptOpportunity(@NonNull String leadId, @Nullable String note,
                                  @NonNull RepoCallback<java.util.Map<String, Object>> cb) {
        run(api.acceptOpportunity(
                leadId, new RelationshipDto.OpportunityDecision(note)), cb);
    }

    /** It was politeness, not interest. Recorded rather than deleted. */
    public void dismissOpportunity(@NonNull String leadId, @Nullable String note,
                                   @NonNull RepoCallback<java.util.Map<String, Object>> cb) {
        run(api.dismissOpportunity(
                leadId, new RelationshipDto.OpportunityDecision(note)), cb);
    }

    /** Rounds of business with this client. Empty for almost every lead. */
    public void cycles(@NonNull String leadId,
                       @NonNull RepoCallback<List<com.yuvipep.app.core.net.dto.LeadCycleDto>> cb) {
        run(api.leadCycles(leadId), cb);
    }

    /** Give the newly reopened round to someone. Sales lead or admin only —
     *  the server enforces it; this just asks. */
    public void setCycleOwner(
            @NonNull String leadId, int cycleNumber, @NonNull String ownerId,
            @NonNull RepoCallback<com.yuvipep.app.core.net.dto.LeadCycleDto> cb) {
        run(api.setCycleOwner(leadId, cycleNumber,
                new com.yuvipep.app.core.net.dto.LeadCycleDto.OwnerRequest(ownerId)),
                cb);
    }

    /** `engagement` is null for every client nobody looks after — most. */
    public void forLead(@NonNull String leadId,
                        @NonNull RepoCallback<RelationshipDto.Envelope> cb) {
        run(api.relationshipFor(leadId), cb);
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
