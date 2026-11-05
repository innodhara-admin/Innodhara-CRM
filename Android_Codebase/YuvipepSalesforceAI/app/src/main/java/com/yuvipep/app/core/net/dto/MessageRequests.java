package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

import java.util.Map;

/** Request bodies for the /messages routes. */
public final class MessageRequests {

    private MessageRequests() {
    }

    public static class Reject {
        @SerializedName("reason") public String reason;

        public Reject(String reason) {
            this.reason = reason;
        }
    }

    /** POST /messages/draft — the manual "ask for a client message" path
     * (03 §6 project home "Draft message" quick action); still approval-
     * gated like every other outward message. */
    public static class Draft {
        @SerializedName("contact_id") public String contactId;
        public String kind = "follow_up";
        public String purpose = "manual message";
        @SerializedName("project_id") @Nullable public String projectId;
        @Nullable public String channel;
        @Nullable public String subject;
        @Nullable public String instruction;
        public Map<String, Object> facts = java.util.Collections.emptyMap();
        public boolean urgent;
    }
}
