package com.yuvipep.app.feature.assistant;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedList;
import java.util.List;
import java.util.UUID;

import javax.inject.Inject;
import javax.inject.Singleton;

import dagger.hilt.android.qualifiers.ApplicationContext;

/**
 * The conversation outlives the fragment (tab switches must not wipe it) and,
 * since the session id is persisted, outlives the process too: the backend
 * holds the turns keyed by that id, so a killed app can ask for its chat back
 * instead of pretending nothing was ever said. The bubbles here are still a
 * working view — the durable record is the backend's.
 *
 * Recent commands persist in prefs for the chips, newline-separated (commands
 * are flattened to one line when remembered).
 */
@Singleton
public class AssistantSession {

    private static final String PREFS = "yuvipep_assistant";
    private static final String KEY_RECENT = "recent_commands";
    private static final String KEY_SESSION = "session_id";
    private static final int MAX_RECENT = 5;

    private final List<ChatItem> transcript = new ArrayList<>();
    private final SharedPreferences prefs;
    /** Server history is fetched once per process, not on every tab visit. */
    private boolean restored;
    /** A fetch is in flight — a fast tab switch must not start a second. */
    private boolean restoring;
    /**
     * A command another screen has written for the user — the Inbox's reply
     * route drafts one from a client's message. It is placed in the input box,
     * never sent: the user reads it, edits it, and decides (Phase 6, F27).
     */
    @Nullable private String pendingPrompt;

    @Inject
    public AssistantSession(@ApplicationContext Context context) {
        this.prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    @NonNull
    public List<ChatItem> transcript() {
        return transcript;
    }

    /**
     * The conversation this device is having. A 32-char UUID hex — the
     * backend accepts 8–64 of [A-Za-z0-9_-].
     */
    @NonNull
    public synchronized String sessionId() {
        String existing = prefs.getString(KEY_SESSION, null);
        if (existing != null && !existing.isEmpty()) return existing;
        String minted = UUID.randomUUID().toString().replace("-", "");
        prefs.edit().putString(KEY_SESSION, minted).apply();
        return minted;
    }

    /**
     * Start a fresh conversation. Returns the id of the one being left so the
     * caller can ask the backend to forget it — a "new chat" that only hides
     * the old turns would be a lie.
     */
    @NonNull
    public synchronized String newConversation() {
        String previous = sessionId();
        prefs.edit().putString(KEY_SESSION,
                UUID.randomUUID().toString().replace("-", "")).apply();
        transcript.clear();
        restored = true;  // the new conversation is empty by construction
        restoring = false;
        return previous;
    }

    /**
     * Claim the one restore attempt. Returns false when the transcript is
     * already populated, a fetch is running, or the conversation has been
     * restored. The claim is released by {@link #finishRestore(boolean)} —
     * a failed fetch (offline on first open) leaves the door open so the
     * next visit tries again instead of losing the chat for the whole
     * process lifetime.
     */
    public synchronized boolean beginRestore() {
        if (restored || restoring || !transcript.isEmpty()) return false;
        restoring = true;
        return true;
    }

    public synchronized void finishRestore(boolean succeeded) {
        restoring = false;
        if (succeeded) restored = true;
    }

    /** Sign-out must not leave one person's chat waiting for the next. */
    public synchronized void reset() {
        transcript.clear();
        restored = false;
        restoring = false;
        prefs.edit().remove(KEY_SESSION).remove(KEY_RECENT).apply();
    }

    /** Hand the assistant a command to open with. */
    public synchronized void prefill(@NonNull String prompt) {
        this.pendingPrompt = prompt;
    }

    /** Read it once — a prompt must not reappear on the next tab visit. */
    @Nullable
    public synchronized String takePrefill() {
        String prompt = pendingPrompt;
        pendingPrompt = null;
        return prompt;
    }

    public void rememberCommand(@NonNull String command) {
        String flat = command.replaceAll("\\s+", " ").trim();
        if (flat.isEmpty()) return;
        LinkedList<String> recent = new LinkedList<>(recentCommands());
        recent.remove(flat);
        recent.addFirst(flat);
        while (recent.size() > MAX_RECENT) recent.removeLast();
        prefs.edit().putString(KEY_RECENT, String.join("\n", recent)).apply();
    }

    @NonNull
    public List<String> recentCommands() {
        String stored = prefs.getString(KEY_RECENT, "");
        if (stored == null || stored.trim().isEmpty()) return new ArrayList<>();
        return new ArrayList<>(Arrays.asList(stored.split("\n")));
    }
}
