package com.yuvipep.app.feature.leads;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.snackbar.Snackbar;
import com.google.android.material.tabs.TabLayout;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.ContactDto;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.net.dto.ProjectDto;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentLeadDetailBinding;
import com.yuvipep.app.feature.meetings.MeetingDetailFragment;
import com.yuvipep.app.feature.meetings.NotesComposerFragment;
import com.yuvipep.app.feature.meetings.RecorderFragment;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Lead detail (03 §4): header with state chip + importance star, the
 * AI state-suggestion banner (accept round-trips through PATCH state;
 * "keep" is a local dismissal — the backend keeps its suggestion until the
 * state actually changes, and the app says so honestly), and six tabs
 * rendered through one generic row list.
 */
@AndroidEntryPoint
public class LeadDetailFragment extends Fragment {

    private static final String ARG_LEAD = "lead_id";
    private static final String PREFS = "yuvipep_lead_ui";

    private static final int TAB_OVERVIEW = 0;
    private static final int TAB_CONTACTS = 1;
    private static final int TAB_PROJECTS = 2;
    private static final int TAB_NOTEBOOK = 3;
    // Meetings sits ahead of History: one is work, the other is a record.
    // These values are tab POSITIONS — keep them in step with the titles
    // array in onViewCreated, which is what actually builds the strip.
    private static final int TAB_MEETINGS = 4;
    private static final int TAB_HISTORY = 5;

    public static LeadDetailFragment create(@NonNull String leadId) {
        LeadDetailFragment fragment = new LeadDetailFragment();
        Bundle args = new Bundle();
        args.putString(ARG_LEAD, leadId);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject LeadsRepository repository;
    @Inject com.yuvipep.app.feature.relationships.RelationshipRepository relationships;

    /** Who looks after this client once the selling is done, plus what we
     *  know about them. Null until fetched, and null forever for the many
     *  clients nobody looks after — the Overview tab simply omits the
     *  section then rather than showing an empty one. */
    @Nullable private com.yuvipep.app.core.net.dto.RelationshipDto.Envelope relationship;

    /** Rounds of business with this client. Empty for almost every lead —
     *  cycles are only written once a client comes back — so the Overview tab
     *  shows nothing extra unless there is genuinely more than one round to
     *  tell apart. */
    private List<com.yuvipep.app.core.net.dto.LeadCycleDto> cycles = new ArrayList<>();
    @Inject TokenStore tokenStore;
    @Inject com.yuvipep.app.feature.assistant.ContextBus contextBus;
    @Inject com.yuvipep.app.feature.demos.DemosRepository demosRepository;
    @Inject com.yuvipep.app.feature.tasks.TasksRepository tasksRepository;

    private FragmentLeadDetailBinding binding;
    private final RowAdapter adapter = new RowAdapter();
    private String leadId;
    private LeadDetailResponse lead;
    private List<ProjectDto> projects;
    private int currentTab = TAB_OVERVIEW;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentLeadDetailBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        leadId = requireArguments().getString(ARG_LEAD, "");
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.rowList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.rowList.setAdapter(adapter);

        String[] titles = {
                getString(R.string.lead_tab_overview),
                getString(R.string.lead_tab_contacts),
                getString(R.string.lead_tab_projects),
                getString(R.string.lead_tab_notebook),
                getString(R.string.lead_tab_meetings),
                getString(R.string.lead_tab_history),
        };
        for (String title : titles) {
            binding.tabs.addTab(binding.tabs.newTab().setText(title));
        }
        // Re-select whatever tab was actually open — the strip defaults to
        // position 0 every time this view is recreated (e.g. returning from
        // a pushed screen), which used to desync the indicator from the
        // still-correct content (06d/Phase-4 fix, applied back here too).
        TabLayout.Tab restored = binding.tabs.getTabAt(currentTab);
        if (restored != null) restored.select();
        binding.tabs.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override
            public void onTabSelected(TabLayout.Tab tab) {
                currentTab = tab.getPosition();
                renderTab();
            }

            @Override public void onTabUnselected(TabLayout.Tab tab) { }
            @Override public void onTabReselected(TabLayout.Tab tab) { }
        });

        getParentFragmentManager().setFragmentResultListener(
                ContactSheet.RESULT_KEY, this, (key, result) -> load());
        getParentFragmentManager().setFragmentResultListener(
                ConsentSheet.RESULT_KEY, this, (key, result) ->
                        pushFragment(RecorderFragment.create(leadId,
                                lead == null ? "" : lead.name)));
        getParentFragmentManager().setFragmentResultListener(
                CardScanFragment.RESULT_KEY, this, (key, result) -> {
                    ContactSheet.showScanResult(getParentFragmentManager(), leadId,
                            result);
                    load();
                });
    }

    @Override
    public void onResume() {
        super.onResume();
        load();
    }

    private void load() {
        if (binding == null) return;
        if (lead == null) binding.stateView.showLoading();
        // Fired alongside the lead, not after it: the two are independent
        // reads and the relationship section renders itself in when it lands.
        loadRelationship();
        repository.detail(leadId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                lead = result.data;
                contextBus.set("lead", leadId, lead.name);
                renderHeader();
                renderTab();
            } else if (result.isError() && result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    private void renderHeader() {
        binding.leadName.setText(lead.name);
        binding.stateChip.setText(LeadStates.label(lead.state));
        binding.stateChip.setBackgroundTintList(ContextCompat.getColorStateList(
                requireContext(), LeadStates.color(lead.state)));
        binding.stateChip.setOnClickListener(v -> changeStateDialog());

        StringBuilder meta = new StringBuilder();
        if (lead.city != null && !lead.city.isEmpty()) meta.append(lead.city);
        if (lead.lastActivityAt != null) {
            if (meta.length() > 0) meta.append(" · ");
            meta.append(getString(R.string.lead_updated,
                    Times.ago(Times.parseUtc(lead.lastActivityAt))));
        }
        binding.leadMeta.setText(meta);

        if (lead.ownerName != null && !lead.ownerName.isEmpty()) {
            binding.ownerLine.setText(
                    getString(R.string.lead_owner_label, lead.ownerName));
            binding.ownerLine.setVisibility(View.VISIBLE);
        } else {
            binding.ownerLine.setVisibility(View.GONE);
        }

        binding.timeline.bind(lead.stateHistory, lead.state);
        binding.timelineScroll.setVisibility(
                binding.timeline.getVisibility() == View.VISIBLE
                        ? View.VISIBLE : View.GONE);

        boolean canManage = RoleGate.has(tokenStore.getRole(), RoleGate.MANAGE_LEADS);
        binding.importantButton.setImageResource(lead.isImportant
                ? R.drawable.ic_star_filled : R.drawable.ic_star);
        binding.importantButton.setImageTintList(ContextCompat.getColorStateList(
                requireContext(), lead.isImportant
                        ? R.color.brand_accent : R.color.md_light_outline));
        binding.importantButton.setOnClickListener(canManage ? v -> toggleImportant()
                : v -> Toast.makeText(requireContext(),
                        R.string.lead_no_manage_permission, Toast.LENGTH_SHORT).show());

        renderSuggestion();
    }

    private void renderSuggestion() {
        boolean canManage = RoleGate.has(tokenStore.getRole(), RoleGate.MANAGE_LEADS);
        if (lead.suggestedState == null || dismissed() || !canManage) {
            binding.suggestionBanner.setVisibility(View.GONE);
            return;
        }
        binding.suggestionBanner.setVisibility(View.VISIBLE);
        String reason = lead.suggestedStateReason == null ? ""
                : " — " + lead.suggestedStateReason;
        binding.suggestionText.setText(getString(R.string.lead_suggestion_text,
                LeadStates.label(lead.suggestedState).toLowerCase(), reason));
        binding.suggestionAccept.setOnClickListener(v -> {
            binding.suggestionAccept.setEnabled(false);
            repository.changeState(leadId, lead.suggestedState,
                    "Accepted AI suggestion", result -> {
                        if (binding == null) return;
                        binding.suggestionAccept.setEnabled(true);
                        if (result.isSuccess()) {
                            Snackbar.make(binding.getRoot(),
                                    getString(R.string.lead_state_changed,
                                            LeadStates.label(lead.suggestedState)),
                                    Snackbar.LENGTH_SHORT).show();
                            load();
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
        });
        binding.suggestionWhy.setOnClickListener(v ->
                com.yuvipep.app.feature.assistant.WhySheet.open(
                        getParentFragmentManager(), "lead", leadId));
        binding.suggestionKeep.setOnClickListener(v -> {
            prefs().edit().putBoolean(dismissKey(), true).apply();
            binding.suggestionBanner.setVisibility(View.GONE);
            Snackbar.make(binding.getRoot(), R.string.lead_suggestion_kept,
                    Snackbar.LENGTH_LONG).show();
        });
    }

    private boolean dismissed() {
        return prefs().getBoolean(dismissKey(), false);
    }

    private String dismissKey() {
        return "dismiss_" + leadId + "_" + lead.suggestedState;
    }

    private SharedPreferences prefs() {
        return requireContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private void toggleImportant() {
        com.yuvipep.app.core.net.dto.LeadRequests.Update body =
                new com.yuvipep.app.core.net.dto.LeadRequests.Update();
        body.isImportant = !lead.isImportant;
        repository.update(leadId, body, result -> {
            if (binding == null) return;
            if (result.isSuccess()) {
                load();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message,
                        Snackbar.LENGTH_LONG).show();
            }
        });
    }

    private void changeStateDialog() {
        if (!RoleGate.has(tokenStore.getRole(), RoleGate.MANAGE_LEADS)) {
            Toast.makeText(requireContext(), R.string.lead_no_manage_permission,
                    Toast.LENGTH_SHORT).show();
            return;
        }
        String[] labels = new String[LeadStates.ALL.length];
        for (int i = 0; i < LeadStates.ALL.length; i++) {
            labels[i] = LeadStates.label(LeadStates.ALL[i]);
        }
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.lead_change_state)
                .setItems(labels, (d, which) -> {
                    // The backend owns the transition rules; a refused move
                    // shows its message verbatim.
                    repository.changeState(leadId, LeadStates.ALL[which], null,
                            result -> {
                                if (binding == null) return;
                                if (result.isSuccess()) {
                                    load();
                                } else if (result.error != null) {
                                    Snackbar.make(binding.getRoot(),
                                            result.error.message,
                                            Snackbar.LENGTH_LONG).show();
                                }
                            });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    // ── Tabs ─────────────────────────────────────────────────────────

    private void renderTab() {
        if (lead == null || binding == null) return;
        binding.stateView.hide();
        binding.actionPrimary.setVisibility(View.GONE);
        binding.actionSecondary.setVisibility(View.GONE);
        boolean canManage = RoleGate.has(tokenStore.getRole(), RoleGate.MANAGE_LEADS);
        boolean canRecord = RoleGate.has(tokenStore.getRole(), RoleGate.RECORD_MEETING);

        switch (currentTab) {
            case TAB_CONTACTS:
                renderContacts();
                if (canManage) {
                    showActions(getString(R.string.lead_scan_card),
                            this::openCardScan,
                            getString(R.string.lead_add_contact),
                            () -> ContactSheet.showAdd(getParentFragmentManager(),
                                    leadId));
                }
                break;
            case TAB_PROJECTS:
                // Nothing to show and nothing to do until the lead is real.
                if (LeadStates.isPreSales(lead.state)) {
                    showPreSalesLock();
                    break;
                }
                renderProjects();
                break;
            case TAB_NOTEBOOK:
                renderNotebook();
                if (canManage) {
                    showActions(getString(R.string.lead_add_note), this::addNote,
                            null, null);
                }
                break;
            case TAB_HISTORY:
                renderHistory();
                break;
            case TAB_MEETINGS:
                // The backend refuses meetings on a cold-calling lead; say so
                // here rather than letting the recorder fail at upload time.
                if (LeadStates.isPreSales(lead.state)) {
                    showPreSalesLock();
                    break;
                }
                renderMeetings();
                if (canRecord) {
                    showActions(getString(R.string.lead_record_meeting),
                            this::startRecordingFlow,
                            getString(R.string.lead_type_notes),
                            () -> pushFragment(NotesComposerFragment.create(
                                    leadId, lead.name)));
                }
                break;
            case TAB_OVERVIEW:
            default:
                renderOverview();
                if (LeadStates.isPreSales(lead.state) && isOwner()) {
                    // The owner made the calls, so the owner answers the only
                    // question this lead is currently asking.
                    showActions(getString(R.string.lead_open_action), this::openLead,
                            getString(R.string.lead_drop_action), this::dropLead);
                } else if (LeadStates.isClosed(lead.state) && canHandOver()) {
                    // Won and delivered. Handing the client to a relationship
                    // manager is offered, never forced: leaving it closed is a
                    // real choice and stays the default if nobody taps.
                    showActions(getString(R.string.demos_book), this::bookDemo,
                            getString(R.string.lead_handover_action),
                            this::handOverDialog);
                } else if (!LeadStates.isPreSales(lead.state)) {
                    // Book demo (Phase 5, 03 §11) — the button is discoverable
                    // for every role; roles without schedule_demos get the
                    // honest explanation instead of a hidden capability (05 §8).
                    showActions(getString(R.string.demos_book), this::bookDemo,
                            null, null);
                }
                break;
        }
    }

    /**
     * The relationship section, first on Overview when there is one.
     *
     * <p>First because for a relationship manager it is the whole reason the
     * screen is open, and absent entirely otherwise — most clients never get
     * a relationship manager, and an empty "Relationship" heading on every
     * lead in the pipeline would be noise for everyone else.
     *
     * <p>The story is the backend's `replay_story`, the same block the revival
     * card uses. Reusing it means there is one account of a client and one
     * place to improve it, rather than two that can disagree.
     */
    private void addRelationship(@NonNull List<RowAdapter.Row> rows) {
        if (relationship == null || relationship.engagement == null) return;
        addOpportunityCard(rows);
        rows.add(new RowAdapter.Row(
                getString(R.string.relationship_section_title),
                getString(R.string.relationship_managed_by,
                        relationship.engagement.managerName == null
                                ? "" : relationship.engagement.managerName),
                relationship.engagement.reason, null, null));
        if (relationship.story != null && !relationship.story.isEmpty()) {
            rows.add(new RowAdapter.Row(
                    getString(R.string.relationship_story_title),
                    relationship.story, null, null, null));
        }
        if (relationship.intelligence != null && !relationship.intelligence.isEmpty()) {
            StringBuilder notes = new StringBuilder();
            for (com.yuvipep.app.core.net.dto.RelationshipDto.Note n
                    : relationship.intelligence) {
                if (n.note == null || n.note.isEmpty()) continue;
                if (notes.length() > 0) notes.append("\n");
                notes.append("• ").append(n.note);
            }
            if (notes.length() > 0) {
                rows.add(new RowAdapter.Row(
                        getString(R.string.relationship_approach_title),
                        notes.toString(), null, null, null));
            }
        }
    }

    /**
     * "They might be ready to buy again" — first on the screen when it is open.
     *
     * <p>Shows the client's own words, not just the assistant's conclusion:
     * the person tapping Accept is making the call, and a paraphrase is not
     * evidence. Only someone with `manage_relationships` is offered the
     * buttons; everyone else sees the card and can read it, which is the
     * honest version of "you cannot act on this" (05 §8).
     */
    private void addOpportunityCard(@NonNull List<RowAdapter.Row> rows) {
        com.yuvipep.app.core.net.dto.RelationshipDto.Opportunity opp =
                relationship.engagement.opportunity;
        if (opp == null || !opp.isOpen()) return;

        boolean canDecide = RoleGate.has(tokenStore.getRole(),
                RoleGate.MANAGE_RELATIONSHIPS);
        StringBuilder body = new StringBuilder();
        if (opp.reason != null && !opp.reason.isEmpty()) body.append(opp.reason);
        if (opp.quote != null && !opp.quote.isEmpty()) {
            if (body.length() > 0) body.append("\n\n");
            body.append(getString(R.string.opportunity_quote, opp.quote));
        }
        rows.add(new RowAdapter.Row(
                getString(R.string.opportunity_title),
                body.toString(),
                canDecide ? getString(R.string.opportunity_tap_to_decide) : null,
                getString(R.string.opportunity_badge),
                canDecide ? this::opportunityDialog : null));
    }

    private void opportunityDialog() {
        if (lead == null) return;
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(getString(R.string.opportunity_dialog_title, lead.name))
                .setMessage(R.string.opportunity_dialog_body)
                .setPositiveButton(R.string.opportunity_accept,
                        (d, w) -> decideOpportunity(true))
                .setNeutralButton(R.string.opportunity_dismiss,
                        (d, w) -> decideOpportunity(false))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void decideOpportunity(boolean accept) {
        com.yuvipep.app.core.util.RepoCallback<java.util.Map<String, Object>> cb =
                result -> {
                    if (binding == null) return;
                    if (result.isSuccess()) {
                        Snackbar.make(binding.getRoot(),
                                accept ? R.string.opportunity_accepted
                                       : R.string.opportunity_dismissed,
                                Snackbar.LENGTH_LONG).show();
                        load();
                    } else if (result.error != null) {
                        Snackbar.make(binding.getRoot(), result.error.message,
                                Snackbar.LENGTH_LONG).show();
                    }
                };
        if (accept) {
            relationships.acceptOpportunity(leadId, null, cb);
        } else {
            relationships.dismissOpportunity(leadId, null, cb);
        }
    }

    /**
     * One card per round of business, oldest first.
     *
     * <p>Absent entirely for a client sold to once, which is almost all of
     * them — a single-round lead has no cycle rows and its page is exactly
     * what it always was. The cards appear the moment there is more than one
     * round to tell apart, which is the only time anyone needs them.
     */
    private void addCycles(@NonNull List<RowAdapter.Row> rows) {
        if (cycles == null || cycles.isEmpty()) return;
        for (com.yuvipep.app.core.net.dto.LeadCycleDto cycle : cycles) {
            String who = cycle.ownerName == null || cycle.ownerName.isEmpty()
                    ? getString(R.string.cycle_no_owner)
                    : cycle.ownerName;
            String source = "relationship".equals(cycle.source)
                    ? getString(R.string.cycle_source_relationship)
                    : getString(R.string.cycle_source_cold_call);
            rows.add(new RowAdapter.Row(
                    getString(R.string.cycle_title, cycle.cycleNumber),
                    getString(R.string.cycle_body, source, who),
                    cycle.note,
                    cycle.needsOwner()
                            ? getString(R.string.cycle_needs_owner)
                            : LeadStates.label(cycle.outcome),
                    cycle.needsOwner() && canAssignRound()
                            ? () -> assignRoundOwner(cycle.cycleNumber)
                            : null));
        }
    }

    /** The server allows a sales lead or the org admin; this mirrors it so
     *  nobody is offered a tap that only fails. */
    private boolean canAssignRound() {
        String role = tokenStore.getRole();
        return RoleGate.SALES_LEAD.equals(role) || RoleGate.ORG_ADMIN.equals(role);
    }

    /**
     * Hand the reopened round to a salesperson.
     *
     * <p>Reuses the same picker a new lead uses — sales agents only — because
     * it is the same question: who is going to work this client.
     */
    private void assignRoundOwner(int cycleNumber) {
        repository.assignableOwners(result -> {
            if (binding == null || lead == null) return;
            if (!result.isSuccess() || result.data == null || result.data.isEmpty()) {
                Snackbar.make(binding.getRoot(), R.string.cycle_no_agents,
                        Snackbar.LENGTH_LONG).show();
                return;
            }
            List<com.yuvipep.app.core.net.dto.OrgUserDto> people = result.data;
            String[] labels = new String[people.size()];
            for (int i = 0; i < people.size(); i++) {
                labels[i] = people.get(i).name;
            }
            final int[] chosen = {0};
            new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                    .setTitle(getString(R.string.cycle_assign_title, cycleNumber))
                    .setSingleChoiceItems(labels, 0, (d, which) -> chosen[0] = which)
                    .setPositiveButton(R.string.cycle_assign_action, (d, w) ->
                            relationships.setCycleOwner(
                                    leadId, cycleNumber, people.get(chosen[0]).id,
                                    assigned -> {
                                        if (binding == null) return;
                                        if (assigned.isSuccess()) {
                                            load();
                                        } else if (assigned.error != null) {
                                            Snackbar.make(binding.getRoot(),
                                                    assigned.error.message,
                                                    Snackbar.LENGTH_LONG).show();
                                        }
                                    }))
                    .setNegativeButton(android.R.string.cancel, null)
                    .show();
        });
    }

    /**
     * Fetch the relationship alongside the lead.
     *
     * <p>Deliberately silent on failure. This is extra context on a screen
     * that already works without it, so a failed call leaves the section out
     * instead of putting an error over a lead someone is trying to read.
     */
    private void loadRelationship() {
        relationships.forLead(leadId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                relationship = result.data;
                if (currentTab == TAB_OVERVIEW) renderTab();
            }
        });
        relationships.cycles(leadId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                cycles = result.data;
                if (currentTab == TAB_OVERVIEW) renderTab();
            }
        });
    }

    private void bookDemo() {
        if (!RoleGate.has(tokenStore.getRole(), RoleGate.SCHEDULE_DEMOS)) {
            Toast.makeText(requireContext(), R.string.demos_no_schedule_permission,
                    Toast.LENGTH_LONG).show();
            return;
        }
        com.yuvipep.app.feature.demos.BookDemoDialog.open(requireContext(),
                demosRepository, tasksRepository, leadId, lead == null ? null : lead.name,
                new com.yuvipep.app.feature.demos.BookDemoDialog.Host() {
                    @Override
                    public void onBooked(@NonNull String resultMessage) {
                        if (binding == null) return;
                        new com.google.android.material.dialog.MaterialAlertDialogBuilder(
                                requireContext())
                                .setTitle(R.string.demos_booked_title)
                                .setMessage(resultMessage)
                                .setPositiveButton(android.R.string.ok, null)
                                .show();
                    }

                    @Override
                    public void onFailed(@NonNull String backendMessage) {
                        if (binding == null) return;
                        Snackbar.make(binding.getRoot(), backendMessage,
                                Snackbar.LENGTH_LONG).show();
                    }
                });
    }

    /** primary shows on the right; secondary (optional) on the left. */
    /** True when the signed-in user is this lead's owner. */
    private boolean isOwner() {
        return lead != null && lead.ownerId != null
                && lead.ownerId.equals(tokenStore.getUserId());
    }

    /**
     * Who is offered the handover button.
     *
     * <p>The server's rule is "the owner, a sales lead, or the org admin",
     * and it is the enforcer. This mirrors it so an agent is not shown a
     * button on a colleague's client that would only be refused on the last
     * tap — the same mistake F51 made with the assignment-batch card.
     */
    private boolean canHandOver() {
        String role = tokenStore.getRole();
        if (!RoleGate.has(role, RoleGate.ASSIGN_RELATIONSHIP_MANAGER)) return false;
        return RoleGate.SALES_LEAD.equals(role) || RoleGate.ORG_ADMIN.equals(role)
                || isOwner();
    }

    /**
     * Hand a finished client to a relationship manager.
     *
     * <p>Two ways through, because the assistant will sometimes be wrong and
     * there has to be a fix that is not a developer: take its pick, or choose
     * from the list. Either way the server records why, so the
     * "Why this person?" sheet has something to say afterwards.
     */
    private void handOverDialog() {
        if (lead == null) return;
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(getString(R.string.lead_handover_title, lead.name))
                .setMessage(R.string.lead_handover_message)
                .setPositiveButton(R.string.lead_handover_auto,
                        (d, w) -> submitHandover(null))
                .setNeutralButton(R.string.lead_handover_choose,
                        (d, w) -> chooseManagerDialog())
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void chooseManagerDialog() {
        relationships.managers(result -> {
            if (binding == null || lead == null) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null) {
                    Snackbar.make(binding.getRoot(), result.error.message,
                            Snackbar.LENGTH_LONG).show();
                }
                return;
            }
            List<com.yuvipep.app.core.net.dto.RelationshipDto.Manager> people =
                    result.data;
            if (people.isEmpty()) {
                // The same thing the server would say, said before the round
                // trip rather than after it.
                Snackbar.make(binding.getRoot(), R.string.lead_handover_none,
                        Snackbar.LENGTH_LONG).show();
                return;
            }
            String[] labels = new String[people.size()];
            for (int i = 0; i < people.size(); i++) {
                String designation = people.get(i).designation;
                labels[i] = designation == null || designation.isEmpty()
                        ? people.get(i).name
                        : people.get(i).name + " · " + designation;
            }
            final int[] chosen = {0};
            new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                    .setTitle(getString(R.string.lead_handover_pick_title, lead.name))
                    .setSingleChoiceItems(labels, 0, (d, which) -> chosen[0] = which)
                    .setPositiveButton(R.string.lead_handover_action,
                            (d, w) -> submitHandover(people.get(chosen[0]).id))
                    .setNegativeButton(android.R.string.cancel, null)
                    .show();
        });
    }

    /** One place for the call. A refusal is shown verbatim: the server's
     *  wording already explains what to do about it. */
    private void submitHandover(@Nullable String managerId) {
        relationships.handOver(leadId, managerId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                String who = result.data.managerName == null
                        ? "" : result.data.managerName;
                Snackbar.make(binding.getRoot(),
                        getString(R.string.lead_handover_done, who),
                        Snackbar.LENGTH_LONG).show();
                load();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message,
                        Snackbar.LENGTH_LONG).show();
            }
        });
    }

    /**
     * The panel behind Projects and Meetings while a lead is still being cold
     * called. The tab stays present and explains itself — the same choice the
     * Book-demo button makes for roles that cannot schedule (05 §8).
     */
    private void showPreSalesLock() {
        adapter.submit(new ArrayList<>());
        String body = isOwner()
                ? getString(R.string.lead_locked_body_self)
                : getString(R.string.lead_locked_body,
                        lead.ownerName == null || lead.ownerName.isEmpty()
                                ? getString(R.string.lead_locked_owner_unknown)
                                : lead.ownerName);
        binding.stateView.showEmpty(getString(R.string.lead_locked_title), body,
                R.drawable.ic_lock, null, null);
    }

    /** Cold call went well: the lead becomes everyone's business. */
    private void openLead() {
        final android.widget.EditText input = new android.widget.EditText(requireContext());
        input.setHint(R.string.lead_open_reason_hint);
        input.setInputType(android.text.InputType.TYPE_CLASS_TEXT
                | android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        android.widget.FrameLayout wrap = new android.widget.FrameLayout(requireContext());
        wrap.setPadding(pad, pad / 2, pad, 0);
        wrap.addView(input);
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.lead_open_action)
                .setView(wrap)
                .setPositiveButton(R.string.lead_open_action, (d, w) -> {
                    String reason = input.getText() == null ? ""
                            : input.getText().toString().trim();
                    move("open", reason.isEmpty() ? null : reason);
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    /** Cold call went nowhere. `lost_for_now` keeps the revival machinery. */
    private void dropLead() {
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.lead_drop_action)
                .setMessage(R.string.lead_drop_confirm)
                .setPositiveButton(R.string.lead_drop_action,
                        (d, w) -> move("lost_for_now", null))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    /** One place for a state move: the backend owns the rules, and a refusal
     *  (including "you are not the owner") is shown verbatim. */
    private void move(@NonNull String state, @Nullable String reason) {
        repository.changeState(leadId, state, reason, result -> {
            if (binding == null) return;
            if (result.isSuccess()) {
                load();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message,
                        Snackbar.LENGTH_LONG).show();
            }
        });
    }

    private void showActions(@NonNull String primaryLabel, @NonNull Runnable primary,
                             @Nullable String secondaryLabel,
                             @Nullable Runnable secondary) {
        binding.actionPrimary.setText(primaryLabel);
        binding.actionPrimary.setVisibility(View.VISIBLE);
        binding.actionPrimary.setOnClickListener(v -> primary.run());
        if (secondaryLabel != null && secondary != null) {
            binding.actionSecondary.setText(secondaryLabel);
            binding.actionSecondary.setVisibility(View.VISIBLE);
            binding.actionSecondary.setOnClickListener(v -> secondary.run());
        }
    }

    private void renderOverview() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        addRelationship(rows);
        addCycles(rows);
        addFact(rows, getString(R.string.lead_fact_address), lead.address);
        addFact(rows, getString(R.string.lead_fact_city), joined(lead.city, lead.region));
        addFact(rows, getString(R.string.lead_fact_website), lead.website);
        addFact(rows, getString(R.string.lead_fact_source), lead.source);
        addFact(rows, getString(R.string.lead_fact_notes), lead.notes);
        if (lead.actionItems != null) {
            for (LeadDetailResponse.ActionItemRow item : lead.actionItems) {
                if ("open".equals(item.status) || "in_progress".equals(item.status)) {
                    rows.add(new RowAdapter.Row(item.title, null,
                            getString(R.string.lead_next_step_meta, item.status,
                                    item.dueDate == null ? "—"
                                            : Times.dateLabel(item.dueDate)),
                            null, null));
                }
            }
        }
        if (lead.followups != null) {
            for (LeadDetailResponse.FollowupRow f : lead.followups) {
                if ("pending".equals(f.status) || "open".equals(f.status)) {
                    rows.add(new RowAdapter.Row(
                            getString(R.string.lead_followup_title, f.channel),
                            f.note, getString(R.string.lead_followup_meta,
                                    Times.dateLabel(f.dueDate)),
                            null, null));
                }
            }
        }
        if (lead.proposals != null) {
            for (LeadDetailResponse.ProposalRow p : lead.proposals) {
                final String proposalId = p.id;
                rows.add(new RowAdapter.Row(
                        p.title == null ? getString(R.string.lead_proposal) : p.title,
                        p.totalAmount == null ? null
                                : com.yuvipep.app.core.util.Money.format(
                                        p.totalAmount, p.currency),
                        getString(R.string.lead_proposal_meta, p.status), null,
                        proposalId == null ? null : () -> pushFragment(
                                com.yuvipep.app.feature.proposals
                                        .ProposalDetailFragment.create(proposalId))));
            }
        }
        // BESIDE the proposals, never merged into them. The two lists are
        // separate all the way from the backend's tables, and joining them
        // here would put a signed contract in the middle of the sales
        // pipeline on the one screen a salesperson actually reads.
        if (lead.mous != null) {
            for (LeadDetailResponse.MouRow m : lead.mous) {
                // Tapping it opens the contract. Until this, the row named a
                // document and went nowhere, so a contract the assistant had
                // built could not be read anywhere in the app -- which the
                // owner found on a phone, on the first one they made.
                final String mouId = m.id;
                rows.add(new RowAdapter.Row(
                        com.yuvipep.app.feature.mous.MouLines.rowTitle(
                                m.title, getString(R.string.lead_mou)),
                        null,
                        // WITH THE DATE. A client can have several contracts
                        // and they all carry the same title -- the programme
                        // and the client name -- so without it the rows are
                        // indistinguishable, and the owner read a superseded
                        // one and reported its figures as a defect.
                        "sent".equals(m.status)
                                ? getString(R.string.lead_mou_sent_meta,
                                        Times.dateLabel(m.createdAt))
                                : getString(R.string.lead_mou_meta, m.status,
                                        Times.dateLabel(m.createdAt)),
                        null,
                        mouId == null ? null : () -> pushFragment(
                                com.yuvipep.app.feature.mous
                                        .MouDetailFragment.create(mouId))));
            }
        }
        submitOrEmpty(rows, getString(R.string.lead_overview_empty));
    }

    private void addFact(List<RowAdapter.Row> rows, String label,
                         @Nullable String value) {
        if (value != null && !value.isEmpty()) {
            rows.add(new RowAdapter.Row(label, value, null, null, null));
        }
    }

    @Nullable
    private static String joined(@Nullable String a, @Nullable String b) {
        boolean hasA = a != null && !a.isEmpty();
        boolean hasB = b != null && !b.isEmpty();
        if (hasA && hasB) return a + ", " + b;
        if (hasA) return a;
        return hasB ? b : null;
    }

    private void renderContacts() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        if (lead.contacts != null) {
            for (ContactDto contact : lead.contacts) {
                String body = joined(contact.email, contact.phone);
                String meta = contact.title;
                if (contact.isPrimary) {
                    meta = meta == null ? getString(R.string.contact_primary)
                            : meta + " · " + getString(R.string.contact_primary);
                }
                rows.add(new RowAdapter.Row(contact.name, body, meta,
                        contact.needsReview
                                ? getString(R.string.contact_needs_review) : null,
                        () -> ContactSheet.showEdit(getParentFragmentManager(),
                                leadId, contact)));
            }
        }
        submitOrEmpty(rows, getString(R.string.lead_contacts_empty));
    }

    private void renderProjects() {
        if (projects == null) {
            binding.stateView.showLoading();
            repository.projectsForLead(leadId, result -> {
                if (binding == null || currentTab != TAB_PROJECTS) return;
                if (result.isSuccess() && result.data != null) {
                    projects = result.data;
                    renderProjects();
                } else if (result.error != null) {
                    binding.stateView.showError(result.error.message,
                            this::renderProjects);
                }
            });
            return;
        }
        List<RowAdapter.Row> rows = new ArrayList<>();
        for (ProjectDto project : projects) {
            String body = joined(LeadStates.label(project.status),
                    project.health == null ? null : LeadStates.label(project.health));
            rows.add(new RowAdapter.Row(project.name, body, project.objective, null,
                    () -> pushFragment(com.yuvipep.app.feature.projects.ProjectDetailFragment
                            .create(project.id))));
        }
        submitOrEmpty(rows, getString(R.string.lead_projects_empty));
    }

    private void renderNotebook() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        if (lead.intelligence != null) {
            for (LeadDetailResponse.IntelligenceRow note : lead.intelligence) {
                String meta = (note.category == null ? "" : note.category + " · ")
                        + (note.source == null ? "" : note.source) + " · "
                        + Times.ago(Times.parseUtc(note.createdAt));
                rows.add(new RowAdapter.Row(note.note, null, meta, null, null));
            }
        }
        submitOrEmpty(rows, getString(R.string.lead_notebook_empty));
    }

    private void renderHistory() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        if (lead.stateHistory != null) {
            for (LeadDetailResponse.HistoryRow h : lead.stateHistory) {
                String title = (h.from == null ? getString(R.string.lead_history_created)
                        : LeadStates.label(h.from)) + "  →  " + LeadStates.label(h.to);
                rows.add(new RowAdapter.Row(title, h.reason,
                        Times.ago(Times.parseUtc(h.at)), null, null));
            }
        }
        submitOrEmpty(rows, getString(R.string.lead_history_empty));
    }

    private void renderMeetings() {
        List<RowAdapter.Row> rows = new ArrayList<>();
        if (lead.meetings != null) {
            for (LeadDetailResponse.MeetingRow m : lead.meetings) {
                String duration = m.durationSeconds == null ? null
                        : (m.durationSeconds / 60) + " min";
                rows.add(new RowAdapter.Row(LeadStates.label(m.status), duration,
                        m.startedAt == null ? null
                                : Times.ago(Times.parseUtc(m.startedAt)),
                        "review_pending".equals(m.status)
                                ? getString(R.string.meeting_review_badge) : null,
                        () -> pushFragment(MeetingDetailFragment.create(m.id))));
            }
        }
        submitOrEmpty(rows, getString(R.string.lead_meetings_empty));
    }

    private void submitOrEmpty(List<RowAdapter.Row> rows, String emptyText) {
        adapter.submit(rows);
        if (rows.isEmpty()) {
            binding.stateView.showEmpty(emptyText, null, R.drawable.ic_tab_people,
                    null, null);
        } else {
            binding.stateView.hide();
        }
    }

    // ── Actions ──────────────────────────────────────────────────────

    private void addNote() {
        android.widget.EditText input = new android.widget.EditText(requireContext());
        input.setHint(R.string.lead_add_note_hint);
        input.setMinLines(2);
        android.widget.LinearLayout wrapper =
                new android.widget.LinearLayout(requireContext());
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        wrapper.setPadding(pad, pad / 2, pad, 0);
        wrapper.addView(input, new android.widget.LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.lead_add_note)
                .setView(wrapper)
                .setPositiveButton(R.string.action_save, (d, w) -> {
                    String note = input.getText().toString().trim();
                    if (note.length() < 2) return;
                    repository.addIntelligence(leadId, note, null, result -> {
                        if (binding == null) return;
                        if (result.isSuccess()) {
                            load();
                        } else if (result.error != null) {
                            Snackbar.make(binding.getRoot(), result.error.message,
                                    Snackbar.LENGTH_LONG).show();
                        }
                    });
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void openCardScan() {
        pushFragment(CardScanFragment.create(leadId));
    }

    private void startRecordingFlow() {
        // Consent gate first, every time — the backend has no "consent on
        // file" lookup, so the app never pretends to know (08 §1).
        ConsentSheet.open(getParentFragmentManager(), leadId);
    }

    private void pushFragment(@NonNull Fragment fragment) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(fragment);
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
