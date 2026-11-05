package com.yuvipep.app.core.db;

import androidx.lifecycle.LiveData;
import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;

import java.util.List;

@Dao
public interface CachedApprovalDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    void upsertAll(List<CachedApproval> rows);

    @Query("SELECT * FROM cached_approval ORDER BY expiresAt")
    LiveData<List<CachedApproval>> observeAll();

    @Query("SELECT * FROM cached_approval ORDER BY expiresAt")
    List<CachedApproval> getAll();

    @Query("SELECT * FROM cached_approval WHERE id = :id")
    CachedApproval byId(String id);

    @Query("UPDATE cached_approval SET localState = :state WHERE id = :id")
    void setLocalState(String id, String state);

    @Query("DELETE FROM cached_approval WHERE id = :id")
    void delete(String id);

    @Query("DELETE FROM cached_approval WHERE id NOT IN (:keepIds) AND localState = ''")
    void pruneExcept(List<String> keepIds);

    @Query("DELETE FROM cached_approval")
    void clear();
}
