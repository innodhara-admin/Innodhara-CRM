package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/**
 * One row of GET /inbound/triage (unmatched / needs_human inbound).
 *
 * There is deliberately no confidence field: the backend never records one,
 * and a number the model did not produce would be an invention. What the AI
 * actually offers is {@link #intent} (its reading), {@link #reason} (why it
 * stopped) and {@link #summary} — the card shows those three.
 */
public class TriageItemDto {
    @SerializedName("id") public String id;
    @SerializedName("channel") public String channel;
    @SerializedName("from_address") public String fromAddress;
    @SerializedName("subject") public String subject;
    @SerializedName("body") public String body;
    @SerializedName("status") public String status;
    @SerializedName("reason") public String reason;
    @SerializedName("summary") public String summary;
    // Phase 6 additions.
    @SerializedName("intent") public String intent;
    @SerializedName("change_type") public String changeType;
    @SerializedName("matched_lead_id") public String matchedLeadId;
    @SerializedName("matched_project_id") public String matchedProjectId;
    @SerializedName("created_at") public String createdAt;
}
