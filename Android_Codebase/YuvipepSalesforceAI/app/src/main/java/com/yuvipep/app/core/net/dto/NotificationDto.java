package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** One row of GET /notifications. */
public class NotificationDto {
    @SerializedName("id") public String id;
    @SerializedName("title") public String title;
    @SerializedName("body") public String body;
    @SerializedName("kind") public String kind;
    @SerializedName("entity_type") public String entityType;
    @SerializedName("entity_id") public String entityId;
    @SerializedName("is_read") public boolean isRead;
    @SerializedName("created_at") public String createdAt;
}
