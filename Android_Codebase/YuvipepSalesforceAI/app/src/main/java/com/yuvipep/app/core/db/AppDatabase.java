package com.yuvipep.app.core.db;

import androidx.room.Database;
import androidx.room.RoomDatabase;

/**
 * The offline cache (single source of truth for screens, 02 §1). Phase 1
 * adds notifications, approvals and the offline write queue; each later
 * phase adds its entities (leads, projects, tasks…).
 */
@Database(
        entities = {
                CachedUser.class,
                CachedNotification.class,
                CachedApproval.class,
                QueuedWrite.class,
        },
        version = 3,
        exportSchema = false
)
public abstract class AppDatabase extends RoomDatabase {

    public abstract CachedUserDao cachedUserDao();

    public abstract CachedNotificationDao notificationDao();

    public abstract CachedApprovalDao approvalDao();

    public abstract QueuedWriteDao queuedWriteDao();
}
