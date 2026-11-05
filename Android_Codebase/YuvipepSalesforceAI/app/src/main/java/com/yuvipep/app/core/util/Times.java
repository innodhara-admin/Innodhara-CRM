package com.yuvipep.app.core.util;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeParseException;

/** Backend timestamps are naive-UTC ISO strings; render them humanly. */
public final class Times {

    private Times() {
    }

    /** ISO string (with or without offset) → epoch millis; 0 when unparseable. */
    public static long parseUtc(@Nullable String iso) {
        if (iso == null || iso.isEmpty()) return 0L;
        try {
            return OffsetDateTime.parse(iso).toInstant().toEpochMilli();
        } catch (DateTimeParseException ignored) {
        }
        try {
            return LocalDateTime.parse(iso).toInstant(ZoneOffset.UTC).toEpochMilli();
        } catch (DateTimeParseException ignored) {
        }
        return 0L;
    }

    /** "just now" / "5m ago" / "3h ago" / "2d ago". */
    @NonNull
    public static String ago(long epochMillis) {
        if (epochMillis <= 0) return "";
        long deltaMin = (Instant.now().toEpochMilli() - epochMillis) / 60_000L;
        if (deltaMin < 1) return "just now";
        if (deltaMin < 60) return deltaMin + "m ago";
        long hours = deltaMin / 60;
        if (hours < 24) return hours + "h ago";
        return (hours / 24) + "d ago";
    }

    /** ISO date or datetime → "30 Jul" (adds the year when it isn't this
     * year); the raw string comes back when unparseable — never blank. */
    @NonNull
    public static String dateLabel(@Nullable String iso) {
        if (iso == null || iso.isEmpty()) return "";
        String datePart = iso.length() >= 10 ? iso.substring(0, 10) : iso;
        try {
            java.time.LocalDate date = java.time.LocalDate.parse(datePart);
            String pattern = date.getYear() == java.time.LocalDate.now().getYear()
                    ? "d MMM" : "d MMM yyyy";
            return date.format(java.time.format.DateTimeFormatter
                    .ofPattern(pattern, java.util.Locale.ENGLISH));
        } catch (DateTimeParseException e) {
            return iso;
        }
    }

    /**
     * ISO datetime → "29 Jul, 13:54" in the reader's OWN timezone. The backend
     * stores naive UTC, so slicing the string would print 08:24 to somebody
     * whose clock says 13:54 — a delivery trace that disagrees with the wall
     * clock reads like the wrong message. Unparseable input comes back raw.
     */
    @NonNull
    public static String dateTimeLabel(@Nullable String iso) {
        long at = parseUtc(iso);
        if (at <= 0) return iso == null ? "" : iso;
        java.time.ZonedDateTime local = Instant.ofEpochMilli(at)
                .atZone(java.time.ZoneId.systemDefault());
        String pattern = local.getYear() == java.time.LocalDate.now().getYear()
                ? "d MMM, HH:mm" : "d MMM yyyy, HH:mm";
        return local.format(java.time.format.DateTimeFormatter
                .ofPattern(pattern, java.util.Locale.ENGLISH));
    }

    /** "expires in 3h" / "expires in 2d" / "expired". */
    @NonNull
    public static String untilLabel(@Nullable String iso) {
        long at = parseUtc(iso);
        if (at <= 0) return "";
        long deltaMin = (at - Instant.now().toEpochMilli()) / 60_000L;
        if (deltaMin <= 0) return "expired";
        if (deltaMin < 60) return "expires in " + deltaMin + "m";
        long hours = deltaMin / 60;
        if (hours < 24) return "expires in " + hours + "h";
        return "expires in " + (hours / 24) + "d";
    }
}
