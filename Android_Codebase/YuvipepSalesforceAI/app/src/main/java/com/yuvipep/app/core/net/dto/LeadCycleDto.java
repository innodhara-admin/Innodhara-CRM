package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/**
 * GET /leads/{id}/cycles — one round of business with a client.
 *
 * <p>An empty list is the ordinary answer. Cycles are only written once a
 * client comes back for a second round, so most leads have none and their page
 * looks exactly as it always did. A client on their second round has two rows,
 * which is where the plan's "one card per round" comes from.
 *
 * <p>{@link #ownerId} is null on a round that has just reopened and is waiting
 * for a sales lead to choose someone. That is the question the screen should
 * be asking, not a missing value.
 */
public class LeadCycleDto {
    @SerializedName("id") public String id;
    @SerializedName("cycle_number") public int cycleNumber;
    @SerializedName("owner_id") public String ownerId;
    @SerializedName("owner_name") public String ownerName;
    /** cold_call for the first round, relationship for every later one. */
    @SerializedName("source") public String source;
    @SerializedName("opened_at") public String openedAt;
    @SerializedName("closed_at") public String closedAt;
    /** running | closed | lost_for_now */
    @SerializedName("outcome") public String outcome;
    @SerializedName("project_id") public String projectId;
    @SerializedName("note") public String note;

    public boolean isRunning() { return "running".equals(outcome); }

    public boolean needsOwner() { return isRunning() && ownerId == null; }

    /** POST /leads/{id}/cycles/{n}/owner */
    public static class OwnerRequest {
        @SerializedName("owner_id") public String ownerId;

        public OwnerRequest(String ownerId) {
            this.ownerId = ownerId;
        }
    }
}
