package com.yuvipep.app.feature.home;

import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.db.CachedApproval;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.dto.ProposedAssignmentDto;
import com.yuvipep.app.core.net.dto.TriageItemDto;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentHomeBinding;
import com.yuvipep.app.databinding.ItemWaitingCardBinding;
import com.yuvipep.app.feature.approvals.ApprovalAdapter;
import com.yuvipep.app.feature.approvals.ApprovalDetailFragment;
import com.yuvipep.app.feature.approvals.DecideDialogs;
import com.yuvipep.app.feature.assignments.AssignmentConfirmFragment;
import com.yuvipep.app.feature.auth.AuthActivity;
import com.yuvipep.app.feature.auth.AuthRepository;
import com.yuvipep.app.feature.meetings.MeetingReviewFragment;

import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;
import io.noties.markwon.Markwon;

/**
 * Home — the Morning Briefing (03 §2): greeting, briefing card from
 * /digests/daily, and the merged Waiting-on-you feed with inline decides.
 */
@AndroidEntryPoint
public class HomeFragment extends Fragment {

    @Inject TokenStore tokenStore;
    @Inject AuthRepository authRepository;
    @Inject com.yuvipep.app.feature.demos.DemosRepository demosRepository;
    @Inject com.yuvipep.app.feature.followups.FollowupsRepository followupsRepository;

    private FragmentHomeBinding binding;
    private HomeViewModel viewModel;
    private ApprovalAdapter approvalAdapter;
    private Markwon markwon;

    private boolean approvalsEmpty = true;
    private boolean extrasEmpty = true;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentHomeBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        viewModel = new ViewModelProvider(this).get(HomeViewModel.class);
        // The briefing names each task's client as a yuvipep://lead/<id> link
        // (customer ask, 21 Sep 2026): tapping the name opens that client.
        // Any other link keeps Markwon's default (open in a browser).
        markwon = Markwon.builder(requireContext())
                .usePlugin(new io.noties.markwon.AbstractMarkwonPlugin() {
                    @Override
                    public void configureConfiguration(
                            @NonNull io.noties.markwon.MarkwonConfiguration.Builder builder) {
                        builder.linkResolver((textView, link) -> {
                            String leadId = BriefingLinks.leadIdOf(link);
                            if (leadId != null) {
                                push(com.yuvipep.app.feature.leads.LeadDetailFragment
                                        .create(leadId));
                            } else {
                                new io.noties.markwon.LinkResolverDef().resolve(textView, link);
                            }
                        });
                    }
                })
                .build();
        binding.briefingBody.setMovementMethod(
                android.text.method.LinkMovementMethod.getInstance());

        String name = tokenStore.getName() != null ? tokenStore.getName() : "";
        binding.homeGreeting.setText(getString(R.string.home_greeting, firstName(name)));
        StringBuilder subtitle = new StringBuilder(
                RoleHomeFragment.roleLabel(tokenStore.getRole()));
        String orgName = tokenStore.getOrgName();
        if (orgName != null && !orgName.isEmpty()) {
            subtitle.append(" · ").append(orgName);
        }
        binding.homeSubtitle.setText(subtitle.toString());

        approvalAdapter = new ApprovalAdapter(new ApprovalAdapter.Listener() {
            @Override
            public void onApprove(@NonNull CachedApproval approval) {
                viewModel.decide(approval.id, true, null);
            }

            @Override
            public void onReject(@NonNull CachedApproval approval) {
                DecideDialogs.rejectWithNote(requireContext(), note ->
                        viewModel.decide(approval.id, false, note));
            }

            @Override
            public void onOpen(@NonNull CachedApproval approval) {
                push(ApprovalDetailFragment.create(approval.id));
            }

            @Override
            public void onDismissFailure(@NonNull CachedApproval approval) {
                viewModel.dismissLocalFailure(approval.id);
            }
        });
        binding.approvalList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.approvalList.setAdapter(approvalAdapter);

        binding.bellButton.setOnClickListener(v -> {
            if (getActivity() instanceof MainActivity) {
                ((MainActivity) getActivity()).openNotifications();
            }
        });
        binding.swipeRefresh.setOnRefreshListener(() -> {
            viewModel.refreshAll();
            binding.swipeRefresh.setRefreshing(false);
        });
        binding.logoutButton.setOnClickListener(v -> confirmLogout());

        // My day (Phase 5): demos calendar + follow-up queue, both readable
        // by every role; counts refresh alongside everything else.
        binding.demosCard.setOnClickListener(v ->
                push(new com.yuvipep.app.feature.demos.DemoCalendarFragment()));
        binding.followupsCard.setOnClickListener(v ->
                push(new com.yuvipep.app.feature.followups.FollowUpQueueFragment()));

        observe();
    }

    private void refreshMyDayCounts() {
        String month = java.time.YearMonth.now().toString();
        String today = java.time.LocalDate.now().toString();
        demosRepository.month(month, null, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                int todayCount = 0;
                for (com.yuvipep.app.core.net.dto.DemoDto demo : result.data) {
                    if (today.equals(demo.date)) todayCount++;
                }
                binding.demosCardSubtitle.setText(todayCount > 0
                        ? getString(R.string.demos_card_today, todayCount)
                        : getString(R.string.demos_card_month, result.data.size()));
            } else {
                binding.demosCardSubtitle.setText(R.string.home_card_unavailable);
            }
        });
        followupsRepository.list("today", true, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                binding.followupsCardSubtitle.setText(result.data.isEmpty()
                        ? getString(R.string.followups_card_none)
                        : getString(R.string.followups_card_due, result.data.size()));
            } else {
                binding.followupsCardSubtitle.setText(R.string.home_card_unavailable);
            }
        });
    }

    private void observe() {
        viewModel.digest().observe(getViewLifecycleOwner(), result -> {
            if (result == null) return;
            if (result.isLoading()) {
                binding.briefingStatus.setText(R.string.state_loading);
                binding.briefingStatus.setVisibility(View.VISIBLE);
            } else if (result.isSuccess() && result.data != null) {
                binding.briefingStatus.setVisibility(View.GONE);
                markwon.setMarkdown(binding.briefingBody,
                        result.data.contentMd != null ? result.data.contentMd : "");
            } else if (result.isError() && result.error != null) {
                // Honest: show the backend's message; cache keeps last text.
                binding.briefingStatus.setText(result.error.message);
                binding.briefingStatus.setVisibility(View.VISIBLE);
            }
        });
        viewModel.digestFetchedAt().observe(getViewLifecycleOwner(), at -> {
            if (at != null) {
                binding.briefingStamp.setText(
                        getString(R.string.briefing_updated, Times.ago(at)));
            }
        });
        viewModel.unreadCount().observe(getViewLifecycleOwner(), count -> {
            if (count != null && count > 0) {
                binding.bellBadge.setText(count > 99 ? "99+" : String.valueOf(count));
                binding.bellBadge.setVisibility(View.VISIBLE);
            } else {
                binding.bellBadge.setVisibility(View.GONE);
            }
        });
        viewModel.approvals().observe(getViewLifecycleOwner(), rows -> {
            approvalAdapter.submitList(rows);
            approvalsEmpty = rows == null || rows.isEmpty();
            updateEmptyState();
        });
        viewModel.assignments().observe(getViewLifecycleOwner(), a -> rebuildExtras());
        viewModel.reviews().observe(getViewLifecycleOwner(), r -> rebuildExtras());
        viewModel.triage().observe(getViewLifecycleOwner(), t -> rebuildExtras());
        viewModel.recentlyOpened().observe(getViewLifecycleOwner(), o -> rebuildExtras());
        viewModel.waitingOnMe().observe(getViewLifecycleOwner(), w -> rebuildExtras());
        viewModel.decideEvent().observe(getViewLifecycleOwner(), result -> {
            if (result == null) return;
            if (result.isSuccess() && result.data != null) {
                Toast.makeText(requireContext(), result.data.queuedOffline
                                ? getString(R.string.approval_queued_offline)
                                : getString(R.string.approval_decided_toast,
                                result.data.response != null
                                        ? result.data.response.status : "applied"),
                        Toast.LENGTH_SHORT).show();
            } else if (result.isError() && result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
                viewModel.refreshAll();
            }
        });
    }

    /** Assignment batch, review-pending and triage cards above the approvals. */
    private void rebuildExtras() {
        binding.waitingExtras.removeAllViews();
        extrasEmpty = true;

        List<ProposedAssignmentDto> assignments = viewModel.assignments().getValue();
        // GET /assignments/proposed is open to every org role — it has no user
        // filter — while POST /assignments/confirm-batch needs
        // `confirm_assignments`. So the rows arrive for everybody and only a
        // lead or the admin can act on them. Offering the card to an agent
        // walked them through the whole screen to a 403 on the last tap; the
        // app must not offer what the server will refuse (05 §1).
        boolean mayConfirm = RoleGate.has(tokenStore.getRole(),
                RoleGate.CONFIRM_ASSIGNMENTS);
        if (mayConfirm && assignments != null && !assignments.isEmpty()) {
            extrasEmpty = false;
            addCard(R.drawable.ic_tab_tasks,
                    getString(R.string.waiting_assignments_title, assignments.size()),
                    getString(R.string.waiting_assignments_body),
                    () -> push(new AssignmentConfirmFragment()));
        }
        // "Blocked, waiting on you" (customer ask, 21 Sep 2026): a colleague
        // cannot move until you do, so this sits near the top. One card per
        // task; it disappears when they unblock it.
        List<com.yuvipep.app.core.net.dto.WaitingOnMeDto.Item> waiting =
                viewModel.waitingOnMe().getValue();
        if (waiting != null) {
            for (com.yuvipep.app.core.net.dto.WaitingOnMeDto.Item item : waiting) {
                extrasEmpty = false;
                String who = item.waitingUserName != null && !item.waitingUserName.isEmpty()
                        ? item.waitingUserName : getString(R.string.waiting_on_you_someone);
                addCard(R.drawable.ic_tab_people,
                        getString(R.string.waiting_on_you_title, who),
                        WaitingOnYou.body(item),
                        () -> openWaiting(item));
            }
        }
        List<HomeViewModel.ReviewPending> reviews = viewModel.reviews().getValue();
        if (reviews != null) {
            for (HomeViewModel.ReviewPending review : reviews) {
                extrasEmpty = false;
                addCard(R.drawable.ic_tab_mic,
                        getString(R.string.waiting_review_title),
                        review.itemCount + " extracted item(s) to confirm",
                        () -> push(MeetingReviewFragment.create(review.meetingId)));
            }
        }
        // Newly opened leads: not a task, an announcement. Anyone on the
        // sales floor may be the one who ends up visiting the school, so this
        // is offered to every role that can see leads rather than to an owner.
        List<com.yuvipep.app.core.net.dto.RecentlyOpenedDto> opened =
                viewModel.recentlyOpened().getValue();
        if (opened != null) {
            for (com.yuvipep.app.core.net.dto.RecentlyOpenedDto lead : opened) {
                extrasEmpty = false;
                final String leadId = lead.id;
                String who = lead.ownerName == null || lead.ownerName.isEmpty()
                        ? null : lead.ownerName;
                String body = lead.reason != null && !lead.reason.isEmpty()
                        ? lead.reason
                        : (who == null ? "" : getString(
                                R.string.home_recently_opened_meta, who));
                addCard(R.drawable.ic_tab_funnel,
                        getString(R.string.home_recently_opened_title, lead.name),
                        body,
                        () -> push(com.yuvipep.app.feature.leads.LeadDetailFragment
                                .create(leadId)));
            }
        }

        List<TriageItemDto> triage = viewModel.triage().getValue();
        if (triage != null && !triage.isEmpty()) {
            extrasEmpty = false;
            addCard(R.drawable.ic_tab_inbox,
                    getString(R.string.waiting_triage_title, triage.size()),
                    getString(R.string.waiting_triage_body),
                    // The Inbox is where a human answers these (Phase 6);
                    // for a role whose bar has no Inbox slot this pushes it.
                    () -> {
                        if (getActivity() instanceof com.yuvipep.app.MainActivity) {
                            ((com.yuvipep.app.MainActivity) getActivity()).openInbox();
                        }
                    });
        }
        updateEmptyState();
    }

    private void openWaiting(@NonNull com.yuvipep.app.core.net.dto.WaitingOnMeDto.Item item) {
        switch (WaitingOnYou.target(item)) {
            case PROJECT:
                push(com.yuvipep.app.feature.projects.ProjectDetailFragment.create(item.projectId));
                break;
            case LEAD:
                push(com.yuvipep.app.feature.leads.LeadDetailFragment.create(item.leadId));
                break;
            default:
                // Nothing to open: the card already says everything the server
                // knows, so show it in full rather than pretend to navigate.
                new com.google.android.material.dialog.MaterialAlertDialogBuilder(requireContext())
                        .setTitle(item.title)
                        .setMessage(WaitingOnYou.body(item))
                        .setPositiveButton(android.R.string.ok, null)
                        .show();
                break;
        }
    }

    private void addCard(int icon, String title, String body, Runnable onTap) {
        ItemWaitingCardBinding card = ItemWaitingCardBinding.inflate(
                getLayoutInflater(), binding.waitingExtras, false);
        card.cardIcon.setImageResource(icon);
        card.cardTitle.setText(title);
        card.cardBody.setText(body);
        card.getRoot().setOnClickListener(v -> onTap.run());
        binding.waitingExtras.addView(card.getRoot());
    }

    private void updateEmptyState() {
        binding.waitingEmpty.setVisibility(
                approvalsEmpty && extrasEmpty ? View.VISIBLE : View.GONE);
    }

    private void push(@NonNull Fragment fragment) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(fragment);
        }
    }

    @Override
    public void onResume() {
        super.onResume();
        viewModel.refreshAll();
        refreshMyDayCounts();
    }

    private void confirmLogout() {
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.logout_confirm_title)
                .setMessage(R.string.logout_confirm_body)
                .setPositiveButton(R.string.action_logout, (d, w) ->
                        authRepository.logout(() -> {
                            Intent intent = new Intent(requireContext(), AuthActivity.class);
                            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                                    | Intent.FLAG_ACTIVITY_CLEAR_TASK);
                            startActivity(intent);
                        }))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private static String firstName(@NonNull String name) {
        int space = name.indexOf(' ');
        return space > 0 ? name.substring(0, space) : name;
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
