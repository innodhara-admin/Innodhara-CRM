package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** GET /meetings/{id}/review — extracted items awaiting the human gate. */
public class MeetingReviewResponse {
    @SerializedName("meeting_status") public String meetingStatus;
    @SerializedName("items") public List<Item> items;

    public static class Item {
        @SerializedName("id") public String id;
        @SerializedName("title") public String title;
        @SerializedName("description") public String description;
        // F24: the lead's existing open task this item looks like (from an
        // earlier meeting or added by hand), or null. Advisory — the human
        // drops the twin with the existing keep/drop control.
        @SerializedName("possible_duplicate_of") public Duplicate possibleDuplicateOf;
    }

    public static class Duplicate {
        @SerializedName("id") public String id;
        @SerializedName("title") public String title;
        @SerializedName("at") public String at;   // e.g. "14 Jul", may be null
    }
}
