package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

/** Request bodies for the /tasks/{id}/... lifecycle router (Phase 4, 03 §7). */
public final class TaskRequests {

    private TaskRequests() {
    }

    public static class Complete {
        @SerializedName("result_note") @Nullable public String resultNote;
        @SerializedName("completion_method") public String completionMethod = "in_app";
        @SerializedName("deliverable_type") @Nullable public String deliverableType;
        @SerializedName("deliverable_title") @Nullable public String deliverableTitle;
        @SerializedName("deliverable_content_md") @Nullable public String deliverableContentMd;
        @SerializedName("deliverable_file_path") @Nullable public String deliverableFilePath;
    }

    public static class Decline {
        public String reason = "other";
        @Nullable public String note;

        public Decline(String reason, @Nullable String note) {
            this.reason = reason;
            this.note = note;
        }
    }

    public static class Block {
        public String reason;

        public Block(String reason) {
            this.reason = reason;
        }
    }

    public static class Progress {
        public int percent;
        @Nullable public String note;

        public Progress(int percent, @Nullable String note) {
            this.percent = percent;
            this.note = note;
        }
    }

    public static class NewDate {
        @SerializedName("new_due") public String newDue;
        @Nullable public String reason;

        public NewDate(String newDue, @Nullable String reason) {
            this.newDue = newDue;
            this.reason = reason;
        }
    }

    public static class Split {
        public List<Map<String, Object>> parts;

        public Split(List<Map<String, Object>> parts) {
            this.parts = parts;
        }
    }

    public static class VendorPromise {
        @SerializedName("vendor_name") public String vendorName;
        @SerializedName("promised_date") public String promisedDate;
        @SerializedName("chase_contact_user_id") @Nullable public String chaseContactUserId;

        public VendorPromise(String vendorName, String promisedDate) {
            this.vendorName = vendorName;
            this.promisedDate = promisedDate;
        }
    }

    public static class VendorSlip {
        @SerializedName("new_promised_date") public String newPromisedDate;
        @Nullable public String note;

        public VendorSlip(String newPromisedDate, @Nullable String note) {
            this.newPromisedDate = newPromisedDate;
            this.note = note;
        }
    }
}
