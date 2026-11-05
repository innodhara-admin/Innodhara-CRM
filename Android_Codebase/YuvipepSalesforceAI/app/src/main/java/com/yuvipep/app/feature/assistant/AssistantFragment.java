package com.yuvipep.app.feature.assistant;

import android.os.Bundle;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.chip.Chip;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.AssistantDtos;
import com.yuvipep.app.databinding.FragmentAssistantBinding;
import com.yuvipep.app.feature.assistant.voice.VoiceModeController;
import com.yuvipep.app.feature.assistant.voice.VoiceStageDialog;
import com.yuvipep.app.feature.leads.LeadStates;
import com.yuvipep.app.feature.meetings.RecorderService;

import java.util.List;
import java.util.Map;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;
import io.noties.markwon.Markwon;

/**
 * Jarvis (04): free text → POST /assistant/command → reply bubble + a card
 * per action taken + inline approval bars for anything the AI drafted. The
 * context chip shows what "this" means (ContextBus).
 *
 * <p>Voice mode (backend docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md) is
 * the same conversation spoken, on its own screen with Jarvis's talking
 * avatar ({@link VoiceStageDialog}): {@link VoiceModeController} streams the
 * mic to the server and plays the answer, and its replies render through the
 * very same cards as typed ones, here and on that screen. The mic button
 * beside the input is still one-shot dictation into the box.
 */
@AndroidEntryPoint
public class AssistantFragment extends Fragment implements ChatAdapter.Listener,
        VoiceModeController.Ui, VoiceModeController.ContextSource, VoiceStageDialog.Host {

    // Which screen a card's Open goes to is decided in AssistantEntities,
    // where a test can reach it. It was decided here, and a contract opened
    // the client's overview instead of the contract.

    @Inject AssistantRepository repository;
    @Inject AssistantSession session;
    @Inject ContextBus contextBus;
    @Inject TokenStore tokenStore;
    @Inject com.yuvipep.app.core.voice.TtsSpeaker ttsSpeaker;
    @Inject VoiceModeController voice;

    private FragmentAssistantBinding binding;
    private ChatAdapter adapter;
    private boolean busy;
    @Nullable private com.yuvipep.app.core.voice.SpeechInput speech;
    private boolean listening;
    private androidx.activity.result.ActivityResultLauncher<String> micPermission;
    /** The permission prompt was for voice mode, not for dictation. */
    private boolean permissionForVoiceMode;
    /** Jarvis's voice screen, while it is open. */
    @Nullable private VoiceStageDialog stage;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentAssistantBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        adapter = new ChatAdapter(session.transcript(), this, Markwon.create(requireContext()));
        binding.transcript.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.transcript.setAdapter(adapter);

        if (session.transcript().isEmpty()) {
            String name = tokenStore.getName();
            binding.emptyHint.setText(getString(R.string.assistant_greeting,
                    name == null || name.isEmpty()
                            ? getString(R.string.assistant_greeting_fallback) : name));
        }
        restoreConversation();

        binding.newChatButton.setOnClickListener(v -> confirmNewConversation());
        binding.sendButton.setOnClickListener(v -> send());
        binding.commandInput.setOnEditorActionListener((v, actionId, event) -> {
            send();
            return true;
        });
        binding.contextChip.setOnCloseIconClickListener(v -> {
            contextBus.clear();
            renderContextChip();
            voice.contextChanged();
        });

        // Voice (Phase 5, 04 §3): mic dictates a command — final text is
        // sent automatically, the Iron-Man loop. TTS toggle speaks replies.
        micPermission = registerForActivityResult(
                new androidx.activity.result.contract.ActivityResultContracts
                        .RequestPermission(),
                granted -> {
                    boolean forVoice = permissionForVoiceMode;
                    permissionForVoiceMode = false;
                    if (Boolean.TRUE.equals(granted)) {
                        if (forVoice) startVoiceMode();
                        else startListening();
                    } else {
                        android.widget.Toast.makeText(requireContext(),
                                R.string.voice_permission_hint,
                                android.widget.Toast.LENGTH_LONG).show();
                    }
                });
        binding.micButton.setOnClickListener(v -> onMicTap());
        binding.speakToggle.setOnClickListener(v -> {
            ttsSpeaker.setEnabled(!ttsSpeaker.isEnabled());
            renderSpeakToggle();
            android.widget.Toast.makeText(requireContext(), ttsSpeaker.isEnabled()
                            ? R.string.assistant_speak_on : R.string.assistant_speak_off,
                    android.widget.Toast.LENGTH_SHORT).show();
        });
        renderSpeakToggle();
        renderRecentChips();
        setUpVoiceMode();
        scrollToEnd();

        // A command another screen wrote for the user (the Inbox reply route).
        // It lands in the box, not in the transcript: the user still reads it,
        // edits it and taps send — nothing is asked on their behalf.
        String prefill = session.takePrefill();
        if (prefill != null && !prefill.isEmpty()) {
            binding.commandInput.setText(prefill);
            binding.commandInput.setSelection(prefill.length());
            binding.commandInput.requestFocus();
        }
    }

    private void renderSpeakToggle() {
        binding.speakToggle.setImageResource(ttsSpeaker.isEnabled()
                ? R.drawable.ic_volume_on : R.drawable.ic_volume_off);
    }

    private void onMicTap() {
        if (voice.isActive()) return;
        if (listening) {
            if (speech != null) speech.stop();
            return;
        }
        if (!com.yuvipep.app.core.voice.SpeechInput.available(requireContext())) {
            android.widget.Toast.makeText(requireContext(), R.string.voice_unavailable,
                    android.widget.Toast.LENGTH_LONG).show();
            return;
        }
        if (androidx.core.content.ContextCompat.checkSelfPermission(requireContext(),
                android.Manifest.permission.RECORD_AUDIO)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            micPermission.launch(android.Manifest.permission.RECORD_AUDIO);
            return;
        }
        startListening();
    }

    private void startListening() {
        if (speech == null) speech = new com.yuvipep.app.core.voice.SpeechInput();
        listening = true;
        ttsSpeaker.stop();
        binding.micButton.setIconResource(R.drawable.ic_stop);
        binding.commandInput.setHint(R.string.voice_listening);
        speech.start(requireContext(), new com.yuvipep.app.core.voice.SpeechInput.Listener() {
            @Override
            public void onPartial(@NonNull String text) {
                if (binding == null) return;
                binding.commandInput.setText(text);
                binding.commandInput.setSelection(text.length());
            }

            @Override
            public void onFinal(@NonNull String text) {
                onFinal(text, false);
            }

            @Override
            public void onFinal(@NonNull String text, boolean lowConfidence) {
                if (binding == null) return;
                binding.commandInput.setText(text);
                binding.commandInput.setSelection(text.length());
                // The mic normally sends for you — the Iron-Man loop. But when
                // the server says it did not hear well, sending would put words
                // in the user's mouth: measured with real Kannada speech, the
                // dictation model returned 6-12% similarity to what was said,
                // and the assistant answered that nonsense confidently instead
                // of admitting it had not understood. Below the gate, the text
                // is still shown — the user can see what was heard, fix it, and
                // send it themselves — but nothing is asked on their behalf.
                if (lowConfidence) {
                    android.widget.Toast.makeText(requireContext(),
                            R.string.voice_low_confidence,
                            android.widget.Toast.LENGTH_LONG).show();
                    return;
                }
                send();
            }

            @Override
            public void onTranscribing() {
                if (binding == null) return;
                // Mic is closed, clip is uploading — don't keep saying
                // "Listening…" at someone who has stopped talking.
                binding.commandInput.setHint(R.string.voice_transcribing);
            }

            @Override
            public void onError(@NonNull String message) {
                if (binding == null) return;
                android.widget.Toast.makeText(requireContext(), message,
                        android.widget.Toast.LENGTH_SHORT).show();
            }

            @Override
            public void onEnd() {
                listening = false;
                if (binding == null) return;
                binding.micButton.setIconResource(R.drawable.ic_mic);
                binding.commandInput.setHint(R.string.assistant_input_hint);
            }
        });
    }

    @Override
    public void onResume() {
        super.onResume();
        renderContextChip();
        voice.contextChanged();
    }

    /**
     * Leaving the screen ends voice mode (backend doc §5.7: stop listening in
     * the background). The conversation itself is kept server-side — reopen
     * voice mode and it carries on, unfinished client included.
     */
    @Override
    public void onStop() {
        super.onStop();
        if (voice.isActive()) voice.stop();
    }

    private void renderContextChip() {
        if (binding == null) return;
        if (contextBus.hasContext()) {
            binding.contextChip.setText(getString(R.string.assistant_about,
                    contextBus.title() == null
                            ? LeadStates.label(contextBus.entityType())
                            : contextBus.title()));
            binding.contextChip.setVisibility(View.VISIBLE);
            binding.contextChipSpacer.setVisibility(View.GONE);
        } else {
            binding.contextChip.setVisibility(View.GONE);
            // Without the chip, something must still hold the middle of the
            // row open, or the mic, speaker and new-chat buttons slide in
            // behind the title.
            binding.contextChipSpacer.setVisibility(View.VISIBLE);
        }
    }

    /**
     * The app died, the conversation did not (04 §4): pull the turns the
     * backend kept for this session so a reopened screen carries on instead of
     * greeting the user as a stranger. Text only — the action cards and
     * approval bars belonged to the request that produced them, and are not
     * replayed as if they were still live buttons. A failure here is silent
     * on purpose: an empty transcript is exactly what the user saw before.
     */
    private void restoreConversation() {
        if (!session.beginRestore()) return;
        repository.history(session.sessionId(), result -> {
            session.finishRestore(result.isSuccess());
            if (binding == null || !result.isSuccess() || result.data == null) return;
            // The user may have typed while the fetch was in flight — their
            // live bubbles win over a replay that would duplicate them.
            if (result.data.isEmpty() || !session.transcript().isEmpty()) return;
            for (AssistantDtos.Turn turn : result.data) {
                if (turn.content == null || turn.content.trim().isEmpty()) continue;
                session.transcript().add("assistant".equals(turn.role)
                        ? ChatItem.reply(turn.content, turn.agent == null ? null
                                : getString(R.string.assistant_agent_meta,
                                        LeadStates.label(turn.agent).toLowerCase()))
                        : ChatItem.user(turn.content));
            }
            binding.emptyHint.setVisibility(View.GONE);
            notifyTranscriptChanged();
            scrollToEnd();
        });
    }

    /** "New chat" — and the backend forgets too, or it is not a new chat. */
    private void confirmNewConversation() {
        if (session.transcript().isEmpty()) return;
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.assistant_new_chat_title)
                .setMessage(R.string.assistant_new_chat_body)
                .setPositiveButton(R.string.assistant_new_chat_confirm, (d, w) -> {
                    String previous = session.newConversation();
                    notifyTranscriptChanged();
                    binding.emptyHint.setVisibility(View.VISIBLE);
                    repository.clearHistory(previous, result -> {
                        if (binding == null || result.isSuccess()) return;
                        // Honest: the screen is clear but the server still holds
                        // the turns, so say so rather than imply they are gone.
                        android.widget.Toast.makeText(requireContext(),
                                R.string.assistant_new_chat_not_forgotten,
                                android.widget.Toast.LENGTH_LONG).show();
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void renderRecentChips() {
        binding.recentChips.removeAllViews();
        List<String> recent = session.recentCommands();
        // Jarvis can add a client by conversation - offered only to the roles
        // the server lets do it (it refuses relationship managers and ops).
        boolean canCreateLead = com.yuvipep.app.core.auth.RoleGate.has(
                tokenStore.getRole(), com.yuvipep.app.core.auth.RoleGate.MANAGE_LEADS);
        if (canCreateLead) {
            Chip suggest = new Chip(requireContext());
            suggest.setText(R.string.assistant_suggest_create_lead);
            suggest.setChipIconResource(R.drawable.ic_add);
            suggest.setEnsureMinTouchTargetSize(false);
            suggest.setOnClickListener(v -> {
                String prefill = getString(R.string.assistant_suggest_create_lead_prefill);
                binding.commandInput.setText(prefill);
                binding.commandInput.setSelection(prefill.length());
                binding.commandInput.requestFocus();
                android.view.inputmethod.InputMethodManager imm =
                        (android.view.inputmethod.InputMethodManager) requireContext()
                                .getSystemService(android.content.Context.INPUT_METHOD_SERVICE);
                if (imm != null) {
                    imm.showSoftInput(binding.commandInput,
                            android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);
                }
            });
            binding.recentChips.addView(suggest);
        }
        binding.recentScroll.setVisibility(recent.isEmpty() && !canCreateLead
                ? View.GONE : View.VISIBLE);
        for (String command : recent) {
            Chip chip = new Chip(requireContext());
            chip.setText(command.length() > 40
                    ? command.substring(0, 40) + "…" : command);
            chip.setEnsureMinTouchTargetSize(false);
            chip.setOnClickListener(v -> {
                binding.commandInput.setText(command);
                binding.commandInput.setSelection(command.length());
            });
            binding.recentChips.addView(chip);
        }
    }

    private void send() {
        send(true);
    }

    /**
     * @param remember false for one-word answers (a draft's chips) — they are
     *                 not commands worth offering again as a recent chip.
     */
    private void send(boolean remember) {
        if (busy || binding == null) return;
        String text = binding.commandInput.getText() == null ? ""
                : binding.commandInput.getText().toString().trim();
        if (text.isEmpty()) return;

        binding.commandInput.setText("");
        binding.emptyHint.setVisibility(View.GONE);
        if (remember) session.rememberCommand(text);

        String contextTitle = contextBus.hasContext() ? contextBus.title() : null;
        ChatItem userItem = ChatItem.user(text);
        if (contextTitle != null) {
            userItem.meta = getString(R.string.assistant_about, contextTitle);
        }
        retireDraftChips();

        // In a spoken conversation a typed turn goes down the same socket, so
        // its answer is spoken too and the turns stay in order.
        if (voice.canSendText()) {
            append(userItem);
            if (!voice.sendText(text)) {
                binding.commandInput.setText(text);
                android.widget.Toast.makeText(requireContext(),
                        R.string.assistant_error_meta, android.widget.Toast.LENGTH_SHORT).show();
            }
            renderRecentChips();
            return;
        }

        append(userItem);
        setBusy(true);

        String type = contextBus.entityType();
        String id = contextBus.entityId();
        repository.command(text, session.sessionId(),
                "lead".equals(type) ? id : null,
                "proposal".equals(type) ? id : null,
                "meeting".equals(type) ? id : null,
                result -> {
                    if (binding == null) return;
                    setBusy(false);
                    if (result.isSuccess() && result.data != null) {
                        renderResponse(result.data, true);
                    } else if (result.error != null) {
                        // Honest failure (04 §6): the backend's words, plus a
                        // route to retry — the command stays one tap away.
                        ChatItem error = ChatItem.reply(result.error.message,
                                getString(R.string.assistant_error_meta));
                        append(error);
                        binding.commandInput.setText(text);
                    }
                    renderRecentChips();
                });
    }

    /**
     * @param speakWithToggle typed turns are read out by the "speak replies"
     *                        toggle; voice mode speaks its own replies.
     */
    private void renderResponse(@NonNull AssistantDtos.CommandResponse response,
                                boolean speakWithToggle) {
        retireDraftChips();
        String meta = response.agent == null ? null
                : getString(R.string.assistant_agent_meta,
                        LeadStates.label(response.agent).toLowerCase());
        append(ChatItem.reply(response.reply == null ? "" : response.reply, meta));
        if (speakWithToggle) ttsSpeaker.speak(response.reply);

        boolean draftCard = false;
        if (response.actions != null) {
            for (Map<String, Object> action : response.actions) {
                ChatItem card = actionCard(action);
                // One live draft per conversation: the newest replaces the last.
                if (card.clientDraft) {
                    removeDraftCards();
                    draftCard = true;
                }
                append(card);
            }
        }
        // The client conversation answering without a draft card has ended —
        // created ("Client added" says so) or dropped ("Nothing was created").
        // A leftover "Ready to create" card would contradict it.
        if ("client".equals(response.agent) && !draftCard) removeDraftCards();
        if (response.pendingApprovals != null) {
            for (Map<String, Object> approval : response.pendingApprovals) {
                append(approvalCard(approval));
            }
        }
    }

    /**
     * One card per tool call, rendered generically from whatever came back —
     * unless the tool is asking rather than reporting (F28), which gets its
     * own card instead of the red "failed" badge.
     */
    @NonNull
    private ChatItem actionCard(@NonNull Map<String, Object> action) {
        if ("needs_confirmation".equals(action.get("outcome"))) {
            return questionCard(action);
        }
        ChatItem item = new ChatItem(ChatItem.Kind.ACTION);
        Object tool = action.get("tool");
        item.title = LeadStates.label(tool == null ? "action" : String.valueOf(tool));
        item.ok = !Boolean.FALSE.equals(action.get("ok"));

        Object detail = item.ok ? action.get("result") : action.get("error");
        String body = Pretty.value(detail);
        item.body = body.isEmpty() ? null : body;
        if (ClientDraft.isCreated(action)) {
            // Jarvis created a client: say so plainly; Open goes to the lead.
            String name = ClientDraft.createdName(action);
            item.title = getString(R.string.assistant_client_added);
            if (name != null) item.body = getString(R.string.assistant_client_added_body, name);
        }

        // Where can this card navigate? The result first, then the arguments.
        String[] entity = AssistantEntities.of(
                action.get("result"), action.get("args"),
                tool == null ? "" : String.valueOf(tool));
        if (entity != null) {
            item.entityType = entity[0];
            item.entityId = entity[1];
        }
        return item;
    }

    /**
     * The assistant is unsure and is asking (F28). The question text is the
     * backend's, verbatim; the candidates become one-tap answers. Older
     * backends never send `outcome`, so they simply keep rendering the plain
     * action card — this is additive on both sides.
     */
    @NonNull
    private ChatItem questionCard(@NonNull Map<String, Object> action) {
        ChatItem item = new ChatItem(ChatItem.Kind.QUESTION);
        Object question = action.get("question");
        if (question == null) question = action.get("error");
        item.body = question == null ? getString(R.string.assistant_question_fallback)
                : String.valueOf(question);
        Object candidates = action.get("candidates");
        if (candidates instanceof List) {
            java.util.List<String> answers = new java.util.ArrayList<>();
            for (Object candidate : (List<?>) candidates) {
                if (candidate != null && !String.valueOf(candidate).isEmpty()) {
                    answers.add(String.valueOf(candidate));
                }
            }
            item.candidates = answers;
        }
        ClientDraft draft = ClientDraft.of(action);
        if (draft != null) {
            item.clientDraft = true;
            item.draftRows = draft.rows(getString(R.string.assistant_draft_owner_you));
            item.draftStep = draft.stepLabel();
        }
        return item;
    }

    /** Earlier draft cards are history once a newer one arrives. */
    private void removeDraftCards() {
        boolean removed = false;
        java.util.Iterator<ChatItem> it = session.transcript().iterator();
        while (it.hasNext()) {
            if (it.next().clientDraft) {
                it.remove();
                removed = true;
            }
        }
        if (removed) notifyTranscriptChanged();
    }

    /**
     * A draft card's chips answer the question it asked. Once anything else
     * has been said they would answer a question no longer being asked - a
     * stale "Create it" must not stay tappable.
     */
    private void retireDraftChips() {
        List<ChatItem> items = session.transcript();
        for (int i = 0; i < items.size(); i++) {
            ChatItem item = items.get(i);
            if (item.clientDraft && item.candidates != null && !item.candidates.isEmpty()) {
                item.candidates = null;
                notifyTranscriptItemChanged(i);
            }
        }
    }

    @NonNull
    private ChatItem approvalCard(@NonNull Map<String, Object> approval) {
        ChatItem item = new ChatItem(ChatItem.Kind.APPROVAL);
        Object kind = approval.get("kind");
        item.title = getString(R.string.assistant_approval_title,
                LeadStates.label(kind == null ? "message" : String.valueOf(kind)));
        String body = Pretty.value(approval);
        item.body = body.isEmpty() ? null : body;
        Object blanks = approval.get("blanks");
        if (blanks instanceof List) {
            java.util.List<String> found = new java.util.ArrayList<>();
            for (Object blank : (List<?>) blanks) {
                if (blank != null) found.add(String.valueOf(blank));
            }
            item.blanks = found;
        }
        Object messageId = approval.get("message_id");
        if (messageId instanceof String) {
            item.messageId = (String) messageId;
            item.approvalState = "pending";
        } else {
            // Nothing to act on — render the facts, no fake buttons.
            item.approvalState = "unactionable";
        }
        return item;
    }

    private void append(@NonNull ChatItem item) {
        session.transcript().add(item);
        notifyTranscriptInserted(session.transcript().size() - 1);
        scrollToEnd();
    }

    private void scrollToEnd() {
        if (!session.transcript().isEmpty()) {
            binding.transcript.scrollToPosition(session.transcript().size() - 1);
        }
    }

    private void setBusy(boolean value) {
        busy = value;
        binding.thinkingRow.setVisibility(value && !voice.isActive() ? View.VISIBLE : View.GONE);
        binding.sendButton.setEnabled(!value);
    }

    // ── Voice mode ───────────────────────────────────────────────────
    //
    // The header's voice button opens Jarvis's voice screen (the avatar,
    // VoiceStageDialog). The session itself lives here, so the screen's
    // cards, chips and approvals are this fragment's, and the chat below has
    // every turn when the screen closes.

    private void setUpVoiceMode() {
        boolean hasMic = com.yuvipep.app.core.voice.SpeechInput.available(requireContext());
        binding.voiceModeButton.setVisibility(hasMic ? View.VISIBLE : View.GONE);
        binding.voiceModeButton.setOnClickListener(v -> onVoiceModeTap());
        // A screen left over from before a configuration change closes itself.
        androidx.fragment.app.Fragment old =
                getChildFragmentManager().findFragmentByTag(VoiceStageDialog.TAG);
        if (old instanceof VoiceStageDialog && stage == null) {
            ((VoiceStageDialog) old).dismissAllowingStateLoss();
        }
    }

    private void onVoiceModeTap() {
        RecorderService.State recording = RecorderService.state().getValue();
        if (recording != null && (recording.status == RecorderService.Status.RECORDING
                || recording.status == RecorderService.Status.PAUSED)) {
            android.widget.Toast.makeText(requireContext(), R.string.voice_mode_recording_busy,
                    android.widget.Toast.LENGTH_LONG).show();
            return;
        }
        if (androidx.core.content.ContextCompat.checkSelfPermission(requireContext(),
                android.Manifest.permission.RECORD_AUDIO)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            permissionForVoiceMode = true;
            micPermission.launch(android.Manifest.permission.RECORD_AUDIO);
            return;
        }
        startVoiceMode();
    }

    /** Open the voice screen; it starts the session once it is up. */
    private void startVoiceMode() {
        if (binding == null || stage != null || !isAdded()) return;
        if (getChildFragmentManager().isStateSaved()) return;
        // One thing on the mic at a time, and one voice.
        if (listening && speech != null) speech.destroy();
        speech = null;
        listening = false;
        binding.micButton.setIconResource(R.drawable.ic_mic);
        binding.commandInput.setHint(R.string.assistant_input_hint);
        ttsSpeaker.stop();
        binding.emptyHint.setVisibility(View.GONE);
        VoiceStageDialog.newInstance().show(getChildFragmentManager(), VoiceStageDialog.TAG);
    }

    // VoiceStageDialog.Host

    @NonNull
    @Override
    public VoiceModeController voice() {
        return voice;
    }

    @NonNull
    @Override
    public List<ChatItem> transcript() {
        return session.transcript();
    }

    @NonNull
    @Override
    public AssistantRepository repository() {
        return repository;
    }

    @NonNull
    @Override
    public ChatAdapter.Listener chatListener() {
        return this;
    }

    @Override
    public void startVoiceFromStage() {
        if (!voice.isActive()) voice.start(this, this);
    }

    @Override
    public void sendFromStage(@NonNull String text) {
        if (binding == null) return;
        binding.commandInput.setText(text);
        send();
    }

    @Nullable
    @Override
    public String contextTitle() {
        return contextBus.hasContext() ? contextBus.title() : null;
    }

    @Override
    public void onStageShown(@NonNull VoiceStageDialog shown) {
        stage = shown;
        renderVoiceButton();
    }

    @Override
    public void onStageGone(@NonNull VoiceStageDialog gone) {
        if (stage == gone) stage = null;
        renderVoiceButton();
    }

    private void renderVoiceButton() {
        if (binding == null) return;
        boolean on = stage != null || voice.isActive();
        binding.voiceModeButton.setImageResource(on ? R.drawable.ic_close : R.drawable.ic_voice_mode);
        binding.voiceModeButton.setContentDescription(getString(on
                ? R.string.voice_mode_end : R.string.voice_mode_start));
        binding.micButton.setVisibility(voice.isActive() ? View.GONE : View.VISIBLE);
    }

    // Transcript changes reach the chat and, when open, the voice screen.

    private void notifyTranscriptInserted(int position) {
        adapter.notifyItemInserted(position);
        if (stage != null) stage.transcriptInserted(position);
    }

    private void notifyTranscriptItemChanged(int position) {
        adapter.notifyItemChanged(position);
        if (stage != null) stage.transcriptItemChanged(position);
    }

    private void notifyTranscriptChanged() {
        adapter.notifyDataSetChanged();
        if (stage != null) stage.transcriptChanged();
    }

    // VoiceModeController.Ui

    @Override
    public void onVoiceState(@NonNull VoiceModeController.State state, @Nullable String detail) {
        if (binding == null) return;
        renderVoiceButton();
        if (state != VoiceModeController.State.OFF) binding.thinkingRow.setVisibility(View.GONE);
        if (stage != null) stage.onVoiceState(state, detail);
    }

    @Override
    public void onVoiceLevel(float level) {
        if (stage != null) stage.onVoiceLevel(level);
    }

    @Override
    public void onVoiceTranscript(@NonNull String text, boolean lowConfidence) {
        if (binding == null) return;
        binding.emptyHint.setVisibility(View.GONE);
        retireDraftChips();
        ChatItem item = ChatItem.user(text);
        String heard = getString(lowConfidence
                ? R.string.voice_heard_unsure_meta : R.string.voice_heard_meta);
        String contextTitle = contextBus.hasContext() ? contextBus.title() : null;
        item.meta = contextTitle == null ? heard
                : heard + " · " + getString(R.string.assistant_about, contextTitle);
        append(item);
        if (stage != null) stage.onHeard(text);
    }

    @Override
    public void onVoiceReply(@NonNull AssistantDtos.CommandResponse reply) {
        if (binding == null) return;
        binding.emptyHint.setVisibility(View.GONE);
        renderResponse(reply, false);
        if (stage != null && reply.reply != null) stage.onJarvisSays(reply.reply);
    }

    @Override
    public void onVoiceSpeaking(@NonNull String text) {
        if (stage != null) stage.onJarvisSays(text);
    }

    @Override
    public void onVoiceNotActed(@NonNull String reply, @Nullable String heard) {
        if (binding == null) return;
        append(ChatItem.reply(reply, getString(R.string.assistant_agent_voice_meta)));
        if (stage != null) stage.onJarvisSays(reply);
        // What was heard goes in the box: fix it and send it, or say it again.
        if (heard != null && !heard.trim().isEmpty()) {
            if (stage != null) {
                stage.offerEdit(heard.trim());
            } else {
                binding.commandInput.setText(heard.trim());
                binding.commandInput.setSelection(heard.trim().length());
            }
            android.widget.Toast.makeText(requireContext(), R.string.voice_mode_not_acted_hint,
                    android.widget.Toast.LENGTH_LONG).show();
        }
    }

    @Override
    public void onVoiceError(@NonNull String message) {
        if (binding == null) return;
        append(ChatItem.reply(message, null));
        if (stage != null) stage.onJarvisSays(message);
    }

    @Override
    public void onVoiceEnded(@Nullable String reason) {
        if (binding == null) return;
        renderVoiceButton();
        if (stage != null) {
            stage.onVoiceEnded(reason);
        } else if (reason != null) {
            android.widget.Toast.makeText(requireContext(), reason,
                    android.widget.Toast.LENGTH_LONG).show();
        }
    }

    @Override
    public void onVoiceUnauthorized() {
        if (binding == null) return;
        if (stage != null) stage.dismissAllowingStateLoss();
        renderVoiceButton();
        android.widget.Toast.makeText(requireContext(), R.string.voice_mode_signed_out,
                android.widget.Toast.LENGTH_LONG).show();
        // The socket cannot sign anyone out; an ordinary request can. If the
        // token really is dead, AuthInterceptor wipes the session and the
        // app routes to Login exactly as it does for any other 401.
        repository.voiceConfig(result -> { });
    }

    // VoiceModeController.ContextSource

    @Nullable
    @Override
    public String leadId() {
        return "lead".equals(contextBus.entityType()) ? contextBus.entityId() : null;
    }

    @Nullable
    @Override
    public String proposalId() {
        return "proposal".equals(contextBus.entityType()) ? contextBus.entityId() : null;
    }

    @Nullable
    @Override
    public String meetingId() {
        return "meeting".equals(contextBus.entityType()) ? contextBus.entityId() : null;
    }

    // ── ChatAdapter.Listener ─────────────────────────────────────────

    @Override
    public void onOpenEntity(@NonNull String entityType, @NonNull String entityId) {
        // Leaving for another screen ends the spoken conversation first.
        if (stage != null) {
            voice.stop();
            stage.dismissAllowingStateLoss();
        }
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).openEntity(entityType, entityId);
        }
    }

    @Override
    public void onWhy(@NonNull String entityType, @NonNull String entityId) {
        WhySheet.open(getParentFragmentManager(), entityType, entityId);
    }

    /**
     * An answer to the assistant's clarifying question (F28). It lands in the
     * input box rather than being sent for them — the same rule the Inbox
     * reply route follows: the user reads it, may edit it, and taps send.
     */
    @Override
    public void onAnswer(@NonNull String candidate) {
        if (binding == null) return;
        binding.commandInput.setText(candidate);
        binding.commandInput.setSelection(candidate.length());
        binding.commandInput.requestFocus();
    }

    /** A client draft's chip: the whole answer, sent as tapped. */
    @Override
    public void onAnswerNow(@NonNull String candidate) {
        if (binding == null) return;
        if (busy) {
            onAnswer(candidate);
            return;
        }
        binding.commandInput.setText(candidate);
        send(false);
    }

    @Override
    public void onApprove(@NonNull ChatItem item) {
        if (item.messageId == null) return;
        // F30: a draft still carrying "[Name]" gets one deliberate confirmation
        // first. The backend refuses it either way — this is so the refusal
        // arrives as a readable question instead of an error after the tap.
        if (item.blanks != null && !item.blanks.isEmpty()) {
            new MaterialAlertDialogBuilder(requireContext())
                    .setTitle(R.string.approval_blanks_title)
                    .setMessage(getString(R.string.approval_blanks_body,
                            android.text.TextUtils.join(", ", item.blanks)))
                    .setPositiveButton(R.string.approval_blanks_send_anyway,
                            (d, w) -> sendApproval(item, true))
                    .setNegativeButton(R.string.approval_blanks_cancel, null)
                    .show();
            return;
        }
        sendApproval(item, false);
    }

    private void sendApproval(@NonNull ChatItem item, boolean allowBlanks) {
        if (item.messageId == null) return;
        item.approvalState = "working";
        notifyTranscriptChanged();
        repository.approveMessage(item.messageId, allowBlanks, result -> {
            if (binding == null) return;
            if (result.isSuccess()) {
                item.approvalState = "approved";
            } else {
                item.approvalState = "pending";
                item.approvalError = result.error == null ? null : result.error.message;
            }
            notifyTranscriptChanged();
        });
    }

    @Override
    public void onReject(@NonNull ChatItem item) {
        if (item.messageId == null) return;
        final android.widget.EditText input =
                new com.yuvipep.app.core.voice.VoiceEditText(requireContext());
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        input.setHint(R.string.assistant_reject_hint);
        android.widget.LinearLayout wrapper =
                new android.widget.LinearLayout(requireContext());
        wrapper.setOrientation(android.widget.LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);
        wrapper.addView(input);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.assistant_reject_title)
                .setView(wrapper)
                .setPositiveButton(R.string.assistant_reject_confirm, (d, w) -> {
                    String reason = input.getText().toString().trim();
                    if (reason.isEmpty()) {
                        reason = getString(R.string.assistant_reject_default);
                    }
                    item.approvalState = "working";
                    notifyTranscriptChanged();
                    repository.rejectMessage(item.messageId, reason, result -> {
                        if (binding == null) return;
                        if (result.isSuccess()) {
                            item.approvalState = "rejected";
                        } else {
                            item.approvalState = "pending";
                            item.approvalError = result.error == null ? null
                                    : result.error.message;
                        }
                        notifyTranscriptChanged();
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        if (stage != null) stage.dismissAllowingStateLoss();
        stage = null;
        voice.release();
        if (speech != null) {
            speech.destroy();
            speech = null;
        }
        listening = false;
        ttsSpeaker.stop();
        binding = null;
    }
}
