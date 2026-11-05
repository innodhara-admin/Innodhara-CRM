package com.yuvipep.app.core.util;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

import java.time.LocalDate;
import java.time.ZoneId;

/**
 * Which day a backend timestamp falls on.
 *
 * The backend stores instants in UTC and, since app/core/clock.py, answers
 * "which day is that?" in the ORGANISATION's timezone. This app used to answer
 * the same question in the PHONE's timezone ({@code ZoneId.systemDefault()}),
 * which is the same mix one layer out: a rep travelling — or a phone simply set
 * wrong — and the app names a different day from the server that sent it the
 * rows.
 *
 * The boundary that matters for Asia/Kolkata is 18:30 UTC: from there on, the
 * instant already belongs to tomorrow locally. A task due 20:00 UTC is due
 * 01:30 the next morning in Kolkata.
 */
public class WorkDayTest {

    private static final ZoneId KOLKATA = ZoneId.of("Asia/Kolkata");
    private static final ZoneId UTC = ZoneId.of("UTC");
    private static final ZoneId LONDON = ZoneId.of("Europe/London");

    @Test
    public void anEveningUtcInstantBelongsToTheNextDayInKolkata() {
        assertEquals(LocalDate.of(2026, 8, 26),
                WorkDay.localDate("2026-08-25T20:00:00", KOLKATA));
    }

    @Test
    public void aWorkingHoursUtcInstantBelongsToTheSameDayInKolkata() {
        assertEquals(LocalDate.of(2026, 8, 25),
                WorkDay.localDate("2026-08-25T05:00:00", KOLKATA));
    }

    @Test
    public void theBoundaryIs1830Utc() {
        assertEquals(LocalDate.of(2026, 8, 25),
                WorkDay.localDate("2026-08-25T18:29:00", KOLKATA));
        assertEquals(LocalDate.of(2026, 8, 26),
                WorkDay.localDate("2026-08-25T18:30:00", KOLKATA));
    }

    /** The same instant, two organisations, two correct answers. */
    @Test
    public void theZoneIsWhatDecides() {
        assertEquals(LocalDate.of(2026, 8, 26),
                WorkDay.localDate("2026-08-25T20:00:00", KOLKATA));
        assertEquals(LocalDate.of(2026, 8, 25),
                WorkDay.localDate("2026-08-25T20:00:00", UTC));
        assertEquals(LocalDate.of(2026, 8, 25),
                WorkDay.localDate("2026-08-25T20:00:00", LONDON));
    }

    @Test
    public void anOffsetOnTheWireIsHonouredRatherThanReinterpreted() {
        // If the backend ever starts sending an offset, the answer must not move.
        assertEquals(WorkDay.localDate("2026-08-25T20:00:00", KOLKATA),
                WorkDay.localDate("2026-08-25T20:00:00Z", KOLKATA));
    }

    @Test
    public void nothingParsesToNothing() {
        assertNull(WorkDay.localDate(null, KOLKATA));
        assertNull(WorkDay.localDate("", KOLKATA));
        assertNull(WorkDay.localDate("not a date", KOLKATA));
    }

    // ── zoneOf: what the app should reckon dates in ─────────────────────────

    @Test
    public void theOrganisationsZoneIsUsedWhenTheServerSendsOne() {
        assertEquals(KOLKATA, WorkDay.zoneOf("Asia/Kolkata"));
    }

    @Test
    public void anUnknownOrMissingZoneFallsBackToTheDeviceRatherThanCrashing() {
        // Mirrors app/core/clock.py `zone()`: a bad value on a settings screen
        // must not be able to stop a screen from rendering.
        assertEquals(ZoneId.systemDefault(), WorkDay.zoneOf(null));
        assertEquals(ZoneId.systemDefault(), WorkDay.zoneOf(""));
        assertEquals(ZoneId.systemDefault(), WorkDay.zoneOf("Not/AZone"));
    }

    // ── bucketOf: the My Tasks grouping, as pure logic ──────────────────────

    @Test
    public void aTaskDueLaterTodayIsTodaysNotOverdue() {
        // 20:00 UTC is 01:30 tomorrow in Kolkata — and "tomorrow" is the day
        // the reader is already in at that moment.
        LocalDate today = LocalDate.of(2026, 8, 26);
        assertEquals(WorkDay.Bucket.TODAY,
                WorkDay.bucketOf("2026-08-25T20:00:00", today, KOLKATA, false));
    }

    @Test
    public void aTaskThatReallyIsLateIsOverdue() {
        LocalDate today = LocalDate.of(2026, 8, 26);
        assertEquals(WorkDay.Bucket.OVERDUE,
                WorkDay.bucketOf("2026-08-20T06:00:00", today, KOLKATA, false));
    }

    @Test
    public void blockedOutranksEveryDateBucket() {
        LocalDate today = LocalDate.of(2026, 8, 26);
        assertEquals(WorkDay.Bucket.BLOCKED,
                WorkDay.bucketOf("2026-08-20T06:00:00", today, KOLKATA, true));
    }

    @Test
    public void theNextSevenDaysAreThisWeekAndTheEighthIsLater() {
        LocalDate today = LocalDate.of(2026, 8, 26);
        assertEquals(WorkDay.Bucket.WEEK,
                WorkDay.bucketOf("2026-09-02T06:00:00", today, KOLKATA, false));
        assertEquals(WorkDay.Bucket.LATER,
                WorkDay.bucketOf("2026-09-03T06:00:00", today, KOLKATA, false));
    }

    @Test
    public void aTaskWithNoDueDateIsLaterNotOverdue() {
        LocalDate today = LocalDate.of(2026, 8, 26);
        assertEquals(WorkDay.Bucket.LATER,
                WorkDay.bucketOf(null, today, KOLKATA, false));
    }
}
