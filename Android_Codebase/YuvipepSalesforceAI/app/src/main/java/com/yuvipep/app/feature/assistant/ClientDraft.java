package com.yuvipep.app.feature.assistant;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * The client (lead) Jarvis is building up by conversation, as the backend
 * reports it on every turn: a {@code needs_confirmation} action whose
 * {@code details.kind} is {@code "client_draft"}.
 *
 * <p>The server runs the whole conversation (app/ai/client_draft.py) — this
 * is only what the app shows, so the person can see what will be saved while
 * a spoken name is still being corrected. Lifted out of the fragment so a
 * plain unit test can reach it.
 */
public final class ClientDraft {

    public static final String KIND = "client_draft";

    /** Every step the server can be on; unknown ones are shown as-is. */
    public static final String STAGE_NAME = "name";
    public static final String STAGE_OWNER = "owner";
    public static final String STAGE_OWNER_SUGGESTED = "owner_suggested";
    public static final String STAGE_OPTIONAL = "optional";
    public static final String STAGE_CONFIRM = "confirm";
    public static final String STAGE_SPELL_CHECK = "spell_check";

    @Nullable public final String stage;
    @Nullable public final String name;
    /** "you" when the speaker will own it. */
    @Nullable public final String owner;
    @Nullable public final String city;
    @Nullable public final String source;
    @Nullable public final String website;
    @Nullable public final String notes;
    @Nullable public final String contact;

    private ClientDraft(@NonNull Map<?, ?> details) {
        stage = text(details.get("stage"));
        name = text(details.get("name"));
        owner = text(details.get("owner"));
        city = text(details.get("city"));
        source = text(details.get("source"));
        website = text(details.get("website"));
        notes = text(details.get("notes"));
        contact = contactName(details.get("contact"));
    }

    /** The draft a question-card action carries, or null when it is not one. */
    @Nullable
    public static ClientDraft of(@Nullable Map<String, Object> action) {
        if (action == null) return null;
        Object details = action.get("details");
        if (!(details instanceof Map)) return null;
        Map<?, ?> map = (Map<?, ?>) details;
        if (!KIND.equals(map.get("kind"))) return null;
        return new ClientDraft(map);
    }

    /**
     * Did this action create the client? The last turn of the conversation is
     * an {@code ok: true} {@code create_client} with the new lead's id.
     */
    public static boolean isCreated(@Nullable Map<String, Object> action) {
        if (action == null) return false;
        if (!"create_client".equals(action.get("tool"))) return false;
        if (!Boolean.TRUE.equals(action.get("ok"))) return false;
        Object result = action.get("result");
        return result instanceof Map && text(((Map<?, ?>) result).get("lead_id")) != null;
    }

    /** The created lead's name, from an action {@link #isCreated} accepts. */
    @Nullable
    public static String createdName(@NonNull Map<String, Object> action) {
        Object result = action.get("result");
        return result instanceof Map ? text(((Map<?, ?>) result).get("name")) : null;
    }

    /**
     * Label/value rows for what is filled in so far, in the order the New
     * Lead form holds them. Empty values are left out — the card shows what
     * will be saved, not a form.
     */
    @NonNull
    public List<String[]> rows(@NonNull String ownerYou) {
        List<String[]> rows = new ArrayList<>();
        add(rows, "Name", name);
        add(rows, "Owner", "you".equalsIgnoreCase(owner == null ? "" : owner)
                ? ownerYou : owner);
        add(rows, "City", city);
        add(rows, "Source", source);
        add(rows, "Website", website);
        add(rows, "Contact", contact);
        add(rows, "Notes", notes);
        return rows;
    }

    /** Human words for the step the conversation is on. */
    @NonNull
    public String stepLabel() {
        if (stage == null) return "In progress";
        switch (stage) {
            case STAGE_NAME: return "Waiting for the client's name";
            case STAGE_OWNER:
            case STAGE_OWNER_SUGGESTED: return "Choosing an owner";
            case STAGE_OPTIONAL: return "Optional details";
            case STAGE_CONFIRM: return "Ready to create";
            case STAGE_SPELL_CHECK: return "Checking the spelling";
            default: return "In progress";
        }
    }

    private static void add(@NonNull List<String[]> rows, @NonNull String label,
                            @Nullable String value) {
        if (value != null) rows.add(new String[]{label, value});
    }

    /** The server sends {name, title, phone, email}; tolerate a bare name. */
    @Nullable
    private static String contactName(@Nullable Object value) {
        if (value instanceof Map) {
            Map<?, ?> map = (Map<?, ?>) value;
            String name = text(map.get("name"));
            String title = text(map.get("title"));
            if (name != null && title != null) return name + " (" + title + ")";
            return name;
        }
        return text(value);
    }

    @Nullable
    private static String text(@Nullable Object value) {
        if (value == null) return null;
        String s = String.valueOf(value).trim();
        return s.isEmpty() || "null".equals(s) ? null : s;
    }
}
