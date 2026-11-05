package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

/** One row of GET /approvals — the facts come from the backend verbatim. */
public class ApprovalDto {
    @SerializedName("id") public String id;
    @SerializedName("entity_type") public String entityType;
    @SerializedName("entity_id") public String entityId;
    @SerializedName("project_id") public String projectId;
    @SerializedName("stage") public String stage;
    @SerializedName("status") public String status;
    @SerializedName("reason") public String reason;
    @SerializedName("recommendation") public String recommendation;
    @SerializedName("joint_with_user_id") public String jointWithUserId;
    @SerializedName("joint_status") public String jointStatus;
    @SerializedName("bundled_entities") public List<Map<String, String>> bundledEntities;
    @SerializedName("expires_at") public String expiresAt;
}
