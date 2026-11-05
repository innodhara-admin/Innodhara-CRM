package com.yuvipep.app.core.db;

import androidx.annotation.Nullable;
import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;

@Dao
public interface CachedUserDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    void upsert(CachedUser user);

    @Nullable
    @Query("SELECT * FROM cached_user WHERE userId = :userId LIMIT 1")
    CachedUser get(String userId);

    @Nullable
    @Query("SELECT * FROM cached_user LIMIT 1")
    CachedUser getAny();

    @Query("DELETE FROM cached_user")
    void clear();
}
