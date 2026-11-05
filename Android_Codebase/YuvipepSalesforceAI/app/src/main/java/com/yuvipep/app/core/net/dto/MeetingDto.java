package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** GET /meetings/{id} — status + transcript + extracted items. */
public class MeetingDto {

    public String id;
    @SerializedName("lead_id") public String leadId;
    public String status;
    @SerializedName("duration_seconds") public Integer durationSeconds;
    @SerializedName("consent_captured") public boolean consentCaptured;
    @SerializedName("state_suggestion") public String stateSuggestion;
    public String error;
    @SerializedName("started_at") public String startedAt;
    @SerializedName("audio_available") public boolean audioAvailable;

    public Transcript transcript;
    @SerializedName("action_items") public List<Item> actionItems;

    public static class Transcript {
        public String text;
        public String summary;
        public String language;
        public Double confidence;
        @SerializedName("low_confidence") public boolean lowConfidence;
        @SerializedName("word_count") public Integer wordCount;
    }

    public static class Item {
        public String id;
        public String title;
        public String description;
        public String status;
        /** The deadline the meeting agreed on; null when nobody gave one. */
        @SerializedName("due_date") public String dueDate;
    }
}
