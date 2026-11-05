package com.yuvipep.app.feature.assistant;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

/**
 * One transcript entry. A single class with nullable fields keeps the
 * adapter simple; {@link #kind} picks the layout.
 */
public class ChatItem {

    public enum Kind { USER, REPLY, ACTION, APPROVAL, QUESTION }

    @NonNull public final Kind kind;

    // USER + REPLY
    @Nullable public String text;
    // REPLY meta ("answered by the proposal agent · about: X")
    @Nullable public String meta;

    // ACTION card
    @Nullable public String title;
    @Nullable public String body;
    public boolean ok = true;
    // Where the card can navigate ("lead"/"meeting"/"proposal"…) — null = nowhere.
    @Nullable public String entityType;
    @Nullable public String entityId;

    // QUESTION card (F28): the assistant is unsure and is asking rather than
    // guessing. The candidates are the answers it will accept as a tap.
    @Nullable public java.util.List<String> candidates;
    /**
     * The card belongs to a client Jarvis is building up (details.kind ==
     * client_draft). Its chips are complete answers, so a tap sends them; and
     * only the newest such card is kept — it replaces the one before.
     */
    public boolean clientDraft;
    /** What the draft holds so far, as {label, value} rows. */
    @Nullable public java.util.List<String[]> draftRows;
    /** Which step the draft is on, in words. */
    @Nullable public String draftStep;

    // APPROVAL card (always an outbound message on this backend)
    @Nullable public String messageId;
    /**
     * F30: the fill-in-the-blanks the draft still carries ("[Name]"). Non-empty
     * means Approve must confirm first — the backend refuses otherwise, and it
     * is refusing on the user's behalf, not against them.
     */
    @Nullable public java.util.List<String> blanks;
    /** pending → approved/rejected; error text replaces the buttons honestly. */
    @Nullable public String approvalState;
    @Nullable public String approvalError;

    public ChatItem(@NonNull Kind kind) {
        this.kind = kind;
    }

    public static ChatItem user(@NonNull String text) {
        ChatItem item = new ChatItem(Kind.USER);
        item.text = text;
        return item;
    }

    public static ChatItem reply(@NonNull String text, @Nullable String meta) {
        ChatItem item = new ChatItem(Kind.REPLY);
        item.text = text;
        item.meta = meta;
        return item;
    }
}
