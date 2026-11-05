package com.yuvipep.app.core.net.dto;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.gson.annotations.SerializedName;

/**
 * POST /inbound/{id}/resolve body.
 *
 * The {@code note} field exists in the backend's schema but is accepted and
 * never stored, so no screen offers a note box — a control whose text is
 * silently dropped is worse than no control. It stays here only so the
 * request shape still matches the documented contract.
 */
public class TriageResolveRequest {
    @SerializedName("contact_id") @Nullable public String contactId;
    @SerializedName("mark_processed") public boolean markProcessed;
    @SerializedName("note") @Nullable public String note;
    // Phase 6 additions: the human's correction of the AI's reading, and the
    // project this message really belongs to.
    @SerializedName("intent") @Nullable public String intent;
    @SerializedName("project_id") @Nullable public String projectId;

    public TriageResolveRequest(@Nullable String contactId, boolean markProcessed,
                                @Nullable String note) {
        this.contactId = contactId;
        this.markProcessed = markProcessed;
        this.note = note;
    }

    /** Attach this message to a client's contact (which decides its lead). */
    public static TriageResolveRequest attachContact(@NonNull String contactId) {
        return new TriageResolveRequest(contactId, false, null);
    }

    /** Attach it to a project. */
    public static TriageResolveRequest attachProject(@NonNull String projectId) {
        TriageResolveRequest body = new TriageResolveRequest(null, false, null);
        body.projectId = projectId;
        return body;
    }

    /** Correct the AI's reading of what the message is asking for. */
    public static TriageResolveRequest setIntent(@NonNull String intent) {
        TriageResolveRequest body = new TriageResolveRequest(null, false, null);
        body.intent = intent;
        return body;
    }

    /** Mark it handled — it leaves the queue. */
    public static TriageResolveRequest markHandled() {
        return new TriageResolveRequest(null, true, null);
    }
}
