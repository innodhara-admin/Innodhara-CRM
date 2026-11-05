package com.yuvipep.app.feature.assistant;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.Map;

/**
 * Which screen a chat card's "Open" goes to.
 *
 * <p>Lifted out of {@code AssistantFragment} because it was wrong and nothing
 * could see it: the owner built a contract, tapped Open on the card announcing
 * it, and landed on the client's overview. {@code confirm_mou_values} returns
 * the contract's id AND the client's, and the client won on nothing better
 * than being first in a list written before contracts existed. A fragment
 * needs Robolectric, which this project does not have, so a decision left in
 * one is a decision no test can reach.
 *
 * <p>The vocabulary is the BACKEND's — these are the context keys it accepts
 * and returns, not a domain model of this app's own. Adding a key here is how
 * a new kind of document becomes openable from the chat.
 */
public final class AssistantEntities {

    /**
     * Context-id keys the backend uses, and the entity each implies.
     *
     * <p><b>Order is the decision.</b> The first key present wins, so the most
     * SPECIFIC document a result is about comes first and {@code lead_id} --
     * which nearly every payload carries as context -- comes last. Put it
     * first, as it was, and every card about anything opens the client.
     */
    private static final String[][] ID_KEYS = {
            {"mou_id", "mou"},
            {"proposal_id", "proposal"},
            {"meeting_id", "meeting"},
            {"message_id", "message"},
            {"project_id", "project"},
            {"demo_id", "demo"},
            {"invoice_id", "invoice"},
            {"task_id", "action_item"},
            {"action_item_id", "action_item"},
            {"lead_id", "lead"},
    };

    private AssistantEntities() {
    }

    /**
     * What this action opens: {@code {type, id}}, or null for nothing.
     *
     * <p>The result is asked first and the arguments second: what a tool DID
     * is a better answer than what it was asked to do.
     */
    @Nullable
    public static String[] of(@Nullable Object result, @Nullable Object args,
                              @NonNull String tool) {
        String[] found = find(result, tool);
        return found != null ? found : find(args, tool);
    }

    @Nullable
    private static String[] find(@Nullable Object value, @NonNull String tool) {
        if (!(value instanceof Map)) return null;
        Map<?, ?> map = (Map<?, ?>) value;
        for (String[] key : ID_KEYS) {
            String id = text(map.get(key[0]));
            if (id != null) return new String[]{key[1], id};
        }
        // Tools often return a bare "id" and nothing else to go on — infer
        // the entity from the tool's own name (create_proposal → proposal).
        String id = text(map.get("id"));
        if (id != null) {
            for (String[] key : ID_KEYS) {
                if (tool.contains(key[1])) return new String[]{key[1], id};
            }
        }
        return null;
    }

    @Nullable
    private static String text(@Nullable Object value) {
        if (!(value instanceof String)) return null;
        String id = (String) value;
        return id.isEmpty() ? null : id;
    }
}
