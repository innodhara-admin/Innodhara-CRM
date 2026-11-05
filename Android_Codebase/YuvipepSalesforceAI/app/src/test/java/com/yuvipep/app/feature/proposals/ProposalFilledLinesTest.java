package com.yuvipep.app.feature.proposals;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.ProposalDetailDto;

import org.junit.Test;

/**
 * The card that tells a salesperson where each value in their proposal came
 * from. Both defects these tests pin were live: a {@code docx_simple}
 * proposal showed no card at all, and a value the person had typed themselves
 * was labelled as having come out of the organisation's records.
 */
public class ProposalFilledLinesTest {

    private static ProposalDetailDto.Filled entry(String source, String text,
                                                  String brief, String anchor) {
        ProposalDetailDto.Filled f = new ProposalDetailDto.Filled();
        f.key = "6d68f3ed6657";
        f.kind = "ask";
        f.source = source;
        f.text = text;
        f.brief = brief;
        f.anchor = anchor;
        return f;
    }

    @Test
    public void bothDocumentFlowsShowWhatWentIntoTheProposal() {
        assertTrue("the complex flow",
                ProposalFilledLines.isDocumentProposal("docx"));
        assertTrue("the simple flow -- this card was hidden entirely",
                ProposalFilledLines.isDocumentProposal("docx_simple"));
    }

    @Test
    public void aMarkdownProposalHasNoDocumentToAccountFor() {
        assertFalse(ProposalFilledLines.isDocumentProposal("markdown"));
        assertFalse(ProposalFilledLines.isDocumentProposal(null));
        assertFalse(ProposalFilledLines.isDocumentProposal(""));
    }

    @Test
    public void aValueTheSalespersonTypedIsNotCalledARecord() {
        assertEquals(R.string.proposal_filled_user,
                ProposalFilledLines.sourceLabel("user"));
        assertEquals(R.string.proposal_filled_default,
                ProposalFilledLines.sourceLabel("default"));
    }

    @Test
    public void theOlderSourcesKeepTheLabelsTheyHad() {
        assertEquals(R.string.proposal_filled_ai,
                ProposalFilledLines.sourceLabel("ai"));
        assertEquals(R.string.proposal_filled_system,
                ProposalFilledLines.sourceLabel("system"));
        assertEquals(R.string.proposal_filled_unfilled,
                ProposalFilledLines.sourceLabel("unfilled"));
    }

    /**
     * A source this app has never heard of must not be flattered into
     * "From your records" — but it has to say something, and "from your
     * records" is the only label that is merely vague rather than actively
     * misleading. Pinned so a future source is a deliberate decision here
     * rather than an accident.
     */
    @Test
    public void anUnknownSourceFallsBackRatherThanCrashing() {
        assertEquals(R.string.proposal_filled_system,
                ProposalFilledLines.sourceLabel("something_new"));
        assertEquals(R.string.proposal_filled_system,
                ProposalFilledLines.sourceLabel(null));
    }

    @Test
    public void aSimpleFlowLineIsNamedByWhereInTheDocumentItGoes() {
        ProposalDetailDto.Filled f =
                entry("user", "8 Units", "the salesperson said so", "Laptops");
        assertEquals("Laptops",
                ProposalFilledLines.heading("docx_simple", f));
    }

    @Test
    public void aComplexFlowLineIsStillNamedByItsBrief() {
        ProposalDetailDto.Filled f = entry("ai", "Dear Greenwood,",
                "Greet the school by name.", "body[2]");
        assertEquals("Greet the school by name.",
                ProposalFilledLines.heading("docx", f));
    }

    @Test
    public void aLineWithNothingToCallItFallsBackToItsKey() {
        assertEquals("6d68f3ed6657",
                ProposalFilledLines.heading("docx_simple",
                        entry("user", "8 Units", "  ", "  ")));
        assertEquals("6d68f3ed6657",
                ProposalFilledLines.heading("docx", entry("ai", "x", null, null)));
    }
}
