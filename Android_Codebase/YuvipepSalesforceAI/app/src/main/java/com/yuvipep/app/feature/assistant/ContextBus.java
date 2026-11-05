package com.yuvipep.app.feature.assistant;

import androidx.annotation.Nullable;

import javax.inject.Inject;
import javax.inject.Singleton;

/**
 * What the user is looking at (04 §4). Entity screens feed it on resume;
 * every assistant command carries the current entity's ids so "this" needs
 * no name. The transcript shows the chip; the user can clear it.
 */
@Singleton
public class ContextBus {

    @Nullable private String entityType;
    @Nullable private String entityId;
    @Nullable private String title;

    @Inject
    public ContextBus() {
    }

    public synchronized void set(@Nullable String type, @Nullable String id,
                                 @Nullable String title) {
        this.entityType = type;
        this.entityId = id;
        this.title = title;
    }

    public synchronized void clear() {
        set(null, null, null);
    }

    @Nullable public synchronized String entityType() { return entityType; }

    @Nullable public synchronized String entityId() { return entityId; }

    @Nullable public synchronized String title() { return title; }

    public synchronized boolean hasContext() {
        return entityType != null && entityId != null;
    }
}
