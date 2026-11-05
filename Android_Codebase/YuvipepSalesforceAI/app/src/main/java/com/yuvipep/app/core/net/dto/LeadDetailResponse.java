package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** GET /leads/{id} — the lead plus every related collection. */
public class LeadDetailResponse extends LeadDto {

    public List<ContactDto> contacts;
    @SerializedName("action_items") public List<ActionItemRow> actionItems;
    public List<MeetingRow> meetings;
    public List<ProposalRow> proposals;
    /**
     * Contracts, and they are a SEPARATE list on purpose. An MOU is signed
     * after a proposal is accepted, so one merged into {@link #proposals}
     * would arrive on an already-closed deal -- the backend keeps them in
     * different tables and sends them under different keys, and reading them
     * into one list here would undo that on the way in.
     */
    public List<MouRow> mous;
    public List<FollowupRow> followups;
    public List<IntelligenceRow> intelligence;
    @SerializedName("state_history") public List<HistoryRow> stateHistory;
    /** Resolved from owner_id by the backend so the UI needs no second call. */
    @SerializedName("owner_name") public String ownerName;

    public static class ActionItemRow {
        public String id;
        public String title;
        public String status;
        @SerializedName("owner_id") public String ownerId;
        @SerializedName("due_date") public String dueDate;
    }

    public static class MeetingRow {
        public String id;
        public String status;
        @SerializedName("started_at") public String startedAt;
        @SerializedName("duration_seconds") public Integer durationSeconds;
    }

    public static class ProposalRow {
        public String id;
        public String title;
        public String status;
        @SerializedName("total_amount") public Double totalAmount;
        public String currency;
    }

    /**
     * No total and no currency: the backend's mou_documents table has no such
     * columns, so a screen that sums a client's documents cannot pick a
     * contract up by accident.
     */
    public static class MouRow {
        public String id;
        public String title;
        public String status;
        @SerializedName("created_at") public String createdAt;
    }

    public static class FollowupRow {
        public String id;
        @SerializedName("due_date") public String dueDate;
        public String channel;
        public String status;
        public String note;
    }

    public static class IntelligenceRow {
        public String id;
        public String note;
        public String category;
        public String source;
        @SerializedName("created_at") public String createdAt;
    }

    public static class HistoryRow {
        public String from;
        public String to;
        public String reason;
        public String at;
        /** Who made the move — a person's name, or "the system". */
        public String by;
    }
}
