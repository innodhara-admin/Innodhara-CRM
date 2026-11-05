package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** Small single-purpose response shapes from the /tasks/{id}/... router. */
public final class TaskResponses {

    private TaskResponses() {
    }

    public static class Complete {
        public boolean ok;
        @SerializedName("already_done") public boolean alreadyDone;
        @SerializedName("deliverable_id") @Nullable public String deliverableId;
    }

    public static class Decline {
        public boolean ok;
        @SerializedName("reassigned_to") @Nullable public String reassignedTo;
        @Nullable public String reason;
        @SerializedName("needs_lead") public boolean needsLead;
    }

    public static class NewDate {
        public boolean accepted;
        @SerializedName("routed_to_lead") public boolean routedToLead;
        @Nullable public List<String> breaks;
    }

    public static class Split {
        public List<Child> children;

        public static class Child {
            public String id;
            public String title;
            @SerializedName("assignee_id") @Nullable public String assigneeId;
        }
    }
}
