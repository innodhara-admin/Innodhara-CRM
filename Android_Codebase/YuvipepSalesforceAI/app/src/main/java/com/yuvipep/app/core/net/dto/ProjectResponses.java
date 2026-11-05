package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/** Small single-purpose response shapes from the /projects router. */
public final class ProjectResponses {

    private ProjectResponses() {
    }

    public static class WhatsBlocking {
        public String answer;
    }

    public static class Brief {
        public String brief;
    }

    public static class WeeklyReport {
        @Nullable public Boolean skipped;
        @Nullable public String reason;
        @SerializedName("digest_id") @Nullable public String digestId;
        @SerializedName("content_md") @Nullable public String contentMd;
        @SerializedName("sent_message_id") @Nullable public String sentMessageId;
    }

    public static class Children {
        public List<Child> children;

        public static class Child {
            @SerializedName("project_id") public String projectId;
            @SerializedName("lead_id") public String leadId;
            public String name;
        }
    }

    public static class MemberAdded {
        public boolean ok;
        @SerializedName("onboarding_brief") @Nullable public String onboardingBrief;
    }

    public static class StakeholderSaved {
        public String id;
        public boolean updated;
    }
}
