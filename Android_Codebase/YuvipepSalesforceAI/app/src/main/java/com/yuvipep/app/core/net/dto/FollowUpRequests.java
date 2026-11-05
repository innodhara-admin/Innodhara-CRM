package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/** Request bodies for the /followups routes. */
public final class FollowUpRequests {

    private FollowUpRequests() {
    }

    public static class Complete {
        @SerializedName("sent_message_id") @Nullable public String sentMessageId;
        @Nullable public String note;
        @SerializedName("schedule_next") public boolean scheduleNext = true;
    }
}
