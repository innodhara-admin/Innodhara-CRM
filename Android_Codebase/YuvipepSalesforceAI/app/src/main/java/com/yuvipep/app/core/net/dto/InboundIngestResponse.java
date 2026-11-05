package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/**
 * What the engines made of a logged reply — shown back verbatim so the person
 * who typed it can see what the system understood and where it went, rather
 * than a "Saved" toast that hides the routing.
 */
public class InboundIngestResponse {
    @SerializedName("id") public String id;
    /** new | processed | needs_human | triage */
    @SerializedName("status") public String status;
    @SerializedName("intent") public String intent;
    @SerializedName("change_type") public String changeType;
    @SerializedName("sentiment") public String sentiment;
    @SerializedName("summary") public String summary;
    @SerializedName("matched_project_id") public String matchedProjectId;
    @SerializedName("needs_human_reason") public String needsHumanReason;
}
