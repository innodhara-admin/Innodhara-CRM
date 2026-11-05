package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/**
 * One follow-up from GET /followups. As with demos, the backend's
 * "school" field is the lead's name, rendered generically.
 */
public class FollowUpDto {
    public String id;
    @SerializedName("lead_id") public String leadId;
    @SerializedName("school") @Nullable public String clientName;
    @SerializedName("due_date") public String dueDate;
    public String channel;
    public String status;
    @Nullable public String note;
    @SerializedName("owner_id") @Nullable public String ownerId;
    @SerializedName("completed_at") @Nullable public String completedAt;
}
