package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/** GET /projects/{id}/plans row — one ActionPlan version. */
public class PlanVersionDto {
    public String id;
    public int version;
    public String status;
    @Nullable public String summary;
    @Nullable public String trigger;
    @SerializedName("changes_from_previous") @Nullable public Object changesFromPrevious;
    @SerializedName("approved_by") @Nullable public String approvedBy;
    @SerializedName("approved_at") @Nullable public String approvedAt;
}
