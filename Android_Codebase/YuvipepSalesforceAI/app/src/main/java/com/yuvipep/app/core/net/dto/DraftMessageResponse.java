package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** POST /messages/draft response — held-or-drafted, honestly either way. */
public class DraftMessageResponse {
    @Nullable public Boolean held;
    @Nullable public String reason;
    @SerializedName("message_id") @Nullable public String messageId;
    @SerializedName("approval_id") @Nullable public String approvalId;
    @Nullable public String status;
    @Nullable public String body;
    @SerializedName("uncovered_points") @Nullable public List<String> uncoveredPoints;
}
