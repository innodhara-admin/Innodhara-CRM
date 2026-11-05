package com.yuvipep.app.core.net;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import com.yuvipep.app.core.net.dto.ApprovalDto;
import com.yuvipep.app.core.net.dto.DemoDto;
import com.yuvipep.app.core.net.dto.DemoTeamDto;
import com.yuvipep.app.core.net.dto.FollowUpDto;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.net.dto.LeadDto;
import com.yuvipep.app.core.net.dto.LoginResponse;
import com.yuvipep.app.core.net.dto.MeResponse;
import com.yuvipep.app.core.net.dto.MessageDto;
import com.yuvipep.app.core.net.dto.MouDto;
import com.yuvipep.app.core.net.dto.NotificationDto;
import com.yuvipep.app.core.net.dto.OrgUserDto;
import com.yuvipep.app.core.net.dto.ProjectDetailDto;
import com.yuvipep.app.core.net.dto.ProjectDto;
import com.yuvipep.app.core.net.dto.ProposalDetailDto;
import com.yuvipep.app.core.net.dto.ProposedAssignmentDto;
import com.yuvipep.app.core.net.dto.TaskDto;

import org.junit.Test;

import java.io.InputStream;
import java.io.InputStreamReader;
import java.lang.reflect.Type;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * The app's DTOs against real backend JSON.
 *
 * <p>Fixtures under {@code src/test/resources/contract/} were captured from a
 * live, seeded backend. Every list fixture holds at least one row on purpose:
 * an empty array parses under any shape and would prove nothing.
 *
 * <p><b>What this catches that nothing else did.</b> Gson does not complain
 * about a field it cannot find — it leaves it null and the screen renders a
 * blank. So a backend rename reaches a user as "why is this empty?" rather than
 * as an error. Asserting on the fields the screens actually read turns that
 * into a failing build. It is the app-side twin of the setup console's
 * {@code reads.ts} plus its committed fixtures.
 *
 * <p>Re-capture with {@code capture_contract.py} against a seeded backend when
 * the API changes on purpose.
 */
public class ContractTest {

    private static final Gson GSON = new Gson();

    private static <T> T parse(String fixture, Class<T> type) {
        return GSON.fromJson(reader(fixture), type);
    }

    private static <T> List<T> parseList(String fixture, Type listType) {
        return GSON.fromJson(reader(fixture), listType);
    }

    private static InputStreamReader reader(String fixture) {
        InputStream in = ContractTest.class.getClassLoader()
                .getResourceAsStream("contract/" + fixture);
        if (in == null) fail("missing fixture: contract/" + fixture);
        return new InputStreamReader(in, StandardCharsets.UTF_8);
    }

    // ── auth ────────────────────────────────────────────────────────────────

    @Test
    public void loginResponseCarriesTheSessionTheAppStores() {
        LoginResponse login = parse("login.json", LoginResponse.class);
        assertNotNull("access_token", login.accessToken);
        assertNotNull("user_id", login.userId);
        assertNotNull("role", login.role);
        assertNotNull("name", login.name);
    }

    @Test
    public void meCarriesIdentityAndBranding() {
        MeResponse me = parse("me.json", MeResponse.class);
        assertNotNull("user_id", me.userId);
        assertNotNull("email", me.email);
        assertNotNull("role", me.role);
        assertNotNull("org_id", me.orgId);
        assertNotNull("org_name", me.orgName);
    }

    /**
     * The field the task list buckets dates in. Without it the app falls back
     * to the phone's zone, which is the mix {@code app/core/clock.py} exists to
     * end — so its absence must fail here rather than quietly on a screen.
     */
    @Test
    public void meCarriesTheOrganisationsTimezone() {
        MeResponse me = parse("me.json", MeResponse.class);
        assertNotNull("org_timezone is missing — the app would bucket dates in "
                + "the phone's zone and disagree with the server", me.orgTimezone);
    }

    // ── the lists behind each tab ───────────────────────────────────────────

    /**
     * My Tasks is built from TWO sources and they do not carry the same fields.
     * {@code TasksRepository.myTasks} walks every project for the rich rows and
     * unions in whatever {@code GET /action-items} adds — the project-less
     * tasks. Both contracts are pinned here, separately, because conflating
     * them is how a screen ends up reading a field one of its sources never
     * sends.
     */
    @Test
    public void theThinTaskListCarriesWhatItPromises() {
        List<TaskDto> tasks = parseList("action_items.json",
                new TypeToken<List<TaskDto>>() {}.getType());
        assertFalse("fixture has no rows", tasks.isEmpty());
        TaskDto t = tasks.get(0);
        assertNotNull("id", t.id);
        assertNotNull("title", t.title);
        assertNotNull("status", t.status);
        assertNotNull("owner_id", t.assigneeId);
        assertNotNull("due_date — every bucket depends on it", t.dueDate);
    }

    /**
     * The gap, pinned so it stays visible.
     *
     * <p>{@code GET /action-items} sends thirteen fields and {@code TaskDto}
     * declares twenty-two. {@code priority} and {@code blocked} are among the
     * missing ones, and My Tasks uses both: it pins P1 within each group and it
     * has a Blocked section. A project-less task therefore always sorts last
     * (rank 3, the fallback) and can <b>never</b> reach the Blocked section,
     * however blocked it is.
     *
     * <p>{@code MyTasksFragment}'s own comment accepts this — "the richer
     * fields left blank rather than guessed" — so this test records the
     * decision rather than failing it. If the backend ever widens the route,
     * this test fails and the compensating union can go.
     */
    @Test
    public void theThinTaskListIsKnownlyMissingPriorityAndBlocked() {
        List<TaskDto> tasks = parseList("action_items.json",
                new TypeToken<List<TaskDto>>() {}.getType());
        TaskDto t = tasks.get(0);
        assertNull("GET /action-items now sends priority — My Tasks can stop "
                + "compensating, and this test should be deleted", t.priority);
        assertFalse("GET /action-items now sends blocked — see above",
                t.blocked);
    }

    /** The rich source, which is what the buckets and the P1 pin rely on. */
    @Test
    public void projectTasksCarryPriorityAndBlocked() {
        ProjectDetailDto detail = parse("project_detail.json", ProjectDetailDto.class);
        assertNotNull("project_detail has no tasks[]", detail.tasks);
        assertFalse("project_detail.tasks[] is empty", detail.tasks.isEmpty());
        TaskDto t = detail.tasks.get(0);
        assertNotNull("priority — My Tasks pins P1 on it", t.priority);
        assertNotNull("phase", t.phase);
        assertNotNull("due_date", t.dueDate);
    }

    @Test
    public void notificationsCarryWhatTheCentreRenders() {
        List<NotificationDto> rows = parseList("notifications.json",
                new TypeToken<List<NotificationDto>>() {}.getType());
        assertFalse(rows.isEmpty());
        NotificationDto notification = rows.get(0);
        assertNotNull("id", notification.id);
        assertNotNull("title", notification.title);
    }

    @Test
    public void leadsCarryWhatTheListRenders() {
        List<LeadDto> leads = parseList("leads.json",
                new TypeToken<List<LeadDto>>() {}.getType());
        assertFalse(leads.isEmpty());
        assertNotNull("id", leads.get(0).id);
        assertNotNull("name", leads.get(0).name);
        assertNotNull("state", leads.get(0).state);
    }

    @Test
    public void leadDetailParses() {
        LeadDetailResponse detail = parse("lead_detail.json", LeadDetailResponse.class);
        assertNotNull(detail);
    }

    @Test
    public void projectsCarryWhatTheListRenders() {
        List<ProjectDto> projects = parseList("projects.json",
                new TypeToken<List<ProjectDto>>() {}.getType());
        assertFalse(projects.isEmpty());
        assertNotNull("id", projects.get(0).id);
        assertNotNull("name", projects.get(0).name);
    }

    @Test
    public void projectDetailParses() {
        ProjectDetailDto detail = parse("project_detail.json", ProjectDetailDto.class);
        assertNotNull(detail);
    }

    @Test
    public void approvalsCarryWhatTheInboxRenders() {
        List<ApprovalDto> approvals = parseList("approvals.json",
                new TypeToken<List<ApprovalDto>>() {}.getType());
        assertFalse(approvals.isEmpty());
        assertNotNull("id", approvals.get(0).id);
        assertNotNull("entity_type", approvals.get(0).entityType);
    }

    @Test
    public void messagesCarryWhatTheInboxRenders() {
        List<MessageDto> messages = parseList("messages.json",
                new TypeToken<List<MessageDto>>() {}.getType());
        assertFalse(messages.isEmpty());
        assertNotNull("id", messages.get(0).id);
        assertNotNull("status", messages.get(0).status);
    }

    @Test
    public void demosCarryWhatTheCalendarRenders() {
        List<DemoDto> demos = parseList("demos.json",
                new TypeToken<List<DemoDto>>() {}.getType());
        assertFalse(demos.isEmpty());
        assertNotNull("id", demos.get(0).id);
        assertNotNull("date", demos.get(0).date);
        assertNotNull("status", demos.get(0).status);
    }

    @Test
    public void followupsCarryWhatTheQueueRenders() {
        List<FollowUpDto> followups = parseList("followups.json",
                new TypeToken<List<FollowUpDto>>() {}.getType());
        assertFalse(followups.isEmpty());
        assertNotNull("id", followups.get(0).id);
        assertNotNull("due_date", followups.get(0).dueDate);
    }

    @Test
    public void staffCarryWhatTheDirectoryRenders() {
        List<OrgUserDto> staff = parseList("admin_users.json",
                new TypeToken<List<OrgUserDto>>() {}.getType());
        assertFalse(staff.isEmpty());
        assertNotNull("id", staff.get(0).id);
        assertNotNull("name", staff.get(0).name);
        assertNotNull("role", staff.get(0).role);
    }

    @Test
    public void demoTeamsCarryWhatTheBookingScreenRenders() {
        List<DemoTeamDto> teams = parseList("admin_demo_teams.json",
                new TypeToken<List<DemoTeamDto>>() {}.getType());
        assertFalse(teams.isEmpty());
        assertNotNull("id", teams.get(0).id);
        assertNotNull("name", teams.get(0).name);
    }

    @Test
    public void proposedAssignmentsCarryWhatTheBatchScreenRenders() {
        List<ProposedAssignmentDto> rows = parseList("assignments_proposed.json",
                new TypeToken<List<ProposedAssignmentDto>>() {}.getType());
        assertFalse(rows.isEmpty());
        assertNotNull("id", rows.get(0).id);
        assertNotNull("action_item_id", rows.get(0).actionItemId);
    }

    /**
     * The task list's dates, end to end: the string the backend really sent,
     * through the app's real parser, into the bucket the screen shows.
     */
    @Test
    public void aRealTaskLandsInTheBucketTheServerWouldName() {
        List<TaskDto> tasks = parseList("action_items.json",
                new TypeToken<List<TaskDto>>() {}.getType());
        MeResponse me = parse("me.json", MeResponse.class);
        TaskDto t = tasks.get(0);

        java.time.ZoneId zone =
                com.yuvipep.app.core.util.WorkDay.zoneOf(me.orgTimezone);
        java.time.LocalDate due =
                com.yuvipep.app.core.util.WorkDay.localDate(t.dueDate, zone);
        assertNotNull("the captured due_date did not parse: " + t.dueDate, due);

        // Seeded at 2026-08-27 20:00 UTC, which is 01:30 on the 28th in
        // Asia/Kolkata — the case the whole clock change is about.
        assertEquals(java.time.LocalDate.of(2026, 8, 28), due);
        assertEquals(com.yuvipep.app.core.util.WorkDay.Bucket.TODAY,
                com.yuvipep.app.core.util.WorkDay.bucketOf(
                        t.dueDate, due, zone, t.blocked));
        assertTrue("Asia/Kolkata expected in the fixture",
                "Asia/Kolkata".equals(me.orgTimezone));
    }

    // ── the proposal detail screen ──────────────────────────────────────────

    /**
     * {@code proposal_detail.json} was produced by the backend itself rather
     * than typed here: the envelope by {@code proposals._proposal_dict} and
     * {@code get_proposal}'s own revisions block, and the {@code filled} array
     * by a real {@code docx/fill.py::apply} run over {@code Essential
     * Lab.docx}. Only the values are invented, and nothing below asserts on a
     * value the app does not read.
     */
    @Test
    public void proposalDetailCarriesWhatTheScreenRenders() {
        ProposalDetailDto p = parse("proposal_detail.json", ProposalDetailDto.class);
        assertNotNull("id", p.id);
        assertNotNull("title", p.title);
        assertNotNull("status", p.status);
        assertNotNull("content_md", p.contentMd);
        assertNotNull("line_items", p.lineItems);
        assertNotNull("total_amount", p.totalAmount);
        assertNotNull("currency", p.currency);
        assertNotNull("template_version", p.templateVersion);
        assertNotNull("revisions", p.revisions);
        assertEquals("line_total is what the pricing rows show",
                240000.0,
                ((Number) p.lineItems.get(0).get("line_total")).doubleValue(),
                0.001);
    }

    /**
     * The two fields Task 22 added.
     *
     * <p>Gson does not complain about a field it cannot find — it leaves it
     * null, {@code renderFilled} takes its early return, and the card simply
     * never appears. A backend rename of {@code template_kind} or
     * {@code filled} would therefore reach a salesperson as a section that
     * silently stopped existing, on the one screen whose job is to say which
     * paragraphs the model wrote.
     */
    @Test
    public void aDocumentProposalSaysWhichSectionsTheModelWrote() {
        ProposalDetailDto p = parse("proposal_detail.json", ProposalDetailDto.class);
        assertEquals("template_kind", "docx", p.templateKind);
        assertNotNull("filled", p.filled);
        assertFalse("filled is empty, so this proves nothing", p.filled.isEmpty());
        for (ProposalDetailDto.Filled f : p.filled) {
            assertNotNull("key", f.key);
            assertNotNull("kind", f.kind);
            assertNotNull("source", f.source);
        }
    }

    /**
     * The three values of {@code source} the screen branches on, all present in
     * one real fill. {@code "unfilled"} is the one that matters: it is a gap in
     * the document that nothing else on the screen would show, and
     * {@code renderFilled} sorts those to the top for exactly that reason.
     */
    @Test
    public void everySourceTheScreenBranchesOnIsRepresented() {
        ProposalDetailDto p = parse("proposal_detail.json", ProposalDetailDto.class);
        boolean ai = false, system = false, unfilled = false;
        String unfilledText = null;
        for (ProposalDetailDto.Filled f : p.filled) {
            if ("ai".equals(f.source)) ai = true;
            if ("system".equals(f.source)) system = true;
            if ("unfilled".equals(f.source)) {
                unfilled = true;
                unfilledText = f.text;
            }
        }
        assertTrue("no ai-written placeholder in the fixture", ai);
        assertTrue("no system-filled placeholder in the fixture", system);
        assertTrue("no unfilled placeholder in the fixture", unfilled);
        // The backend sends "" for an unfilled placeholder, which is why the
        // screen substitutes proposal_filled_empty_hint rather than showing it.
        assertEquals("an unfilled placeholder carries no text", "", unfilledText);
    }

    /**
     * The simple flow: the template author writes the tags into the Word file
     * and the assistant fills them with the salesperson, so a value comes from
     * the model, from the person, or from the author's own suggestion.
     *
     * <p>{@code proposal_detail_simple.json} was captured from a real backend
     * fill, not typed here. Two things it guards. First,
     * {@code template_kind} is {@code "docx_simple"} and NOT {@code "docx"} --
     * {@code renderFilled} gated the whole card on the latter and showed
     * nothing at all for these proposals. Second, {@code source} carries
     * {@code "user"} and {@code "default"}, which the screen used to fall
     * through to "From your records" -- telling the salesperson that a figure
     * they typed themselves had come out of the database.
     */
    @Test
    public void aSimpleFlowProposalSaysWhoSuppliedEachValue() {
        ProposalDetailDto p = parse("proposal_detail_simple.json",
                ProposalDetailDto.class);
        assertEquals("template_kind", "docx_simple", p.templateKind);
        assertNotNull("filled", p.filled);
        assertFalse("filled is empty, so this proves nothing", p.filled.isEmpty());

        boolean ai = false, user = false, byDefault = false;
        for (ProposalDetailDto.Filled f : p.filled) {
            assertNotNull("key", f.key);
            assertNotNull("kind", f.kind);
            assertNotNull("source", f.source);
            assertNotNull("text", f.text);
            if ("ai".equals(f.source)) {
                ai = true;
                // A model-written value cites the fact it came from (D14); a
                // value with no citation never reaches a document filled.
                assertNotNull("an ai value with no citation", f.citation);
            }
            if ("user".equals(f.source)) user = true;
            if ("default".equals(f.source)) byDefault = true;
            // No number reaches one of these documents unless Python computed
            // it from the locked rate card or a person typed it. Nothing in a
            // simple-flow fill is computed, so this is null throughout.
            assertNull("computed_by should be null in the simple flow",
                    f.computedBy);
        }
        assertTrue("no model-written value in the fixture", ai);
        assertTrue("no salesperson-supplied value in the fixture", user);
        assertTrue("no template-default value in the fixture", byDefault);
    }

    /**
     * The tag's anchor is the row label of the cell it sits in -- "Laptops",
     * "Interactive Panel" -- and the simple-flow screen uses it as each line's
     * heading, because the brief holds the model's reasoning and would read as
     * "the salesperson said so" on every row.
     */
    @Test
    public void aSimpleFlowValueSaysWhereInTheDocumentItGoes() {
        ProposalDetailDto p = parse("proposal_detail_simple.json",
                ProposalDetailDto.class);
        for (ProposalDetailDto.Filled f : p.filled) {
            assertNotNull("anchor", f.anchor);
            assertFalse("an anchor that names nowhere", f.anchor.trim().isEmpty());
        }
    }

    /**
     * A memorandum of understanding, captured from a REAL build: upload,
     * resolve, answer, review, approve, correct, then GET /mous/{id} through
     * the route the app calls.
     *
     * <p><b>What it guards.</b> All three provenance labels are present --
     * {@code "ai"}, {@code "user"} and {@code "default"} -- because a fixture
     * whose every value is {@code "user"} cannot catch E1's defect coming
     * back, which was that {@code "user"} and {@code "default"} fell through
     * to "From your records" and told a salesperson that a figure they typed
     * themselves had come out of the database.
     */
    @Test
    public void anMouSaysWhoSuppliedEachValue() {
        MouDto m = parse("mou_detail.json", MouDto.class);
        assertNotNull("id", m.id);
        assertNotNull("lead_id", m.leadId);
        assertNotNull("title", m.title);
        assertEquals("status", "draft", m.status);
        assertNotNull("content_md", m.contentMd);
        assertNotNull("filled", m.filled);
        assertFalse("filled is empty, so this proves nothing",
                m.filled.isEmpty());

        boolean ai = false, user = false, byDefault = false;
        for (MouDto.Filled f : m.filled) {
            assertNotNull("key", f.key);
            assertNotNull("kind", f.kind);
            assertNotNull("source", f.source);
            assertNotNull("text", f.text);
            if ("ai".equals(f.source)) {
                ai = true;
                // D14: a model-written value cites the fact it came from, and
                // a value with no citation never reaches a document filled.
                assertNotNull("an ai value with no citation", f.citation);
            }
            if ("user".equals(f.source)) user = true;
            if ("default".equals(f.source)) byDefault = true;
            // No number reaches one of these documents unless a person typed
            // it. Nothing in an MOU fill is computed by the app or the model.
            assertNull("computed_by should be null in an MOU fill",
                    f.computedBy);
        }
        assertTrue("no model-written value in the fixture", ai);
        assertTrue("no salesperson-supplied value in the fixture", user);
        assertTrue("no template-default value in the fixture", byDefault);
    }

    /**
     * A contract carries NO commercial fields, and their absence is the
     * point: the backend's mou_documents table has no such columns, so a
     * screen that sums a client's documents cannot pick one up by accident.
     *
     * <p>Gson cannot assert an absence for us -- it leaves an unknown field
     * null -- so this reads the raw JSON and asserts the keys are not there
     * at all. A backend that started sending {@code total_amount} would
     * otherwise reach a user as a number nobody computed.
     */
    @Test
    public void anMouCarriesNoCommercialFields() {
        java.util.Map<?, ?> raw = GSON.fromJson(reader("mou_detail.json"),
                java.util.Map.class);
        for (String absent : new String[]{"total_amount", "line_items",
                "currency", "pricing_version", "project_id"}) {
            assertFalse("a contract must not carry " + absent,
                    raw.containsKey(absent));
        }
        // And the two things the app DOES need in order to open the file.
        MouDto m = parse("mou_detail.json", MouDto.class);
        assertEquals(Boolean.TRUE, m.hasDocx);
        assertEquals(Boolean.TRUE, m.hasPdf);
    }

    /**
     * The revisions arrive newest first, and revision 1 is the contract as it
     * was first built. Once the file has been written anew this record is the
     * only place the superseded wording survives.
     */
    @Test
    public void anMouListsWhatItSaidBeforeItWasCorrected() {
        MouDto m = parse("mou_detail.json", MouDto.class);
        assertNotNull("revisions", m.revisions);
        assertEquals("the fixture needs two to show an order", 2,
                m.revisions.size());
        assertEquals(Integer.valueOf(2), m.revisions.get(0).revisionNo);
        assertEquals(Integer.valueOf(1), m.revisions.get(1).revisionNo);
        for (MouDto.Revision r : m.revisions) {
            assertNotNull("instruction", r.instruction);
            assertNotNull("edited_at", r.editedAt);
        }
    }

    /**
     * The client screen reads contracts from their OWN key.
     *
     * <p>An MOU is signed after a proposal is accepted, so one merged into
     * {@code proposals} would arrive on an already-closed deal. The backend
     * keeps the two lists separate; this asserts the app parses them
     * separately, which is the half a rename would break silently.
     */
    @Test
    public void aClientsContractsAreASeparateListFromTheirProposals() {
        LeadDetailResponse lead = parse("lead_detail_with_mou.json",
                LeadDetailResponse.class);
        assertNotNull("mous", lead.mous);
        assertFalse("mous is empty, so this proves nothing",
                lead.mous.isEmpty());

        LeadDetailResponse.MouRow row = lead.mous.get(0);
        assertNotNull("id", row.id);
        assertNotNull("title", row.title);
        assertNotNull("status", row.status);
        assertNotNull("created_at", row.createdAt);

        // The contract is NOT among the proposals. `proposals` is empty in
        // this fixture, and lead_detail.json already covers a lead that has
        // one -- what matters here is that the contract did not land there.
        if (lead.proposals != null) {
            for (LeadDetailResponse.ProposalRow p : lead.proposals) {
                assertNotEquals("a contract is listed among the proposals",
                        row.id, p.id);
            }
        }
    }
}
