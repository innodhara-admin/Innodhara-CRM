package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** Response bodies for the /proposals action routes. */
public final class ProposalResponses {

    private ProposalResponses() {
    }

    /** POST /proposals/{id}/upload-revision */
    public static class UploadRevision {
        @SerializedName("uploaded") public boolean uploaded;
        @SerializedName("revision_no") public int revisionNo;
        // null = file text unreadable, so not machine-verified.
        @SerializedName("total_verified") public Boolean totalVerified;
        @SerializedName("status") public String status;
        @SerializedName("note") public String note;
    }

    /** POST /proposals/{id}/submit-review */
    public static class SubmitReview {
        @SerializedName("status") public String status;
        @SerializedName("approval_id") public String approvalId;
        @SerializedName("note") public String note;
    }

    /** POST /proposals/{id}/approve-send */
    public static class ApproveSend {
        @SerializedName("approved") public boolean approved;
        @SerializedName("message_id") public String messageId;
        @SerializedName("status") public String status;
        @SerializedName("to") public String to;
        @SerializedName("cc") public List<String> cc;
    }
}
