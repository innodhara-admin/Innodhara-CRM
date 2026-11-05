package com.yuvipep.app.feature.leads;

import androidx.annotation.ColorRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.R;

/**
 * Client-side rendering of backend lead states: the app maps state strings
 * to colors only; labels are the backend strings, humanised generically
 * (underscores → spaces) so a new server-side state never breaks the UI.
 */
public final class LeadStates {

    /** The known vocabulary (app/core/constants.py), for the filter chips. */
    public static final String[] ALL = {
            "cold_calling", "open", "active", "cold", "execution_in_progress",
            "client_execution_in_progress", "closed", "lost_for_now",
    };

    /**
     * Pre-sales: assigned to an agent, nobody has reached the school yet.
     * Unrelated to "cold", which means a lead we were working went quiet.
     */
    public static final String COLD_CALLING = "cold_calling";

    /** True while only the owner can move this lead on, and the
     *  Projects/Meetings tabs are not yet meaningful. */
    public static boolean isPreSales(@Nullable String state) {
        return COLD_CALLING.equals(state);
    }

    /** Won and delivered. NOT the same as {@code lost_for_now}, and mixing
     *  the two corrupts reporting. */
    public static final String CLOSED = "closed";

    /**
     * True once the selling and the delivery are finished — the only state
     * from which a client can be handed to a relationship manager.
     */
    public static boolean isClosed(@Nullable String state) {
        return CLOSED.equals(state);
    }

    private LeadStates() {
    }

    @ColorRes
    public static int color(@Nullable String state) {
        if (state == null) return R.color.lead_open;
        switch (state) {
            case "cold_calling": return R.color.lead_cold_calling;
            case "active": return R.color.lead_active;
            case "cold": return R.color.lead_cold;
            case "execution_in_progress": return R.color.lead_execution;
            case "client_execution_in_progress": return R.color.lead_client_execution;
            case "closed": return R.color.lead_closed;
            case "lost_for_now": return R.color.lead_lost;
            default: return R.color.lead_open;
        }
    }

    /** "client_execution_in_progress" → "Client execution in progress". */
    @NonNull
    public static String label(@Nullable String state) {
        if (state == null || state.isEmpty()) return "";
        String words = state.replace('_', ' ');
        return Character.toUpperCase(words.charAt(0)) + words.substring(1);
    }
}
