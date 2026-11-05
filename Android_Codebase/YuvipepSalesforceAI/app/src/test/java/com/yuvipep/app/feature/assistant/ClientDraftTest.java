package com.yuvipep.app.feature.assistant;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.google.gson.Gson;
import com.yuvipep.app.core.net.dto.AssistantDtos;

import org.junit.Test;

import java.util.List;
import java.util.Map;

/**
 * The client Jarvis builds up by conversation, read from the responses the
 * backend documents (docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md §2.2),
 * parsed by the same Gson the app's Retrofit uses.
 */
public class ClientDraftTest {

    private static final String CONFIRM_TURN = "{"
            + "\"agent\": \"client\","
            + "\"reply\": \"Got it, Pune. So: Bal Bhavan Public School in Pune, owned by Priya Nair. Anything else, or shall I create it?\","
            + "\"actions\": [{"
            + "  \"tool\": \"create_client\", \"args\": {\"stage\": \"confirm\"},"
            + "  \"ok\": false, \"outcome\": \"needs_confirmation\","
            + "  \"error\": \"Got it, Pune.\", \"question\": \"Got it, Pune.\","
            + "  \"candidates\": [\"Create it\", \"Cancel\"],"
            + "  \"details\": {"
            + "    \"kind\": \"client_draft\", \"stage\": \"confirm\","
            + "    \"name\": \"Bal Bhavan Public School\", \"owner\": \"Priya Nair\","
            + "    \"city\": \"Pune\", \"source\": null, \"website\": null, \"notes\": null,"
            + "    \"address\": null, \"region\": null, \"contact\": null"
            + "  }"
            + "}],"
            + "\"pending_approvals\": [], \"session_id\": \"abc12345\"}";

    private static final String CREATED_TURN = "{"
            + "\"agent\": \"client\","
            + "\"reply\": \"Done\","
            + "\"actions\": [{"
            + "  \"tool\": \"create_client\","
            + "  \"args\": {\"stage\": \"confirm\", \"name\": \"Bal Bhavan Public School\"},"
            + "  \"ok\": true,"
            + "  \"result\": {\"lead_id\": \"dcf2\", \"name\": \"Bal Bhavan Public School\","
            + "     \"state\": \"cold_calling\", \"owner_id\": \"48c3\", \"owner\": \"Priya Nair\","
            + "     \"contact_id\": null}"
            + "}],"
            + "\"pending_approvals\": [], \"session_id\": \"abc12345\"}";

    private static Map<String, Object> firstAction(String json) {
        AssistantDtos.CommandResponse response =
                new Gson().fromJson(json, AssistantDtos.CommandResponse.class);
        return response.actions.get(0);
    }

    @Test
    public void theReadBackCardCarriesTheDraft() {
        ClientDraft draft = ClientDraft.of(firstAction(CONFIRM_TURN));
        assertNotNull(draft);
        assertEquals(ClientDraft.STAGE_CONFIRM, draft.stage);
        assertEquals("Ready to create", draft.stepLabel());

        List<String[]> rows = draft.rows("You");
        assertEquals(3, rows.size());   // nulls are not shown as empty rows
        assertArrayEquals(new String[]{"Name", "Bal Bhavan Public School"}, rows.get(0));
        assertArrayEquals(new String[]{"Owner", "Priya Nair"}, rows.get(1));
        assertArrayEquals(new String[]{"City", "Pune"}, rows.get(2));
    }

    @Test
    public void theSpeakerOwningItReadsAsYou() {
        Map<String, Object> action = firstAction(CONFIRM_TURN.replace(
                "\"owner\": \"Priya Nair\"", "\"owner\": \"you\""));
        ClientDraft draft = ClientDraft.of(action);
        assertNotNull(draft);
        assertArrayEquals(new String[]{"Owner", "You"}, draft.rows("You").get(1));
    }

    @Test
    public void aContactShowsWithItsTitle() {
        Map<String, Object> action = firstAction(CONFIRM_TURN.replace(
                "\"contact\": null",
                "\"contact\": {\"name\": \"Anita\", \"title\": \"Principal\", \"phone\": null}"));
        ClientDraft draft = ClientDraft.of(action);
        assertNotNull(draft);
        assertEquals("Anita (Principal)", draft.contact);
    }

    @Test
    public void anotherAgentsQuestionIsNotADraft() {
        Map<String, Object> action = firstAction(CONFIRM_TURN.replace(
                "\"kind\": \"client_draft\"", "\"kind\": \"proposal_fill\""));
        assertNull(ClientDraft.of(action));
        assertNull(ClientDraft.of(null));
    }

    @Test
    public void everyStageHasWords() {
        String[] stages = {"name", "owner", "owner_suggested", "optional", "confirm",
                "spell_check", "something_new"};
        for (String stage : stages) {
            ClientDraft draft = ClientDraft.of(firstAction(CONFIRM_TURN.replace(
                    "\"stage\": \"confirm\",    \"name\"", "\"stage\": \"" + stage
                            + "\",    \"name\"")));
            assertNotNull(stage, draft);
            assertEquals(stage, draft.stage);
            assertFalse(stage, draft.stepLabel().isEmpty());
        }
    }

    @Test
    public void onlyASuccessfulCreateCountsAsCreated() {
        Map<String, Object> created = firstAction(CREATED_TURN);
        assertTrue(ClientDraft.isCreated(created));
        assertEquals("Bal Bhavan Public School", ClientDraft.createdName(created));
        // And the card still opens the new lead.
        assertArrayEquals(new String[]{"lead", "dcf2"},
                AssistantEntities.of(created.get("result"), created.get("args"),
                        "create_client"));

        assertFalse(ClientDraft.isCreated(firstAction(CONFIRM_TURN)));
        assertFalse(ClientDraft.isCreated(firstAction(
                CREATED_TURN.replace("\"ok\": true", "\"ok\": false"))));
    }
}
