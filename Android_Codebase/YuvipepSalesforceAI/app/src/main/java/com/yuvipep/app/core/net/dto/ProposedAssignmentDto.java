package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** One row of GET /assignments/proposed (lead_confirm mode). */
public class ProposedAssignmentDto {
    @SerializedName("id") public String id;
    @SerializedName("action_item_id") public String actionItemId;
    @SerializedName("task_title") public String taskTitle;
    @SerializedName("phase") public String phase;
    @SerializedName("to_user_id") public String toUserId;
    @SerializedName("reason") public String reason;
}
