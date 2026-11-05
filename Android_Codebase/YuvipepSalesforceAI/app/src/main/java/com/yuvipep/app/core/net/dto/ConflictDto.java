package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/**
 * GET /projects/{id}/conflicts row. The backend does NOT echo source_a/
 * source_b/held_plan_id back on this list (only on the Conflict model) —
 * the resolver reads what's here (description, which the planner writes as
 * full prose of both sides) rather than the two-card mock in 03 §6.
 */
public class ConflictDto {
    public String id;
    public String description;
    public String status;
    @SerializedName("raised_to_user_id") @Nullable public String raisedToUserId;
    @SerializedName("resolution_note") @Nullable public String resolutionNote;
}
