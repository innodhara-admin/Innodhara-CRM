package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/** Request bodies for the /demos routes. */
public final class DemoRequests {

    private DemoRequests() {
    }

    public static class Create {
        @SerializedName("lead_id") public final String leadId;
        @SerializedName("scheduled_date") public final String scheduledDate;
        @SerializedName("scheduled_time") @Nullable public final String scheduledTime;
        @SerializedName("team_id") @Nullable public final String teamId;
        @Nullable public final String notes;

        public Create(String leadId, String scheduledDate, @Nullable String scheduledTime,
                      @Nullable String teamId, @Nullable String notes) {
            this.leadId = leadId;
            this.scheduledDate = scheduledDate;
            this.scheduledTime = scheduledTime;
            this.teamId = teamId;
            this.notes = notes;
        }
    }

    /** PATCH /demos/{id} — every field optional; null = leave unchanged. */
    public static class Update {
        @SerializedName("scheduled_date") @Nullable public String scheduledDate;
        @SerializedName("scheduled_time") @Nullable public String scheduledTime;
        @SerializedName("team_id") @Nullable public String teamId;
        @Nullable public String status;
        @Nullable public String notes;
    }
}
