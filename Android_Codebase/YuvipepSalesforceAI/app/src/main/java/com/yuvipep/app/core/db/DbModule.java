package com.yuvipep.app.core.db;

import android.content.Context;

import androidx.room.Room;

import javax.inject.Singleton;

import dagger.Module;
import dagger.Provides;
import dagger.hilt.InstallIn;
import dagger.hilt.android.qualifiers.ApplicationContext;
import dagger.hilt.components.SingletonComponent;

@Module
@InstallIn(SingletonComponent.class)
public class DbModule {

    @Provides
    @Singleton
    AppDatabase provideDatabase(@ApplicationContext Context context) {
        return Room.databaseBuilder(context, AppDatabase.class, "yuvipep.db")
                // Phase 0 shell: schema will grow every phase; destructive
                // migration is acceptable for a cache-only database whose
                // truth always lives on the server.
                .fallbackToDestructiveMigration()
                .build();
    }

    @Provides
    @Singleton
    CachedUserDao provideCachedUserDao(AppDatabase db) {
        return db.cachedUserDao();
    }
}
