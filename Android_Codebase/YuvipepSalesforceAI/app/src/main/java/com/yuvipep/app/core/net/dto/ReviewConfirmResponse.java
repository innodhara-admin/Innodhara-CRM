package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

public class ReviewConfirmResponse {
    @SerializedName("confirmed") public boolean confirmed;
    @SerializedName("action_items_saved") public int actionItemsSaved;
    /**
     * The backend handed this meeting to the Planner (a project, a plan and
     * its assignments are being worked out in the background). Absent on
     * backends older than the F9 fix, where it stays false and the toast
     * simply says nothing about planning rather than claiming it happened.
     */
    @SerializedName("planning") public boolean planning;
}
