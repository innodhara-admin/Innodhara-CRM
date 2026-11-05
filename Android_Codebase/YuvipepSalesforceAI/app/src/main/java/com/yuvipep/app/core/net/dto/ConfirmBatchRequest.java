package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

/** POST /assignments/confirm-batch body. Overrides: assignment_id → user_id. */
public class ConfirmBatchRequest {
    @SerializedName("assignment_ids") public List<String> assignmentIds;
    @SerializedName("overrides") public Map<String, String> overrides;

    public ConfirmBatchRequest(List<String> assignmentIds, Map<String, String> overrides) {
        this.assignmentIds = assignmentIds;
        this.overrides = overrides;
    }
}
