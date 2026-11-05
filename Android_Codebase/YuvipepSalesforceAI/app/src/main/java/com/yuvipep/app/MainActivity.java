package com.yuvipep.app;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.Fragment;

import com.google.android.material.snackbar.Snackbar;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.OfflineQueue;
import com.yuvipep.app.core.net.SessionBus;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.databinding.ActivityMainBinding;
import com.yuvipep.app.feature.approvals.ApprovalDetailFragment;
import com.yuvipep.app.feature.approvals.ApprovalsInboxFragment;
import com.yuvipep.app.feature.auth.AuthActivity;
import com.yuvipep.app.feature.common.PlaceholderFragment;
import com.yuvipep.app.feature.home.HomeFragment;
import com.yuvipep.app.feature.home.RoleHomeFragment;
import com.yuvipep.app.feature.meetings.MeetingReviewFragment;
import com.yuvipep.app.feature.notifications.ForegroundPoller;
import com.yuvipep.app.feature.notifications.NotificationCenterFragment;
import com.yuvipep.app.feature.notifications.NotificationRepository;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The app proper: bottom navigation assembled at login from the role
 * (05_ROLE_EXPERIENCES). Phase 1 lights up Home (briefing + waiting feed),
 * the notification center and the approvals inbox; other tabs stay honest
 * placeholders naming their phase.
 */
@AndroidEntryPoint
public class MainActivity extends AppCompatActivity {

    public static final String EXTRA_OPEN_NOTIFICATIONS = "open_notifications";

    private static final int ID_BASE = 1000;

    @Inject TokenStore tokenStore;
    @Inject SessionBus sessionBus;
    @Inject ForegroundPoller foregroundPoller;
    @Inject NotificationRepository notificationRepository;
    @Inject OfflineQueue offlineQueue;
    // F58: needed to turn a conflict/plan id into the project that renders it.
    @Inject com.yuvipep.app.feature.projects.ProjectsRepository projectsRepository;

    private ActivityMainBinding binding;
    private Tab[] tabs;

    /** One bottom-bar slot. */
    private static class Tab {
        final String label;
        final int icon;
        final java.util.function.Supplier<Fragment> factory;

        Tab(String label, int icon, java.util.function.Supplier<Fragment> factory) {
            this.label = label;
            this.icon = icon;
            this.factory = factory;
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityMainBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        if (!tokenStore.hasSession()) {
            returnToAuth(false);
            return;
        }

        boolean offline = getIntent().getBooleanExtra(
                AuthActivity.EXTRA_OFFLINE_SESSION, false);
        binding.offlineBanner.setVisibility(
                offline ? android.view.View.VISIBLE : android.view.View.GONE);

        buildTabsForRole(tokenStore.getRole());
        populateBottomNav(savedInstanceState == null);

        sessionBus.sessionExpired().observe(this, expired -> {
            if (Boolean.TRUE.equals(expired)) {
                sessionBus.reset();
                returnToAuth(true);
            }
        });

        // In-app banner for freshly polled notifications (07 §2).
        notificationRepository.newArrivals().observe(this, fresh -> {
            if (fresh == null || fresh.isEmpty()) return;
            String title = fresh.get(0).title != null ? fresh.get(0).title : "";
            String text = fresh.size() == 1 ? title
                    : title + "  (+" + (fresh.size() - 1) + " more)";
            Snackbar.make(binding.getRoot(), text, Snackbar.LENGTH_LONG)
                    .setAnchorView(binding.bottomNav)
                    .setAction(R.string.notifications_title, v -> openNotifications())
                    .show();
        });

        requestNotificationPermissionIfNeeded();
        offlineQueue.scheduleDrain();

        if (getIntent().getBooleanExtra(EXTRA_OPEN_NOTIFICATIONS, false)) {
            openNotifications();
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (intent.getBooleanExtra(EXTRA_OPEN_NOTIFICATIONS, false)) {
            openNotifications();
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        foregroundPoller.start();
    }

    @Override
    protected void onStop() {
        super.onStop();
        foregroundPoller.stop();
    }

    private void requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(
                Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{Manifest.permission.POST_NOTIFICATIONS}, 71);
        }
    }

    private void buildTabsForRole(@Nullable String role) {
        Tab home = new Tab(getString(R.string.tab_home), R.drawable.ic_tab_home,
                HomeFragment::new);
        Tab jarvis = new Tab(getString(R.string.tab_assistant), R.drawable.ic_tab_mic,
                com.yuvipep.app.feature.assistant.AssistantFragment::new);
        Tab approvals = new Tab(getString(R.string.tab_approvals),
                R.drawable.ic_tab_approvals, ApprovalsInboxFragment::new);

        Tab leads = new Tab(getString(R.string.tab_leads), R.drawable.ic_tab_people,
                com.yuvipep.app.feature.leads.LeadsListFragment::new);

        Tab tasks = new Tab(getString(R.string.tab_tasks), R.drawable.ic_tab_tasks,
                com.yuvipep.app.feature.tasks.MyTasksFragment::new);
        Tab projects = new Tab(getString(R.string.tab_projects), R.drawable.ic_tab_folder,
                com.yuvipep.app.feature.projects.ProjectsListFragment::new);

        Tab inbox = new Tab(getString(R.string.tab_inbox), R.drawable.ic_tab_inbox,
                com.yuvipep.app.feature.inbox.InboxFragment::new);

        if (RoleGate.SALES_AGENT.equals(role)) {
            tabs = new Tab[]{home,
                    leads,
                    jarvis,
                    tasks,
                    inbox};
        } else if (RoleGate.SALES_LEAD.equals(role)) {
            tabs = new Tab[]{home,
                    new Tab(getString(R.string.tab_pipeline), R.drawable.ic_tab_funnel,
                            com.yuvipep.app.feature.projects.PipelineFragment::new),
                    jarvis,
                    approvals,
                    placeholder(R.string.tab_team, "later phase", R.drawable.ic_tab_people)};
        } else if (RoleGate.OPERATIONS_AGENT.equals(role)) {
            tabs = new Tab[]{home,
                    tasks,
                    jarvis,
                    projects,
                    placeholder(R.string.tab_more, "later phases", R.drawable.ic_tab_more)};
        } else if (RoleGate.OPERATIONS_LEAD.equals(role)) {
            tabs = new Tab[]{home,
                    new Tab(getString(R.string.tab_delivery), R.drawable.ic_tab_truck,
                            com.yuvipep.app.feature.projects.ProjectsListFragment::new),
                    jarvis,
                    placeholder(R.string.tab_incidents, "Phase 6", R.drawable.ic_tab_alert),
                    placeholder(R.string.tab_team, "later phase", R.drawable.ic_tab_people)};
        } else if (RoleGate.ORG_ADMIN.equals(role)) {
            tabs = new Tab[]{home,
                    approvals,
                    jarvis,
                    placeholder(R.string.tab_admin, "Phase 7", R.drawable.ic_tab_gear),
                    placeholder(R.string.tab_insights, "Phase 7", R.drawable.ic_tab_chart)};
        } else if (RoleGate.RELATIONSHIP_MANAGER.equals(role)) {
            // Not a salesperson's app. Their first screen is the clients they
            // look after, not a pipeline — there is no pipeline in this job.
            // No Leads tab and no Approvals: an RM holds neither manage_leads
            // nor send_proposal, so offering either would be a button that
            // only ever fails on the last tap.
            tabs = new Tab[]{
                    new Tab(getString(R.string.tab_clients), R.drawable.ic_tab_people,
                            com.yuvipep.app.feature.relationships
                                    .RelationshipHomeFragment::new),
                    tasks,
                    jarvis};
        } else if (RoleGate.SUPER_ADMIN.equals(role)) {
            // Platform flavor arrives in Phase 7; the org build stays honest.
            String note = getString(R.string.platform_note);
            tabs = new Tab[]{
                    new Tab(getString(R.string.tab_home), R.drawable.ic_tab_home,
                            RoleHomeFragment::new),
                    new Tab(getString(R.string.tab_orgs), R.drawable.ic_tab_building,
                            () -> PlaceholderFragment.create(getString(R.string.tab_orgs),
                                    "Phase 7", R.drawable.ic_tab_building, note)),
                    new Tab(getString(R.string.tab_stats), R.drawable.ic_tab_chart,
                            () -> PlaceholderFragment.create(getString(R.string.tab_stats),
                                    "Phase 7", R.drawable.ic_tab_chart, note))};
        } else {
            // Unknown role → generic member experience (05 §8).
            tabs = new Tab[]{home, tasks, jarvis};
        }
    }

    private Tab placeholder(int labelRes, String phase, int icon) {
        String label = getString(labelRes);
        return new Tab(label, icon,
                () -> PlaceholderFragment.create(label, phase, icon));
    }

    private void populateBottomNav(boolean selectFirst) {
        Menu menu = binding.bottomNav.getMenu();
        menu.clear();
        for (int i = 0; i < tabs.length; i++) {
            MenuItem item = menu.add(Menu.NONE, ID_BASE + i, i, tabs[i].label);
            item.setIcon(tabs[i].icon);
        }
        binding.bottomNav.setOnItemSelectedListener(item -> {
            int index = item.getItemId() - ID_BASE;
            if (index >= 0 && index < tabs.length) {
                showTab(index);
                return true;
            }
            return false;
        });
        if (selectFirst) {
            binding.bottomNav.setSelectedItemId(ID_BASE);
        }
    }

    private void showTab(int index) {
        // Switching tabs abandons any pushed detail screens.
        getSupportFragmentManager().popBackStackImmediate(null,
                androidx.fragment.app.FragmentManager.POP_BACK_STACK_INCLUSIVE);
        getSupportFragmentManager().beginTransaction()
                .replace(binding.mainContent.getId(), tabs[index].factory.get())
                .commitAllowingStateLoss();
    }

    /** Push a detail screen on top of the current tab (back pops it). */
    public void push(@NonNull Fragment fragment) {
        getSupportFragmentManager().beginTransaction()
                .replace(binding.mainContent.getId(), fragment)
                .addToBackStack(null)
                .commitAllowingStateLoss();
    }

    public void openNotifications() {
        push(new NotificationCenterFragment());
    }

    /**
     * Switch to the assistant tab, or push it for a role whose bar has no
     * slot for it. Used by the Inbox reply route, which has already put the
     * client on the ContextBus and a drafted command in the input box.
     */
    public void openAssistant() {
        if (!selectTabLabelled(getString(R.string.tab_assistant))) {
            push(new com.yuvipep.app.feature.assistant.AssistantFragment());
        }
    }

    /**
     * The Inbox. Only the sales agent's bar has a slot for it (05 §2); every
     * other role reaches it from Home, a notification, or here — pushed on
     * top of whatever they were doing, so back returns them to it.
     */
    public void openInbox() {
        if (!selectTabLabelled(getString(R.string.tab_inbox))) {
            push(new com.yuvipep.app.feature.inbox.InboxFragment());
        }
    }

    private boolean selectTabLabelled(@NonNull String label) {
        if (tabs == null) return false;
        for (int i = 0; i < tabs.length; i++) {
            if (label.equals(tabs[i].label)) {
                binding.bottomNav.setSelectedItemId(ID_BASE + i);
                return true;
            }
        }
        return false;
    }

    /** Notification deep link: entity → its screen, or honesty. */
    public void openEntity(@Nullable String entityType, @Nullable String entityId) {
        if ("approval".equals(entityType) && entityId != null) {
            push(ApprovalDetailFragment.create(entityId));
        } else if ("meeting".equals(entityType) && entityId != null) {
            // The pipeline screen routes onward (review gate, retry, result).
            push(com.yuvipep.app.feature.meetings.MeetingDetailFragment
                    .create(entityId));
        } else if ("lead".equals(entityType) && entityId != null) {
            push(com.yuvipep.app.feature.leads.LeadDetailFragment.create(entityId));
        } else if ("proposal".equals(entityType) && entityId != null) {
            push(com.yuvipep.app.feature.proposals.ProposalDetailFragment
                    .create(entityId));
        } else if ("mou".equals(entityType) && entityId != null) {
            // A contract is not a proposal (D-A), and the card that announces
            // one has to land on it. Without this the chat's Open fell through
            // to the client's overview, where two contracts with the same
            // title sat one above the other and the owner read the wrong one.
            push(com.yuvipep.app.feature.mous.MouDetailFragment.create(entityId));
        } else if ("project".equals(entityType) && entityId != null) {
            push(com.yuvipep.app.feature.projects.ProjectDetailFragment.create(entityId));
        } else if ("inbound_message".equals(entityType)) {
            // Escalations from the inbound engine point here (a commercial
            // question, an unmatched sender). Until Phase 6 this fell through
            // to the "later phase" toast, which is exactly the dead end
            // FINDINGS F27 described. The triage queue is the screen; the id
            // is not addressable on its own, so the queue is where it lands.
            openInbox();
        } else if ("outbound_message".equals(entityType) && entityId != null) {
            push(com.yuvipep.app.feature.inbox.DeliveryTraceFragment.create(entityId));
        } else if ("message".equals(entityType) && entityId != null) {
            push(com.yuvipep.app.feature.inbox.DeliveryTraceFragment.create(entityId));
        } else if ("action_item".equals(entityType) && entityId != null) {
            // No project context from a bare notification/action-card id —
            // the screen still works, just with the honestly narrower detail
            // set (11 §6e).
            push(com.yuvipep.app.feature.tasks.TaskDetailFragment.create(null, entityId));
        } else if ("followup".equals(entityType)) {
            // F58: the follow-up queue needs no id — it was only ever a missing
            // dispatch line, and the screen has existed since Phase 5.
            push(new com.yuvipep.app.feature.followups.FollowUpQueueFragment());
        } else if (("conflict".equals(entityType) || "action_plan".equals(entityType))
                && entityId != null) {
            // F58: these DO have screens — the project's Conflicts and Plan tabs,
            // both working since Act 11 — but a notification carries only
            // entity_type + entity_id, so there was nothing to navigate with and
            // it fell through to "this opens fully in a later phase". Resolve the
            // project, then land on the right tab.
            final String type = entityType;
            projectsRepository.resolveProjectForEntity(entityType, entityId, result -> {
                if (isFinishing() || isDestroyed()) return;
                if (result.isSuccess() && result.data != null
                        && result.data.projectId != null) {
                    push(com.yuvipep.app.feature.projects.ProjectDetailFragment.create(
                            result.data.projectId,
                            com.yuvipep.app.feature.projects.ProjectDetailFragment
                                    .tabForEntity(type)));
                } else {
                    // Honest failure rather than a silent no-op: say why.
                    android.widget.Toast.makeText(this,
                            result.error != null ? result.error.message
                                    : getString(R.string.notification_no_screen_yet),
                            android.widget.Toast.LENGTH_SHORT).show();
                }
            });
        } else if ("digest".equals(entityType)) {
            // F58: the fair exception. There is no digest screen and there is no
            // plan for one — the content is already in the notification body — so
            // "a later phase" was the wrong promise to make.
            android.widget.Toast.makeText(this,
                    R.string.notification_digest_is_the_content,
                    android.widget.Toast.LENGTH_SHORT).show();
        } else {
            android.widget.Toast.makeText(this,
                    R.string.notification_no_screen_yet,
                    android.widget.Toast.LENGTH_SHORT).show();
        }
    }

    private void returnToAuth(boolean expired) {
        Intent intent = new Intent(this, AuthActivity.class);
        intent.putExtra(AuthActivity.EXTRA_SESSION_EXPIRED, expired);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(intent);
        finish();
    }

    @NonNull
    @Override
    public String toString() {
        return "MainActivity";
    }
}
