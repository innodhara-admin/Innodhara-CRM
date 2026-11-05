package com.yuvipep.app.core.db;

import androidx.room.Entity;
import androidx.room.PrimaryKey;

/**
 * The OfflineQueue (07 §4): a state-changing call captured while offline.
 * Fully generic — any method/path/body, drained FIFO with the idempotency
 * key minted at intent time so retries are safe.
 */
@Entity(tableName = "queued_write")
public class QueuedWrite {

    public static final String STATE_PENDING = "pending";
    public static final String STATE_FAILED = "failed";

    @PrimaryKey(autoGenerate = true) public long seq;
    public String method;         // POST / PATCH / PUT / DELETE
    public String path;           // e.g. api/v1/approvals/{id}/decide, resolved
    public String bodyJson;
    public String idempotencyKey;
    public String entityHint;     // "approval:<id>" — lets UI mark its card
    public long createdAt;
    public int attempts;
    public String state = STATE_PENDING;
    public String lastError;
}
