package com.yuvipep.app.feature.notifications;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;

/**
 * Notifications deleted on the server must leave the phone too (24 Sep 2026:
 * 2,111 "Your daily digest" rows were removed server-side, and the cache —
 * which only ever added rows — would have kept showing them).
 */
public class NotificationPruneTest {

    @Test
    public void aShortPageIsEverythingSoAllElseGoes() {
        // Fewer rows than asked for: the server has nothing older.
        assertNull(NotificationPrune.cutoff(
                Arrays.asList("2026-09-24T01:00:00", "2026-09-23T10:00:00"), 100));
        assertNull(NotificationPrune.cutoff(Collections.emptyList(), 100));
    }

    @Test
    public void aFullPageOnlyVouchesForItsOwnWindow() {
        assertEquals("2026-09-20T08:00:00", NotificationPrune.cutoff(
                Arrays.asList("2026-09-24T01:00:00", "2026-09-20T08:00:00",
                        "2026-09-22T09:00:00"), 3));
    }
}
