package com.yuvipep.app.core.auth;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * 1:1 mirror of the backend's app/core/permissions.py. The server is the
 * enforcer; this only shapes the UI (hides what a role can't do) —
 * 02 §7, 05 §1.
 */
public final class RoleGate {

    // Roles (app/core/constants.py)
    public static final String SUPER_ADMIN = "super_admin";
    public static final String ORG_ADMIN = "org_admin";
    public static final String SALES_AGENT = "sales_agent";
    public static final String SALES_LEAD = "sales_lead";
    public static final String OPERATIONS_AGENT = "operations_agent";
    public static final String OPERATIONS_LEAD = "operations_lead";
    /** Looks after a client after the selling and delivery are done. Holds no
     *  {@link #MANAGE_LEADS}: an RM must not move a lead's sales state. */
    public static final String RELATIONSHIP_MANAGER = "relationship_manager";

    // Permissions
    public static final String RECORD_MEETING = "record_meeting";
    public static final String SEND_PROPOSAL = "send_proposal";
    public static final String MANAGE_LEADS = "manage_leads";
    public static final String VIEW_LEADS = "view_leads";
    public static final String SEND_MESSAGES = "send_messages";
    public static final String MANAGE_TASKS = "manage_tasks";
    /** F51: confirming the org's AI assignment batch is a LEAD's job.
     *  Missing here while the backend gated it, so an agent was shown the
     *  batch card on Home, walked the whole screen and was refused on the
     *  last tap. RoleGateTest now diffs this matrix against the backend's
     *  own, generated, so the next omission fails the build. */
    public static final String CONFIRM_ASSIGNMENTS = "confirm_assignments";
    public static final String VIEW_DEMOS = "view_demos";
    public static final String SCHEDULE_DEMOS = "schedule_demos";
    public static final String UPDATE_DEMO_STATUS = "update_demo_status";
    public static final String EDIT_PRICING = "edit_pricing";
    public static final String MANAGE_PROGRAMS = "manage_programs";
    public static final String MANAGE_TEMPLATES = "manage_templates";
    public static final String MANAGE_STAFF = "manage_staff";
    public static final String MANAGE_TEAMS = "manage_teams";
    public static final String MANAGE_SETTINGS = "manage_settings";
    public static final String VIEW_AUDIT = "view_audit";
    public static final String ERASE_PERSONAL_DATA = "erase_personal_data";
    public static final String CREATE_ORGANISATION = "create_organisation";
    public static final String PLATFORM_STATS = "platform_stats";
    /** Handing a finished client to a relationship manager. Sales-side, and
     *  narrowed further on the server by lead ownership. */
    public static final String ASSIGN_RELATIONSHIP_MANAGER =
            "assign_relationship_manager";
    /** The RM's own screens, and accepting the "new opportunity" card. */
    public static final String MANAGE_RELATIONSHIPS = "manage_relationships";

    private static final Map<String, Set<String>> MATRIX = new HashMap<>();

    static {
        Set<String> salesAndAdmin =
                setOf(SALES_AGENT, SALES_LEAD, ORG_ADMIN);
        // Keeping in touch with a client is the relationship manager's whole
        // job, so they record meetings and write to clients — but they are
        // deliberately absent from MANAGE_LEADS and SEND_PROPOSAL, which is
        // why this is a separate set and not salesAndAdmin plus a member.
        Set<String> clientFacing = setOf(
                SALES_AGENT, SALES_LEAD, ORG_ADMIN, RELATIONSHIP_MANAGER);
        Set<String> everyoneOrg = setOf(
                SALES_AGENT, SALES_LEAD, ORG_ADMIN,
                OPERATIONS_AGENT, OPERATIONS_LEAD, RELATIONSHIP_MANAGER);

        MATRIX.put(RECORD_MEETING, clientFacing);
        MATRIX.put(SEND_PROPOSAL, salesAndAdmin);
        MATRIX.put(MANAGE_LEADS, salesAndAdmin);
        MATRIX.put(VIEW_LEADS, everyoneOrg);
        MATRIX.put(SEND_MESSAGES, clientFacing);
        MATRIX.put(MANAGE_TASKS, everyoneOrg);
        MATRIX.put(ASSIGN_RELATIONSHIP_MANAGER, salesAndAdmin);
        MATRIX.put(MANAGE_RELATIONSHIPS, setOf(RELATIONSHIP_MANAGER, ORG_ADMIN));
        MATRIX.put(CONFIRM_ASSIGNMENTS,
                setOf(SALES_LEAD, OPERATIONS_LEAD, ORG_ADMIN));
        MATRIX.put(VIEW_DEMOS, everyoneOrg);
        MATRIX.put(SCHEDULE_DEMOS, setOf(OPERATIONS_LEAD, ORG_ADMIN, SALES_LEAD));
        MATRIX.put(UPDATE_DEMO_STATUS, setOf(OPERATIONS_AGENT, OPERATIONS_LEAD, ORG_ADMIN));
        MATRIX.put(EDIT_PRICING, setOf(ORG_ADMIN));
        MATRIX.put(MANAGE_PROGRAMS, setOf(ORG_ADMIN));
        MATRIX.put(MANAGE_TEMPLATES, setOf(ORG_ADMIN));
        MATRIX.put(MANAGE_STAFF, setOf(ORG_ADMIN));
        MATRIX.put(MANAGE_TEAMS, setOf(ORG_ADMIN, OPERATIONS_LEAD));
        MATRIX.put(MANAGE_SETTINGS, setOf(ORG_ADMIN));
        MATRIX.put(VIEW_AUDIT, setOf(ORG_ADMIN));
        MATRIX.put(ERASE_PERSONAL_DATA, setOf(ORG_ADMIN));
        MATRIX.put(CREATE_ORGANISATION, setOf(SUPER_ADMIN));
        MATRIX.put(PLATFORM_STATS, setOf(SUPER_ADMIN));
    }

    private RoleGate() {
    }

    public static boolean has(@Nullable String role, @NonNull String permission) {
        if (role == null) return false;
        Set<String> allowed = MATRIX.get(permission);
        return allowed != null && allowed.contains(role);
    }

    /** Unknown/new role strings degrade to a generic member UX (05 §8). */
    public static boolean isKnownRole(@Nullable String role) {
        return SUPER_ADMIN.equals(role) || ORG_ADMIN.equals(role)
                || SALES_AGENT.equals(role) || SALES_LEAD.equals(role)
                || OPERATIONS_AGENT.equals(role) || OPERATIONS_LEAD.equals(role)
                || RELATIONSHIP_MANAGER.equals(role);
    }

    private static Set<String> setOf(String... roles) {
        return Collections.unmodifiableSet(new HashSet<>(Arrays.asList(roles)));
    }
}
