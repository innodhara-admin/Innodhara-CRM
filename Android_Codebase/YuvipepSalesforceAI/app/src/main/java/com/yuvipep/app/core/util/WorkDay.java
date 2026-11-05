package com.yuvipep.app.core.util;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;

/**
 * Which working day a backend timestamp belongs to.
 *
 * <p>The backend stores instants in UTC and answers "which day is that?" in the
 * <b>organisation's</b> timezone (see {@code app/core/clock.py}). This class is
 * the app's half of that agreement, so the phone and the server never name
 * different days for the same row.
 *
 * <p>It used to live inside {@code MyTasksFragment} as two private statics
 * reading {@code ZoneId.systemDefault()} — the phone's zone, which is not the
 * organisation's and cannot be tested without a device. Pulling it out is what
 * makes {@code WorkDayTest} possible; asking for the zone rather than reaching
 * for one is what makes it correct.
 */
public final class WorkDay {

    /** How My Tasks groups work. Order is the order the sections are shown. */
    public enum Bucket {
        BLOCKED, OVERDUE, TODAY, WEEK, LATER
    }

    /** A week ahead counts as "this week"; the eighth day is "later". */
    private static final int WEEK_DAYS = 7;

    private WorkDay() {
    }

    /**
     * The organisation's zone, or the device's when the server did not say.
     *
     * <p>Mirrors {@code clock.zone()}: an unusable value degrades rather than
     * throwing, because a timezone is free text on a settings screen and a typo
     * in it must not be able to stop a screen from rendering. The device zone is
     * the right fallback here — it is what this app used before the server
     * started sending one, so an older backend behaves exactly as it did.
     */
    @NonNull
    public static ZoneId zoneOf(@Nullable String orgTimezone) {
        if (orgTimezone == null || orgTimezone.trim().isEmpty()) {
            return ZoneId.systemDefault();
        }
        try {
            return ZoneId.of(orgTimezone.trim());
        } catch (java.time.DateTimeException e) {
            // ZoneRulesException (unknown region) and the plain
            // DateTimeException (malformed id) both land here.
            return ZoneId.systemDefault();
        }
    }

    /**
     * Which local day a stored instant falls on, or null when there is no date.
     *
     * <p>{@link Times#parseUtc} reads a naive string as UTC — which is what the
     * backend writes — and honours an explicit offset if one ever appears.
     */
    @Nullable
    public static LocalDate localDate(@Nullable String iso, @NonNull ZoneId zone) {
        long millis = Times.parseUtc(iso);
        if (millis == 0L) return null;
        return Instant.ofEpochMilli(millis).atZone(zone).toLocalDate();
    }

    /**
     * Where one task belongs.
     *
     * @param today the reader's today, in {@code zone} — passed in rather than
     *              read here so the caller resolves it once for a whole list and
     *              a test can pin it.
     */
    @NonNull
    public static Bucket bucketOf(@Nullable String dueIso, @NonNull LocalDate today,
                                  @NonNull ZoneId zone, boolean blocked) {
        if (blocked) return Bucket.BLOCKED;
        LocalDate due = localDate(dueIso, zone);
        if (due == null) return Bucket.LATER;
        if (due.isBefore(today)) return Bucket.OVERDUE;
        if (due.isEqual(today)) return Bucket.TODAY;
        if (!due.isAfter(today.plusDays(WEEK_DAYS))) return Bucket.WEEK;
        return Bucket.LATER;
    }
}
