package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/**
 * GET /messages (list row) and GET /messages/{id} (adds delivery_log) — the
 * message centre, the delivery trace and the draft preview on a message
 * approval all read this one shape.
 *
 * Attachments are NOT in the payload: the backend stores them but does not
 * serialise them, so the delivery trace says so rather than showing an empty
 * section. The .eml of a dry-run send is still reachable — the "sent" event's
 * detail carries {@code dry_run:<path>} for GET /files/{path}.
 */
public class MessageDto {
    @SerializedName("id") public String id;
    @SerializedName("kind") public String kind;
    @SerializedName("channel") public String channel;
    @SerializedName("status") public String status;
    @SerializedName("to") public String to;
    @SerializedName("cc") public List<String> cc;
    /** Meeting invites may carry a blind copy (2026-09-23). Absent on older servers. */
    @SerializedName("bcc") public List<String> bcc;
    @SerializedName("subject") public String subject;
    @SerializedName("body") public String body;
    @SerializedName("lead_id") public String leadId;
    @SerializedName("proposal_id") public String proposalId;
    /** Phase 6: /messages is org-wide, so Mine/All filters on this. */
    @SerializedName("sender_user_id") public String senderUserId;
    /**
     * Phase 7 (F30): the fill-in-the-blanks the AI left behind — "[Name]",
     * "[Insert Date]". Non-empty means approving is refused until the approver
     * confirms they mean to send it as it stands. Empty or absent = nothing
     * detected, which is a floor and not a promise of quality.
     */
    @SerializedName("blanks") public List<String> blanks;
    @SerializedName("attempts") public int attempts;
    @SerializedName("last_error") public String lastError;
    @SerializedName("sent_at") public String sentAt;
    @SerializedName("created_at") public String createdAt;
    @SerializedName("delivery_log") public List<DeliveryEvent> deliveryLog;

    public static class DeliveryEvent {
        @SerializedName("event") public String event;
        @SerializedName("detail") public String detail;
        @SerializedName("at") public String at;
    }
}
