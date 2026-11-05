package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** Request bodies for the /projects router (Phase 4). */
public final class ProjectRequests {

    private ProjectRequests() {
    }

    public static class Status {
        public String status;
        @Nullable public String reason;
        @SerializedName("revival_date") @Nullable public String revivalDate;
        @SerializedName("revival_context") @Nullable public String revivalContext;

        public Status(String status, @Nullable String reason) {
            this.status = status;
            this.reason = reason;
        }
    }

    public static class PhaseShift {
        public String phase;
        @SerializedName("anchor_date") @Nullable public String anchorDate;

        public PhaseShift(String phase) {
            this.phase = phase;
        }
    }

    public static class Stakeholder {
        @SerializedName("contact_id") public String contactId;
        @SerializedName("role_at_client") @Nullable public String roleAtClient;
        @Nullable public String influence;
        @SerializedName("preferred_channel") public String preferredChannel = "email";
        @SerializedName("preferred_language") public String preferredLanguage = "english";
        @SerializedName("receives_progress_updates") public boolean receivesProgressUpdates;
        @SerializedName("do_not_contact") public boolean doNotContact;
    }

    public static class ResolveConflict {
        @SerializedName("resolution_note") public String resolutionNote;

        public ResolveConflict(String resolutionNote) {
            this.resolutionNote = resolutionNote;
        }
    }

    public static class Children {
        @SerializedName("branch_names") public List<String> branchNames;
        @SerializedName("invoicing_mode") public String invoicingMode = "group";

        public Children(List<String> branchNames, String invoicingMode) {
            this.branchNames = branchNames;
            this.invoicingMode = invoicingMode;
        }
    }

    public static class Member {
        @SerializedName("user_id") public String userId;
        @SerializedName("role_in_project") @Nullable public String roleInProject;

        public Member(String userId, @Nullable String roleInProject) {
            this.userId = userId;
            this.roleInProject = roleInProject;
        }
    }
}
