package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/** GET /projects/{id}/timeline row — one humanised progress_events entry. */
public class TimelineEventDto {
    public String at;
    public String event;
    @SerializedName("entity_type") @Nullable public String entityType;
    @SerializedName("entity_id") @Nullable public String entityId;
    @Nullable public String actor;
    @Nullable public Object details;
}
