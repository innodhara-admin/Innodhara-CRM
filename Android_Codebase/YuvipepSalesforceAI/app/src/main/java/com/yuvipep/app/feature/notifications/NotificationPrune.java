package com.yuvipep.app.feature.notifications;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.List;

/**
 * Which cached notifications the newest server page lets us drop.
 *
 * <p>The cache used to only add and update, so a notification deleted on the
 * server stayed on the phone for good (24 Sep 2026: the daily-digest flood was
 * removed server-side and would have kept showing here).
 */
final class NotificationPrune {

    private NotificationPrune() { }

    /**
     * Null: the page was short, so it is everything the server has — drop any
     * cached row not in it. Otherwise the oldest createdAt in the page: only
     * cached rows at or after it can be judged missing.
     */
    @Nullable
    static String cutoff(@NonNull List<String> pageCreatedAts, int limit) {
        if (pageCreatedAts.size() < limit) return null;
        String oldest = null;
        for (String at : pageCreatedAts) {
            if (at != null && (oldest == null || at.compareTo(oldest) < 0)) oldest = at;
        }
        return oldest;
    }
}
