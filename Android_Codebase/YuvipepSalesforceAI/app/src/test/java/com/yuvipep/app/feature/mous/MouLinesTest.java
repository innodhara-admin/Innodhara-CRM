package com.yuvipep.app.feature.mous;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.MouDto;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;

/**
 * The contract screen's decisions, which are only testable because they are
 * not in the fragment.
 *
 * <p>Two of these guard a defect this project has already shipped once, on
 * the proposal side: the provenance card was hidden for a whole flow, and a
 * value the salesperson had typed themselves was labelled "From your
 * records". Neither could be caught while the decisions lived inside
 * {@code ProposalDetailFragment}, because a fragment needs Robolectric and
 * this suite is pure logic.
 */
public class MouLinesTest {

    private static MouDto.Filled entry(String source, String anchor,
                                       String brief, String key) {
        MouDto.Filled f = new MouDto.Filled();
        f.source = source;
        f.anchor = anchor;
        f.brief = brief;
        f.key = key;
        return f;
    }

    private static MouDto mou(MouDto.Filled... filled) {
        MouDto m = new MouDto();
        m.filled = new ArrayList<>(Arrays.asList(filled));
        return m;
    }

    // --- the card is shown at all -------------------------------------------

    @Test
    public void aContractWithFilledValuesHasAProvenanceCard() {
        assertTrue(MouLines.hasProvenance(
                mou(entry("ai", "Between", "the client's own name", "k"))));
    }

    @Test
    public void aContractWithNoProvenanceShowsNoCard() {
        assertFalse("a heading over nothing", MouLines.hasProvenance(mou()));
        MouDto missing = new MouDto();
        assertFalse("filled was never sent", MouLines.hasProvenance(missing));
        assertFalse("no contract at all", MouLines.hasProvenance(null));
    }

    // --- E1's defect, on a contract ------------------------------------------

    @Test
    public void aValueTheSalespersonTypedIsNotCreditedToTheDatabase() {
        assertEquals("You told me this", R.string.proposal_filled_user,
                MouLines.sourceLabel("user"));
        assertNotEquals("a value the salesperson typed was labelled "
                        + "\"From your records\"",
                R.string.proposal_filled_system, MouLines.sourceLabel("user"));
    }

    @Test
    public void theTemplatesOwnSuggestionIsNotCreditedToTheSalesperson() {
        assertEquals(R.string.proposal_filled_default,
                MouLines.sourceLabel("default"));
        assertNotEquals("the template's words were credited to the person",
                R.string.proposal_filled_user, MouLines.sourceLabel("default"));
        assertNotEquals(R.string.proposal_filled_system,
                MouLines.sourceLabel("default"));
    }

    @Test
    public void aValueWorkedOutFromTheRecordsSaysSo() {
        assertEquals(R.string.proposal_filled_ai, MouLines.sourceLabel("ai"));
    }

    @Test
    public void everySourceAContractFillProducesHasItsOwnLabel() {
        // The backend's filled_json for an MOU produces exactly these three.
        // If any two shared a label the screen would be telling a
        // salesperson the same thing about different provenance.
        int ai = MouLines.sourceLabel("ai");
        int user = MouLines.sourceLabel("user");
        int byDefault = MouLines.sourceLabel("default");
        assertNotEquals(ai, user);
        assertNotEquals(user, byDefault);
        assertNotEquals(ai, byDefault);
    }

    @Test
    public void anUnrecognisedSourceMakesTheMostModestClaimAvailable() {
        // Not a claim about where it came from that nobody can check.
        assertEquals(R.string.proposal_filled_system,
                MouLines.sourceLabel("something the backend added later"));
        assertEquals(R.string.proposal_filled_system,
                MouLines.sourceLabel(null));
    }

    // --- what a line is called -----------------------------------------------

    @Test
    public void aLineIsNamedByTheRowLabelTheSalespersonCanSee() {
        assertEquals("First Instalment", MouLines.heading(
                entry("user", "First Instalment", "the person said so", "k")));
    }

    @Test
    public void aLineWithNoRowLabelFallsBackToTheBriefAndThenTheKey() {
        assertEquals("the client's own name",
                MouLines.heading(entry("ai", "  ", "the client's own name", "k")));
        assertEquals("6d68f3ed6657",
                MouLines.heading(entry("ai", null, null, "6d68f3ed6657")));
        assertEquals("", MouLines.heading(entry("ai", null, null, null)));
        assertEquals("", MouLines.heading(null));
    }

    // --- the client screen's row ---------------------------------------------

    @Test
    public void aContractWithNoTitleIsStillNamed() {
        assertEquals("MOU", MouLines.rowTitle(null, "MOU"));
        assertEquals("MOU", MouLines.rowTitle("   ", "MOU"));
        assertEquals("Innovation Base Course MOU - Greenwood",
                MouLines.rowTitle("Innovation Base Course MOU - Greenwood",
                        "MOU"));
    }

    // --- whether a correction may still be offered ---------------------------

    @Test
    public void aDraftContractIsNotYetWithTheClient() {
        MouDto draft = new MouDto();
        draft.status = "draft";
        assertFalse(MouLines.isWithTheClient(draft));
        assertFalse(MouLines.isWithTheClient(null));
    }

    @Test
    public void aSentContractIsWithTheClientOnEitherSignal() {
        MouDto byStatus = new MouDto();
        byStatus.status = "sent";
        assertTrue("the status alone", MouLines.isWithTheClient(byStatus));

        // A send that recorded WHEN it went and then failed to move the
        // status still means the client is holding it. The backend refuses a
        // correction on either signal; the screen must not offer one it would
        // be refused.
        MouDto byTimestamp = new MouDto();
        byTimestamp.status = "draft";
        byTimestamp.sentAt = "2026-09-10T16:04:21";
        assertTrue("the timestamp alone", MouLines.isWithTheClient(byTimestamp));
    }

    // --- whether the contract can be opened and read -------------------------

    @Test
    public void aContractWithARenderedPdfCanBeOpened() {
        MouDto mou = new MouDto();
        mou.hasDocx = true;
        mou.hasPdf = true;
        assertTrue(MouLines.canBeRead(mou));
    }

    @Test
    public void aContractWhosePdfFailedToRenderCanStillBeOpened() {
        // The backend leaves pdf_path null when LibreOffice fails, on purpose
        // -- losing an approved contract over a converter hiccup is worse than
        // converting late -- and /download?format=pdf converts on the way out.
        // Gating the button on has_pdf would hide the document for exactly the
        // contracts whose conversion is the one that needs retrying.
        MouDto mou = new MouDto();
        mou.hasDocx = true;
        mou.hasPdf = false;
        assertTrue("the PDF is rendered on demand from the .docx",
                MouLines.canBeRead(mou));
    }

    @Test
    public void aContractWithNoFileStoredCannotBeOpened() {
        MouDto mou = new MouDto();
        mou.hasDocx = false;
        mou.hasPdf = false;
        assertFalse(MouLines.canBeRead(mou));

        // A backend that sent neither flag has told us nothing, and a button
        // that opens an error is worse than a button that is not there.
        assertFalse("neither flag was sent", MouLines.canBeRead(new MouDto()));
        assertFalse("no contract at all", MouLines.canBeRead(null));
    }

    @Test
    public void theVersionTagCountsTheRevisionsSoACorrectionIsNotServedStale() {
        MouDto mou = new MouDto();
        mou.revisions = new ArrayList<>();
        mou.revisions.add(new MouDto.Revision());
        assertEquals("1", MouLines.versionTag(mou));
        mou.revisions.add(new MouDto.Revision());
        assertNotEquals("a correction must not be served the cached render",
                "1", MouLines.versionTag(mou));
    }

    @Test
    public void aContractWithNoRevisionsStillHasAVersionTag() {
        assertEquals("0", MouLines.versionTag(new MouDto()));
        assertEquals("0", MouLines.versionTag(null));
    }
}
