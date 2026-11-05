package com.yuvipep.app.feature.projects;

import androidx.annotation.ColorRes;
import androidx.annotation.Nullable;

import com.yuvipep.app.R;

/** Client-side color for backend health values (app/core/constants.py
 * ProjectHealth) — labels reuse LeadStates' generic humaniser. */
public final class ProjectStates {

    public static final String[] STATUSES = {
            "planning", "proposal_stage", "negotiation", "agreed",
            "preparation", "delivery", "payment_pending", "closed",
            "on_hold", "lost",
    };

    private ProjectStates() {
    }

    @ColorRes
    public static int healthColor(@Nullable String health) {
        if (health == null) return R.color.md_light_outline;
        switch (health) {
            case "on_track": return R.color.health_on_track;
            case "at_risk": return R.color.health_at_risk;
            case "delayed": return R.color.health_delayed;
            default: return R.color.md_light_outline;
        }
    }
}
