package com.yuvipep.app.core.db;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

/**
 * Room mirror of a pending approval. `localState` layers the offline story
 * on top of the server status: "" (normal), "queued" (decide waiting for
 * connectivity), "failed:<backend message>" (queued write refused — shown
 * honestly, never silently dropped, 07 §4).
 */
@Entity(tableName = "cached_approval")
public class CachedApproval {

    @PrimaryKey @NonNull public String id = "";
    public String entityType;
    public String entityId;
    public String projectId;
    public String stage;
    public String status;
    public String reason;
    public String recommendation;
    public String jointWithUserId;
    public String jointStatus;
    public String bundledEntitiesJson;
    public String expiresAt;
    public String localState = "";
    public long fetchedAt;
}
