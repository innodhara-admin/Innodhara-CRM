package com.yuvipep.app.core.auth;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;

import org.junit.Test;

import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;

/**
 * {@link RoleGate} against the backend's own {@code app/core/permissions.py}.
 *
 * <p>RoleGate says it is a "1:1 mirror". It was not: the backend had twenty
 * permissions and RoleGate nineteen, and the missing one was
 * {@code confirm_assignments} — added when F51 made confirming an assignment
 * batch a lead's job. Nothing noticed, because a mirror with a hole in it looks
 * exactly like a mirror until someone stands in front of the hole. What stood
 * there was the Home screen's assignment-batch card: an agent could see it,
 * open it, choose assignees and be refused by the server on the last tap.
 *
 * <p>The fixture is generated from the backend, not transcribed
 * ({@code contract/permissions.json}). A sweep is a claim made once; this is
 * the claim re-made on every build.
 */
public class RoleGateTest {

    private static Map<String, List<String>> backendMatrix() {
        InputStream in = RoleGateTest.class.getClassLoader()
                .getResourceAsStream("contract/permissions.json");
        if (in == null) fail("missing fixture: contract/permissions.json");
        return new Gson().fromJson(
                new InputStreamReader(in, StandardCharsets.UTF_8),
                new TypeToken<TreeMap<String, List<String>>>() {}.getType());
    }

    private static final String[] ROLES = {
            RoleGate.SUPER_ADMIN, RoleGate.ORG_ADMIN, RoleGate.SALES_AGENT,
            RoleGate.SALES_LEAD, RoleGate.OPERATIONS_AGENT, RoleGate.OPERATIONS_LEAD,
            RoleGate.RELATIONSHIP_MANAGER,
    };

    /** Which roles this app believes hold a permission. */
    private static Set<String> appRolesFor(String permission) {
        Set<String> held = new TreeSet<>();
        for (String role : ROLES) {
            if (RoleGate.has(role, permission)) held.add(role);
        }
        return held;
    }

    @Test
    public void everyBackendPermissionIsMirrored() {
        List<String> missing = new ArrayList<>();
        for (String permission : backendMatrix().keySet()) {
            if (appRolesFor(permission).isEmpty()) missing.add(permission);
        }
        Collections.sort(missing);
        assertTrue(
                "the backend gates these and RoleGate knows nothing about them, so "
                        + "the app cannot hide what a role may not do: " + missing,
                missing.isEmpty());
    }

    @Test
    public void everyMirroredPermissionHoldsTheSameRoles() {
        Map<String, List<String>> backend = backendMatrix();
        List<String> differences = new ArrayList<>();
        for (Map.Entry<String, List<String>> entry : backend.entrySet()) {
            Set<String> expected = new TreeSet<>(entry.getValue());
            Set<String> actual = appRolesFor(entry.getKey());
            if (!expected.equals(actual)) {
                differences.add(entry.getKey() + ": app=" + actual + " backend=" + expected);
            }
        }
        assertEquals("RoleGate and permissions.py disagree", "[]", differences.toString());
    }

    /**
     * The specific hole, named — so a future edit that drops it again fails
     * with this test's name rather than with a mystery 403 on a phone.
     */
    @Test
    public void confirmingAnAssignmentBatchIsALeadsJob() {
        assertTrue(RoleGate.has(RoleGate.SALES_LEAD, RoleGate.CONFIRM_ASSIGNMENTS));
        assertTrue(RoleGate.has(RoleGate.OPERATIONS_LEAD, RoleGate.CONFIRM_ASSIGNMENTS));
        assertTrue(RoleGate.has(RoleGate.ORG_ADMIN, RoleGate.CONFIRM_ASSIGNMENTS));
        assertFalse("an agent is offered the batch card and then refused",
                RoleGate.has(RoleGate.SALES_AGENT, RoleGate.CONFIRM_ASSIGNMENTS));
        assertFalse(RoleGate.has(RoleGate.OPERATIONS_AGENT, RoleGate.CONFIRM_ASSIGNMENTS));
    }

    /**
     * The relationship manager's boundary, named — the same way
     * {@code confirm_assignments} is named above, and for the same reason.
     *
     * <p>An RM looks after a client after the selling is finished. They record
     * meetings and write to the client, because that is the job; they must not
     * move the lead's sales state or price anything. Those two halves are easy
     * to conflate when someone later "tidies up" the matrix by folding the RM
     * into the sales set, and the generic diff tests above would still pass if
     * the backend were tidied the same wrong way on the same day.
     */
    @Test
    public void aRelationshipManagerKeepsInTouchButDoesNotSell() {
        assertTrue(RoleGate.has(RoleGate.RELATIONSHIP_MANAGER, RoleGate.RECORD_MEETING));
        assertTrue(RoleGate.has(RoleGate.RELATIONSHIP_MANAGER, RoleGate.SEND_MESSAGES));
        assertTrue(RoleGate.has(RoleGate.RELATIONSHIP_MANAGER, RoleGate.VIEW_LEADS));
        assertTrue(RoleGate.has(RoleGate.RELATIONSHIP_MANAGER,
                RoleGate.MANAGE_RELATIONSHIPS));

        assertFalse("an RM must not move a lead through the sales states",
                RoleGate.has(RoleGate.RELATIONSHIP_MANAGER, RoleGate.MANAGE_LEADS));
        assertFalse("an RM must not price work",
                RoleGate.has(RoleGate.RELATIONSHIP_MANAGER, RoleGate.SEND_PROPOSAL));
        assertFalse("handing a client over is the sales side's call",
                RoleGate.has(RoleGate.RELATIONSHIP_MANAGER,
                        RoleGate.ASSIGN_RELATIONSHIP_MANAGER));

        assertTrue("a new role the app knows must not fall through to the "
                        + "generic member experience",
                RoleGate.isKnownRole(RoleGate.RELATIONSHIP_MANAGER));
    }

    @Test
    public void anUnknownRoleOrPermissionIsRefusedRatherThanAllowed() {
        assertFalse(RoleGate.has("archbishop", RoleGate.MANAGE_LEADS));
        assertFalse(RoleGate.has(RoleGate.ORG_ADMIN, "launch_the_missiles"));
        assertFalse(RoleGate.has(null, RoleGate.MANAGE_LEADS));
    }

    @Test
    public void theSuperAdminHoldsNoOrganisationPermission() {
        // deps.py `get_org_context` refuses super_admin outright; the app must
        // not offer org actions it will certainly be refused.
        assertFalse(RoleGate.has(RoleGate.SUPER_ADMIN, RoleGate.VIEW_LEADS));
        assertFalse(RoleGate.has(RoleGate.SUPER_ADMIN, RoleGate.MANAGE_TASKS));
        assertFalse(RoleGate.has(RoleGate.SUPER_ADMIN, RoleGate.MANAGE_SETTINGS));
    }
}
