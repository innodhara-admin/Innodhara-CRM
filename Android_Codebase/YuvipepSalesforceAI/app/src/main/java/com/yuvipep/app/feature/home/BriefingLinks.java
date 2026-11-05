package com.yuvipep.app.feature.home;

import androidx.annotation.Nullable;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Links the server writes into the Home briefing. Each task line ends with
 * its client as {@code [ABC School](yuvipep://lead/<id>)} (customer ask,
 * 21 Sep 2026: a task about a school should name it and lead there).
 */
public final class BriefingLinks {

    private static final Pattern LEAD = Pattern.compile("^yuvipep://lead/([A-Za-z0-9]+)$");

    private BriefingLinks() { }

    /** The lead id in a briefing link, or null if the link is not one. */
    @Nullable
    public static String leadIdOf(@Nullable String link) {
        if (link == null) return null;
        Matcher m = LEAD.matcher(link.trim());
        return m.matches() ? m.group(1) : null;
    }
}
