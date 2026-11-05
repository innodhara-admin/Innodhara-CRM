package com.yuvipep.app.core.db;

import androidx.lifecycle.LiveData;
import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;

import java.util.List;

@Dao
public interface CachedNotificationDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    void upsertAll(List<CachedNotification> rows);

    @Query("SELECT * FROM cached_notification ORDER BY createdAt DESC LIMIT 200")
    LiveData<List<CachedNotification>> observeAll();

    @Query("SELECT * FROM cached_notification ORDER BY createdAt DESC LIMIT 200")
    List<CachedNotification> getAll();

    @Query("SELECT COUNT(*) FROM cached_notification WHERE isRead = 0")
    LiveData<Integer> observeUnreadCount();

    @Query("SELECT * FROM cached_notification WHERE isRead = 0 ORDER BY createdAt DESC")
    List<CachedNotification> getUnread();

    @Query("UPDATE cached_notification SET isRead = 1 WHERE id = :id")
    void markRead(String id);

    @Query("SELECT MAX(createdAt) FROM cached_notification")
    String newestCreatedAt();

    @Query("DELETE FROM cached_notification")
    void clear();

    /** Rows the server no longer has, when its page was everything it holds. */
    @Query("DELETE FROM cached_notification WHERE id NOT IN (:keep)")
    void deleteAllExcept(List<String> keep);

    /** Rows inside a full page's time window that the server no longer has. */
    @Query("DELETE FROM cached_notification WHERE createdAt >= :since AND id NOT IN (:keep)")
    void deleteSinceExcept(String since, List<String> keep);
}
