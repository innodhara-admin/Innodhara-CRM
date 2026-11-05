package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/**
 * Who looks after a client once the selling and delivery are finished
 * — the /leads/{id}/relationship routes.
 *
 * <p>A client has one relationship at a time. Reassignment moves
 * {@link #managerId} on the engagement that already exists rather than
 * starting a second one, so "who looks after this client" stays a question
 * with one answer rather than a history to read.
 */
public class RelationshipDto {

    /**
     * GET /leads/{id}/relationship — the client page.
     *
     * <p>{@link #engagement} is null for most clients and that is the ordinary
     * answer, not a missing record. Everything else is present either way, so
     * a caller needs one code path rather than two.
     */
    public static class Envelope {
        @SerializedName("engagement") public RelationshipDto engagement;
        /** Everything we know, assembled by the backend's `replay_story`. */
        @SerializedName("story") public String story;
        /** How to approach them — the notes the org has accumulated. */
        @SerializedName("intelligence") public java.util.List<Note> intelligence;
        @SerializedName("last_touch_at") public String lastTouchAt;
        @SerializedName("days_quiet") public Integer daysQuiet;
        @SerializedName("next_touch_date") public String nextTouchDate;
        @SerializedName("next_touch_note") public String nextTouchNote;
    }

    /** One accumulated note about a client. */
    public static class Note {
        @SerializedName("note") public String note;
        @SerializedName("category") public String category;
        @SerializedName("source") public String source;
        @SerializedName("at") public String at;
    }

    /** GET /relationship-managers — a row in the "choose myself" picker. */
    public static class Manager {
        @SerializedName("id") public String id;
        @SerializedName("name") public String name;
        @SerializedName("email") public String email;
        @SerializedName("designation") public String designation;
    }

    /** POST body for accepting or dismissing an opportunity. */
    public static class OpportunityDecision {
        @SerializedName("note") public String note;

        public OpportunityDecision(String note) {
            this.note = note;
        }
    }

    /** POST body. A null managerId means "let the assistant choose". */
    public static class HandoverRequest {
        @SerializedName("manager_id") public String managerId;

        public HandoverRequest(String managerId) {
            this.managerId = managerId;
        }
    }

    public static class ReassignRequest {
        @SerializedName("manager_id") public String managerId;
        @SerializedName("reason") public String reason;

        public ReassignRequest(String managerId, String reason) {
            this.managerId = managerId;
            this.reason = reason;
        }
    }

    @SerializedName("id") public String id;
    @SerializedName("lead_id") public String leadId;
    @SerializedName("manager_id") public String managerId;
    @SerializedName("manager_name") public String managerName;
    @SerializedName("assigned_by") public String assignedBy;
    @SerializedName("assigned_by_name") public String assignedByName;
    /** Why this person — what the "Why this person?" sheet shows. */
    @SerializedName("reason") public String reason;
    /** True when a human picked instead of taking the assistant's choice. */
    @SerializedName("overridden") public boolean overridden;
    /** active | ended | returned_to_sales */
    @SerializedName("status") public String status;
    @SerializedName("started_at") public String startedAt;
    @SerializedName("ended_at") public String endedAt;
    @SerializedName("ended_reason") public String endedReason;
    /** "They might be ready to buy again" — status is "none" for almost
     *  every engagement, which is the ordinary answer. */
    @SerializedName("opportunity") public Opportunity opportunity;

    /**
     * A hint that the client wants to buy again, waiting for a person.
     *
     * <p>{@link #quote} is the client's own words, not a paraphrase. It is on
     * the card because someone is being asked to decide, and "the AI thinks
     * so" is not evidence — what they actually said is.
     */
    public static class Opportunity {
        /** none | open | accepted | dismissed */
        @SerializedName("status") public String status;
        @SerializedName("reason") public String reason;
        @SerializedName("quote") public String quote;
        @SerializedName("meeting_id") public String meetingId;
        @SerializedName("at") public String at;
        @SerializedName("decided_by_name") public String decidedByName;
        @SerializedName("decided_at") public String decidedAt;

        public boolean isOpen() { return "open".equals(status); }
    }
}
