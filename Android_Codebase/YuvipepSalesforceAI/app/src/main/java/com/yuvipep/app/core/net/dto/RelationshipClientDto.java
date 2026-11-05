package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/**
 * GET /relationships/mine — one client a relationship manager looks after.
 *
 * <p>The server returns these worst-neglected first, so the screen renders
 * them in the order it receives them and does no sorting of its own. A client
 * nobody has ever spoken to comes first of all: {@link #daysQuiet} is null
 * there, which is the worst case rather than a missing value, and
 * {@link #isQuiet} is already true for it so no screen has to know that rule.
 */
public class RelationshipClientDto {
    @SerializedName("engagement_id") public String engagementId;
    @SerializedName("lead_id") public String leadId;
    @SerializedName("lead_name") public String leadName;
    @SerializedName("city") public String city;
    @SerializedName("started_at") public String startedAt;
    /** ISO-8601 UTC, or null when nobody has ever met them. */
    @SerializedName("last_touch_at") public String lastTouchAt;
    /** Null means never spoken to — not "unknown". */
    @SerializedName("days_quiet") public Integer daysQuiet;
    @SerializedName("is_quiet") public boolean isQuiet;
    /** The next planned conversation, whoever booked it. */
    @SerializedName("next_touch_date") public String nextTouchDate;
    @SerializedName("next_touch_note") public String nextTouchNote;
    @SerializedName("next_touch_overdue") public boolean nextTouchOverdue;
    /** A client hinting they want to buy again is the most time-sensitive
     *  thing on this screen, so it outranks the quiet badge. */
    @SerializedName("opportunity_open") public boolean opportunityOpen;
    @SerializedName("opportunity_reason") public String opportunityReason;
}
