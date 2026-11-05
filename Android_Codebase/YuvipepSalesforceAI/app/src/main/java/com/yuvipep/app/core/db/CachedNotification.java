package com.yuvipep.app.core.db;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

/** Room mirror of a backend notification row (07 §4 — reads are cache-first). */
@Entity(tableName = "cached_notification")
public class CachedNotification {

    @PrimaryKey @NonNull public String id = "";
    public String title;
    public String body;
    public String kind;
    public String entityType;
    public String entityId;
    public boolean isRead;
    public String createdAt;
    public long fetchedAt;
}
