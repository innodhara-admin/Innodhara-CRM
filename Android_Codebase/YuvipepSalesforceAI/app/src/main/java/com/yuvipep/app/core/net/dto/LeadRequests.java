package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** Request bodies for the /leads router — grouped, they are tiny. */
public final class LeadRequests {

    private LeadRequests() {
    }

    public static class Create {
        public String name;
        public String address;
        public String city;
        public String region;
        public String website;
        public String source;
        public String notes;
        /** The sales agent who will cold call this lead. Null = the creator. */
        @SerializedName("owner_id") public String ownerId;
    }

    public static class Update {
        public String name;
        public String address;
        public String city;
        public String region;
        public String website;
        public String notes;
        @SerializedName("is_important") public Boolean isImportant;
    }

    public static class StateChange {
        public String state;
        public String reason;

        public StateChange(String state, String reason) {
            this.state = state;
            this.reason = reason;
        }
    }

    public static class Contact {
        public String name;
        public String title;
        public String email;
        public String phone;
        @SerializedName("is_primary") public boolean isPrimary;
    }

    public static class Intelligence {
        public String note;
        public String category;
        public String source = "typed";

        public Intelligence(String note, String category) {
            this.note = note;
            this.category = category;
        }
    }

    public static class Consent {
        public String method;
        public String note;
        @SerializedName("meeting_id") public String meetingId;

        public Consent(String method, String note) {
            this.method = method;
            this.note = note;
        }
    }
}
