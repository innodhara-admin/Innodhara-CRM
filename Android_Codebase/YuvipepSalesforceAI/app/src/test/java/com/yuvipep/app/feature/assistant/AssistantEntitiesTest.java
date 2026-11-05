package com.yuvipep.app.feature.assistant;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Which screen a chat card's "Open" goes to.
 *
 * <p>This was a fragment's private method until a contract went to the wrong
 * one: the owner built an MOU, tapped Open on the card that announced it, and
 * landed on the client's overview instead. The card's result carries both the
 * contract's id and the client's, and the client won because it was first in
 * a list nobody had revisited since before contracts existed.
 */
public class AssistantEntitiesTest {

    private static Map<String, Object> map(Object... pairs) {
        // Insertion-ordered, so a test can prove the CHOICE and not the
        // accident of a hash.
        Map<String, Object> out = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) {
            out.put(String.valueOf(pairs[i]), pairs[i + 1]);
        }
        return out;
    }

    @Test
    public void aBuiltContractOpensTheContractAndNotTheClient() {
        // Exactly what confirm_mou_values returns, in its own order.
        Map<String, Object> result = map(
                "created", true, "built_from", "mou_simple",
                "mou_id", "99a2b933", "title", "IBC Program MOU",
                "status", "draft", "lead_id", "87efb1be",
                "program_id", "b4487189", "has_pdf", true);
        assertArrayEquals(new String[]{"mou", "99a2b933"},
                AssistantEntities.of(result, null, "confirm_mou_values"));
    }

    @Test
    public void aClientCardStillOpensTheClient() {
        assertArrayEquals(new String[]{"lead", "87efb1be"},
                AssistantEntities.of(map("lead_id", "87efb1be"), null,
                        "get_lead"));
    }

    @Test
    public void aProposalStillOpensTheProposal() {
        assertArrayEquals(new String[]{"proposal", "p1"},
                AssistantEntities.of(map("proposal_id", "p1",
                        "lead_id", "87efb1be"), null, "get_proposal"));
    }

    @Test
    public void aBareIdIsReadFromTheToolsOwnName() {
        // create_proposal returns {"id": ...} and nothing else to go on.
        assertArrayEquals(new String[]{"proposal", "p9"},
                AssistantEntities.of(map("id", "p9"), null,
                        "create_proposal"));
    }

    @Test
    public void theArgumentsAreTriedWhenTheResultSaysNothing() {
        assertArrayEquals(new String[]{"lead", "L1"},
                AssistantEntities.of(map("ok", true), map("lead_id", "L1"),
                        "add_note"));
    }

    @Test
    public void nothingToOpenIsNothingToOpen() {
        assertNull(AssistantEntities.of(map("ok", true), null, "some_tool"));
        assertNull(AssistantEntities.of(null, null, "some_tool"));
        assertNull(AssistantEntities.of(map("lead_id", ""), null, "get_lead"));
        assertNull(AssistantEntities.of(map("lead_id", 7), null, "get_lead"));
    }

    @Test
    public void aHashOrderedResultStillOpensTheContract() {
        // The real payload arrives from Gson as a HashMap, whose iteration
        // order is its own business. The choice must come from the key list,
        // never from the order the keys happen to be in.
        Map<String, Object> result = new HashMap<>();
        result.put("lead_id", "87efb1be");
        result.put("mou_id", "99a2b933");
        assertArrayEquals(new String[]{"mou", "99a2b933"},
                AssistantEntities.of(result, null, "confirm_mou_values"));
    }
}
