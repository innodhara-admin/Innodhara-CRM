package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/**
 * GET /projects/{id} — the base project fields (mirrors ProjectDto) plus the
 * embedded tasks/members/stakeholders/commitments the backend joins in for
 * the one-screen project home (01 §1.7).
 */
public class ProjectDetailDto extends ProjectDto {

    public List<TaskDto> tasks;
    public List<Member> members;
    public List<Stakeholder> stakeholders;
    public List<Commitment> commitments;

    /** Project-embedded task shape — richer than /action-items (phase,
     * priority, blocked, assignment_reason, depends_on_ids) but without
     * description/result_note/completed_at. TaskDto unifies both shapes. */

    public static class Member {
        @SerializedName("user_id") public String userId;
        public String name;
        @SerializedName("role_in_project") public String roleInProject;
    }

    public static class Stakeholder {
        public String id;
        @SerializedName("contact_id") public String contactId;
        public String name;
        @SerializedName("role_at_client") public String roleAtClient;
        public String influence;
        @SerializedName("preferred_channel") public String preferredChannel;
        @SerializedName("receives_progress_updates") public boolean receivesProgressUpdates;
    }

    public static class Commitment {
        public String id;
        public String text;
        public String direction;
        public String status;
        @SerializedName("due_date") public String dueDate;
    }
}
