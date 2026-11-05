package com.yuvipep.app.core.db;

import androidx.lifecycle.LiveData;
import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.Query;
import androidx.room.Update;

import java.util.List;

@Dao
public interface QueuedWriteDao {

    @Insert
    long enqueue(QueuedWrite write);

    @Query("SELECT * FROM queued_write WHERE state = 'pending' ORDER BY seq")
    List<QueuedWrite> pending();

    @Query("SELECT COUNT(*) FROM queued_write WHERE state = 'pending'")
    LiveData<Integer> observePendingCount();

    @Update
    void update(QueuedWrite write);

    @Query("DELETE FROM queued_write WHERE seq = :seq")
    void delete(long seq);

    @Query("DELETE FROM queued_write")
    void clear();
}
