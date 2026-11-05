package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

/** POST /approvals/{id}/decide body. */
public class DecideRequest {
    @SerializedName("approve") public boolean approve;
    @SerializedName("note") public String note;
    /**
     * F30: the approver has read the "[Name]" blanks this draft still carries
     * and means to send it as it is. The server refuses otherwise. Sent on
     * every decide — false is the safe default and the server treats a missing
     * field the same way.
     */
    @SerializedName("allow_blanks") public boolean allowBlanks;

    public DecideRequest(boolean approve, String note) {
        this(approve, note, false);
    }

    public DecideRequest(boolean approve, String note, boolean allowBlanks) {
        this.approve = approve;
        this.note = note;
        this.allowBlanks = allowBlanks;
    }
}
