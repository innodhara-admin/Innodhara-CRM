package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/**
 * GET /action-items/waiting-on-me — open tasks blocked on the caller
 * (customer ask, 21 Sep 2026: "blocked, waiting on Siva" must reach Siva).
 * Cleared server-side the moment the task is unblocked.
 */
public class WaitingOnMeDto {
    @Nullable public List<Item> items;

    public static class Item {
        public String id;
        public String title;
        @SerializedName("blocked_reason") @Nullable public String blockedReason;
        /** The person whose task is blocked — the one waiting. */
        @SerializedName("waiting_user_id") @Nullable public String waitingUserId;
        @SerializedName("waiting_user_name") @Nullable public String waitingUserName;
        @SerializedName("lead_id") @Nullable public String leadId;
        @Nullable public String school;
        @SerializedName("project_id") @Nullable public String projectId;
        @SerializedName("project_name") @Nullable public String projectName;
        @SerializedName("due_date") @Nullable public String dueDate;
    }
}
