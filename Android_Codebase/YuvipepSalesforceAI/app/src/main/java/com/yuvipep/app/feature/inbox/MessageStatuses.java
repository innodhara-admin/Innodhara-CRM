package com.yuvipep.app.feature.inbox;

import androidx.annotation.ColorRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.R;

/**
 * Client-side rendering of backend message statuses. As with lead states, the
 * app maps strings to colours only and humanises the label generically, so a
 * status the server adds tomorrow renders sensibly instead of blank.
 *
 * The trail (draft → pending → queued → sent → delivered) is the happy path
 * from 03 §9; rejected, failed and dead_letter are ends, not steps, and the
 * chip says so by colour rather than by pretending they sit on the line.
 */
public final class MessageStatuses {

    /** The filter chips, in the order a message travels. */
    public static final String[] FILTERS = {
            "all", "pending_approval", "queued", "sent", "delivered", "failed",
    };

    /** The happy path, for the trail rendering. */
    private static final String[] TRAIL = {
            "draft", "pending_approval", "queued", "sent", "delivered",
    };

    private MessageStatuses() {
    }

    @ColorRes
    public static int color(@Nullable String status) {
        if (status == null) return R.color.lead_open;
        switch (status) {
            // Arrived = green, in flight = teal, waiting on a person = amber,
            // ended badly = red. Read the palette by what the colour means
            // here, not by the lead state it was first named for.
            case "delivered":
            case "sent":
                return R.color.lead_active;
            case "queued":
            case "sending":
                return R.color.lead_client_execution;
            case "pending_approval":
                return R.color.lead_execution;
            case "failed":
            case "dead_letter":
            case "rejected":
                return R.color.lead_lost;
            default:
                return R.color.lead_open;
        }
    }

    /** "pending_approval" → "Pending approval". */
    @NonNull
    public static String label(@Nullable String status) {
        if (status == null || status.isEmpty()) return "";
        String words = status.replace('_', ' ');
        return Character.toUpperCase(words.charAt(0)) + words.substring(1);
    }

    /**
     * How far along the happy path this status is, or -1 when it is not on it
     * (rejected / failed / dead_letter / anything new the server invents).
     */
    public static int trailIndex(@Nullable String status) {
        for (int i = 0; i < TRAIL.length; i++) {
            if (TRAIL[i].equals(status)) return i;
        }
        return -1;
    }

    public static int trailLength() {
        return TRAIL.length;
    }

    /** "draft › pending approval › queued" — the steps taken so far. */
    @NonNull
    public static String trail(@Nullable String status) {
        int reached = trailIndex(status);
        if (reached < 0) return label(status);
        StringBuilder out = new StringBuilder();
        for (int i = 0; i <= reached; i++) {
            if (i > 0) out.append(" › ");
            out.append(label(TRAIL[i]));
        }
        return out.toString();
    }
}
