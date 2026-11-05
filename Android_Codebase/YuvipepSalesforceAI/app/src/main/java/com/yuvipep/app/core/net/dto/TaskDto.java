package com.yuvipep.app.core.net.dto;

import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/**
 * A task (ActionItem row), unified across the two shapes the backend
 * exposes for the SAME table (01 §1.9/1.12):
 *  - GET /projects/{id}.tasks[]: id/title/status/assignee_id/phase/priority/
 *    due_date/blocked/blocked_reason/visible_to_client/progress_percent/
 *    assignment_reason/depends_on_ids — rich, but no description/result_note/
 *    completed_at/created_at, and no project_id echoed back.
 *  - GET /action-items: id/title/description/status/owner_id/owner_name/
 *    lead_id/school/due_date/result_note/completed_at/created_at — has the
 *    narrative fields but none of phase/priority/blocked/progress/
 *    assignment_reason/depends_on_ids.
 * There is no single endpoint that returns both; TasksRepository merges
 * project-sourced and action-items-sourced rows by id (11 §6e). `projectId`/
 * `projectName` are filled in locally by the repository, never by the wire —
 * they carry no @SerializedName so Gson never touches them.
 */
public class TaskDto {
    public String id;
    public String title;
    @Nullable public String description;
    public String status;
    @SerializedName(value = "assignee_id", alternate = "owner_id")
    @Nullable public String assigneeId;
    @SerializedName("owner_name") @Nullable public String assigneeName;
    @SerializedName("lead_id") @Nullable public String leadId;
    @SerializedName("school") @Nullable public String leadName;
    @SerializedName("due_date") @Nullable public String dueDate;
    @Nullable public String phase;
    @Nullable public String priority;
    public boolean blocked;
    @SerializedName("blocked_reason") @Nullable public String blockedReason;
    @SerializedName("visible_to_client") public boolean visibleToClient;
    @SerializedName("progress_percent") @Nullable public Integer progressPercent;
    @SerializedName("assignment_reason") @Nullable public String assignmentReason;
    @SerializedName("depends_on_ids") @Nullable public List<String> dependsOnIds;
    @SerializedName("client_commitment_id") @Nullable public String clientCommitmentId;
    @SerializedName("result_note") @Nullable public String resultNote;
    @SerializedName("completed_at") @Nullable public String completedAt;
    @SerializedName("created_at") @Nullable public String createdAt;

    /** Filled locally once the task is discovered inside a project's tasks[]
     * (or left null when it only surfaced via the thin /action-items list —
     * an honest signal that the richer fields above may be unknown). */
    public transient String projectId;
    public transient String projectName;
    /** True once this row's data came from a project GET (rich fields
     * trustworthy); false when only /action-items backed it. */
    public transient boolean rich;
}
