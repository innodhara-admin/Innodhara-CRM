package com.yuvipep.app.core.net.dto;

import java.util.Map;

/**
 * POST /meetings/notes — the meeting plus what was done with it.
 *
 * <p>Exactly one of {@link #planner} and {@link #relationship} is filled. A
 * sales meeting gets a plan; a catch-up gets a summary and a suggested next
 * touch and deliberately no plan at all, so {@code planner} being null there
 * is the correct answer rather than a missing one.
 */
public class MeetingNotesResponse {
    public MeetingDto meeting;
    public Map<String, Object> planner;
    /** Present only for a catch-up: {@code next_touch}, {@code action_items}. */
    public Map<String, Object> relationship;
}
