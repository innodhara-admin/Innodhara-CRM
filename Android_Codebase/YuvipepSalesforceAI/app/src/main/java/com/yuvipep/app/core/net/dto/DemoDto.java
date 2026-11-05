package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/**
 * One demo, as /demos returns it. The backend names the client field
 * "school" for legacy reasons — it is the lead's name and rendered
 * generically as the client (README law 2).
 */
public class DemoDto {
    public String id;
    @SerializedName("lead_id") public String leadId;
    @SerializedName("school") @Nullable public String clientName;
    @SerializedName("team_id") @Nullable public String teamId;
    @Nullable public String team;
    public String date;
    @Nullable public String time;
    public String status;
    @Nullable public String notes;

    // Only on POST /demos and PATCH /demos/{id} responses:
    @SerializedName("invite_message_id") @Nullable public String inviteMessageId;
    @SerializedName("invite_note") @Nullable public String inviteNote;
    @Nullable public String warning;
}
