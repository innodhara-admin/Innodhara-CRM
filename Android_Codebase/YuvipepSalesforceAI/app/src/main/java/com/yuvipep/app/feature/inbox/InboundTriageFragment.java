package com.yuvipep.app.feature.inbox;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.ContactDto;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.net.dto.LeadDto;
import com.yuvipep.app.core.net.dto.ProjectDto;
import com.yuvipep.app.core.net.dto.TriageItemDto;
import com.yuvipep.app.core.net.dto.TriageResolveRequest;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentInboundTriageBinding;
import com.yuvipep.app.databinding.ItemInboundBinding;
import com.yuvipep.app.feature.assistant.AssistantSession;
import com.yuvipep.app.feature.assistant.ContextBus;
import com.yuvipep.app.feature.leads.LeadStates;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Inbound triage (03 §9) — everything the AI could not place or would not
 * answer, with its own words for why.
 *
 * Each card carries the AI's intent guess, the reason it stopped and its
 * summary. There is no confidence figure because the backend records none;
 * inventing one would be exactly the kind of false certainty this screen
 * exists to prevent.
 *
 * The actions are attach-to-client, attach-to-project, set-intent, mark-handled
 * and — the point of the whole phase — **Reply**, which opens the assistant
 * scoped to that client with a drafted command. The reply itself is written by
 * the email agent and waits for a one-tap approval like every other outward
 * message; this screen never sends anything (FINDINGS F27).
 */
@AndroidEntryPoint
public class InboundTriageFragment extends Fragment {

    @Inject InboxRepository repository;
    @Inject ContextBus contextBus;
    @Inject AssistantSession assistantSession;
    @Inject TokenStore tokenStore;

    /**
     * Replying ends in an outbound message, which needs send_messages. An ops
     * agent can triage — attach, classify, mark handled — but offering them a
     * Reply button that the server would refuse is a dead end, so it is not
     * offered. Everything else on the card still works for them.
     */
    private boolean canReply;

    private FragmentInboundTriageBinding binding;
    private final List<TriageItemDto> items = new ArrayList<>();
    private final Adapter adapter = new Adapter();

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentInboundTriageBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        canReply = RoleGate.has(tokenStore.getRole(), RoleGate.SEND_MESSAGES);
        binding.inboundList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.inboundList.setAdapter(adapter);
        binding.swipeRefresh.setOnRefreshListener(() -> {
            load();
            binding.swipeRefresh.setRefreshing(false);
        });
        load();
    }

    private void load() {
        binding.stateView.showLoading();
        repository.triageQueue(result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                items.clear();
                items.addAll(result.data);
                adapter.notifyDataSetChanged();
                if (items.isEmpty()) {
                    binding.stateView.showEmpty(getString(R.string.triage_empty_title),
                            getString(R.string.triage_empty_body),
                            R.drawable.ic_tab_inbox, null, null);
                } else {
                    binding.stateView.hide();
                }
            } else if (result.isError() && result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    // ── Actions ─────────────────────────────────────────────────────────────

    private void showActions(@NonNull TriageItemDto item) {
        String[] labels = {
                getString(R.string.triage_action_attach_client),
                getString(R.string.triage_action_attach_project),
                getString(R.string.triage_action_set_intent),
                getString(R.string.triage_action_read_full),
                getString(R.string.triage_action_handled),
        };
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.triage_actions)
                .setItems(labels, (dialog, which) -> {
                    switch (which) {
                        case 0: pickLeadThenContact(item); break;
                        case 1: pickProject(item); break;
                        case 2: pickIntent(item); break;
                        case 3: readFull(item); break;
                        default: markHandled(item); break;
                    }
                })
                .show();
    }

    /** The backend resolves a message's client through one of its contacts,
     * so attaching is a two-step pick: which client, then which person. */
    private void pickLeadThenContact(@NonNull TriageItemDto item) {
        repository.leads(result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null) toast(result.error.message);
                return;
            }
            List<PickerSheet.Option> options = new ArrayList<>();
            for (LeadDto lead : result.data) {
                options.add(new PickerSheet.Option(lead.id, lead.name,
                        LeadStates.label(lead.state)));
            }
            if (options.isEmpty()) {
                toast(getString(R.string.triage_no_leads));
                return;
            }
            PickerSheet.open(getParentFragmentManager(),
                    getString(R.string.triage_pick_client), null, options,
                    picked -> pickContact(item, picked.id, picked.label));
        });
    }

    private void pickContact(@NonNull TriageItemDto item, @NonNull String leadId,
                             @NonNull String leadName) {
        repository.lead(leadId, result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null) toast(result.error.message);
                return;
            }
            LeadDetailResponse lead = result.data;
            List<PickerSheet.Option> options = new ArrayList<>();
            if (lead.contacts != null) {
                for (ContactDto contact : lead.contacts) {
                    options.add(new PickerSheet.Option(contact.id, contact.name,
                            subtitleFor(contact)));
                }
            }
            if (options.isEmpty()) {
                // Honest dead end rather than a silent failure: the resolve
                // endpoint takes a contact, so a client with none cannot be
                // attached until somebody adds one.
                new MaterialAlertDialogBuilder(requireContext())
                        .setTitle(R.string.triage_no_contacts_title)
                        .setMessage(getString(R.string.triage_no_contacts_body, leadName))
                        .setPositiveButton(R.string.action_close, null)
                        .show();
                return;
            }
            PickerSheet.open(getParentFragmentManager(),
                    getString(R.string.triage_pick_contact),
                    getString(R.string.triage_pick_contact_hint, leadName),
                    options,
                    picked -> resolve(item, TriageResolveRequest.attachContact(picked.id),
                            getString(R.string.triage_attached_to, leadName)));
        });
    }

    private String subtitleFor(@NonNull ContactDto contact) {
        StringBuilder out = new StringBuilder();
        if (contact.title != null && !contact.title.isEmpty()) out.append(contact.title);
        if (contact.email != null && !contact.email.isEmpty()) {
            if (out.length() > 0) out.append(" · ");
            out.append(contact.email);
        }
        return out.toString();
    }

    private void pickProject(@NonNull TriageItemDto item) {
        repository.projects(result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null) toast(result.error.message);
                return;
            }
            List<PickerSheet.Option> options = new ArrayList<>();
            for (ProjectDto project : result.data) {
                options.add(new PickerSheet.Option(project.id, project.name,
                        LeadStates.label(project.status)));
            }
            if (options.isEmpty()) {
                toast(getString(R.string.triage_no_projects));
                return;
            }
            PickerSheet.open(getParentFragmentManager(),
                    getString(R.string.triage_pick_project), null, options,
                    picked -> resolve(item, TriageResolveRequest.attachProject(picked.id),
                            getString(R.string.triage_attached_to, picked.label)));
        });
    }

    private void pickIntent(@NonNull TriageItemDto item) {
        List<PickerSheet.Option> options = new ArrayList<>();
        for (String intent : InboundIntents.ALL) {
            options.add(new PickerSheet.Option(intent, LeadStates.label(intent), null));
        }
        // Say what it is read as now, so the human sees what they overwrite.
        String hint = item.intent == null || item.intent.isEmpty()
                ? getString(R.string.triage_intent_none)
                : getString(R.string.triage_intent_current, LeadStates.label(item.intent));
        PickerSheet.open(getParentFragmentManager(),
                getString(R.string.triage_pick_intent), hint, options,
                picked -> resolve(item, TriageResolveRequest.setIntent(picked.id),
                        getString(R.string.triage_intent_set, picked.label)));
    }

    private void readFull(@NonNull TriageItemDto item) {
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(item.subject != null && !item.subject.isEmpty()
                        ? item.subject : item.fromAddress)
                .setMessage(item.body)
                .setPositiveButton(R.string.action_close, null)
                .show();
    }

    private void markHandled(@NonNull TriageItemDto item) {
        resolve(item, TriageResolveRequest.markHandled(),
                getString(R.string.triage_handled_toast));
    }

    private void resolve(@NonNull TriageItemDto item, @NonNull TriageResolveRequest body,
                         @NonNull String successMessage) {
        repository.resolveTriage(item.id, body, result -> {
            if (binding == null) return;
            if (result.isSuccess()) {
                toast(successMessage);
                load();
            } else if (result.error != null) {
                toast(result.error.message);
            }
        });
    }

    // ── The reply route (F27) ───────────────────────────────────────────────

    /**
     * Hands the message to the assistant, scoped to the client it came from.
     * Nothing is sent here: the email agent drafts a reply and parks it for
     * the one-tap approval the assistant screen already renders.
     *
     * The client is looked up first, for two reasons found on the device: the
     * context chip should name the client rather than read "About: Lead", and
     * the email agent resolves a recipient by NAME — handed a bare address it
     * fails with "no contact matching…". So the sender's address is matched
     * back to a contact here, and the drafted command names the person.
     */
    private void reply(@NonNull TriageItemDto item) {
        if (item.matchedLeadId == null || item.matchedLeadId.isEmpty()) {
            // The assistant scopes by client, and this message has none yet.
            new MaterialAlertDialogBuilder(requireContext())
                    .setTitle(R.string.triage_reply_needs_client_title)
                    .setMessage(R.string.triage_reply_needs_client_body)
                    .setPositiveButton(R.string.triage_action_attach_client,
                            (d, w) -> pickLeadThenContact(item))
                    .setNegativeButton(R.string.action_close, null)
                    .show();
            return;
        }
        repository.lead(item.matchedLeadId, result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null) toast(result.error.message);
                return;
            }
            LeadDetailResponse lead = result.data;
            openAssistantWithReply(item, lead.name, senderName(lead, item.fromAddress));
        });
    }

    /** Which contact wrote from this address, by name — null when none does. */
    @Nullable
    private String senderName(@NonNull LeadDetailResponse lead, @Nullable String from) {
        if (from == null || from.isEmpty() || lead.contacts == null) return null;
        for (ContactDto contact : lead.contacts) {
            if (from.equalsIgnoreCase(contact.email) || from.equals(contact.phone)) {
                return contact.name;
            }
        }
        return null;
    }

    private void openAssistantWithReply(@NonNull TriageItemDto item,
                                        @NonNull String leadName,
                                        @Nullable String contactName) {
        contextBus.set("lead", item.matchedLeadId, leadName);
        // Naming the person is what lets the email agent resolve a recipient.
        // When the address matches nobody on file we say so instead of
        // guessing a contact — the human can correct the command before send.
        String prompt = contactName != null
                ? getString(R.string.triage_reply_prompt, contactName, leadName, what(item))
                : getString(R.string.triage_reply_prompt_unknown_sender,
                        item.fromAddress == null ? "" : item.fromAddress,
                        leadName, what(item));
        assistantSession.prefill(prompt);
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).openAssistant();
        }
    }

    /** The client's own words are what the reply must answer — the summary
     * when the AI wrote one, otherwise the message itself. */
    private String what(@NonNull TriageItemDto item) {
        String text = item.summary != null && !item.summary.isEmpty()
                ? item.summary
                : (item.body == null ? "" : item.body);
        String flat = text.replace('\n', ' ').trim();
        return flat.length() > 400 ? flat.substring(0, 397) + "…" : flat;
    }

    private void toast(@NonNull String message) {
        Toast.makeText(requireContext(), message, Toast.LENGTH_LONG).show();
    }

    private class Adapter extends RecyclerView.Adapter<Adapter.Holder> {
        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemInboundBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(items.get(position));
        }

        @Override
        public int getItemCount() {
            return items.size();
        }

        class Holder extends RecyclerView.ViewHolder {
            private final ItemInboundBinding row;

            Holder(ItemInboundBinding row) {
                super(row.getRoot());
                this.row = row;
            }

            void bind(TriageItemDto item) {
                row.channelChip.setText(item.channel != null ? item.channel : "?");
                row.intentChip.setText(item.intent == null || item.intent.isEmpty()
                        ? getString(R.string.triage_intent_unknown)
                        : LeadStates.label(item.intent));
                row.receivedText.setText(Times.dateLabel(item.createdAt));
                row.fromText.setText(item.fromAddress);
                String summary = item.summary != null && !item.summary.isEmpty()
                        ? item.summary
                        : (item.subject != null && !item.subject.isEmpty()
                        ? item.subject : item.body);
                row.summaryText.setText(summary);
                if (item.reason != null && !item.reason.isEmpty()) {
                    row.reasonText.setText(item.reason);
                    row.reasonText.setVisibility(View.VISIBLE);
                } else {
                    row.reasonText.setVisibility(View.GONE);
                }
                boolean attached = item.matchedLeadId != null
                        && !item.matchedLeadId.isEmpty();
                row.attachedText.setVisibility(attached && canReply
                        ? View.VISIBLE : View.GONE);
                if (attached && canReply) {
                    row.attachedText.setText(R.string.triage_attached_known);
                }
                row.replyButton.setVisibility(canReply ? View.VISIBLE : View.GONE);
                row.actionsButton.setOnClickListener(v -> showActions(item));
                row.replyButton.setOnClickListener(v -> reply(item));
                row.getRoot().setOnClickListener(v -> readFull(item));
            }
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
