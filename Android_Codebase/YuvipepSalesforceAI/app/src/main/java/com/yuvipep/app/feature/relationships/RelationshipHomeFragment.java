package com.yuvipep.app.feature.relationships;

import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.RelationshipClientDto;
import com.yuvipep.app.databinding.FragmentRelationshipHomeBinding;
import com.yuvipep.app.feature.auth.AuthActivity;
import com.yuvipep.app.feature.auth.AuthRepository;
import com.yuvipep.app.feature.leads.LeadDetailFragment;
import com.yuvipep.app.feature.leads.RowAdapter;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The relationship manager's Home: the clients I look after.
 *
 * <p>The screen answers one question — who needs me today — so it renders the
 * server's order untouched. {@code GET /relationships/mine} returns them
 * worst-neglected first, and a client nobody has ever spoken to comes first of
 * all. Re-sorting here, however reasonably, would undo the only thing this
 * screen is for.
 *
 * <p>Tapping a client opens the ordinary lead detail screen. That is
 * deliberate reuse rather than a shortcut: contacts, the notebook, the meeting
 * recorder and the sales history are all already there and all already work,
 * and the relationship summary is added to its Overview tab when an engagement
 * exists. A second, parallel client screen would drift from that one within a
 * release.
 */
@AndroidEntryPoint
public class RelationshipHomeFragment extends Fragment {

    @Inject RelationshipRepository repository;
    @Inject AuthRepository authRepository;

    private FragmentRelationshipHomeBinding binding;
    private RowAdapter adapter;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentRelationshipHomeBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        adapter = new RowAdapter();
        binding.list.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.list.setAdapter(adapter);
        // A relationship manager has no Home tab, and Home is where every
        // other role finds logout. Without this they cannot sign out.
        binding.logoutButton.setOnClickListener(v -> confirmLogout());
        load();
    }

    @Override
    public void onResume() {
        super.onResume();
        // Coming back from a client page, a recorded meeting may have changed
        // how long that client has been quiet.
        if (adapter != null) load();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }

    private void confirmLogout() {
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.logout_confirm_title)
                .setMessage(R.string.logout_confirm_body)
                .setPositiveButton(R.string.action_logout, (d, w) ->
                        authRepository.logout(() -> {
                            Intent intent = new Intent(requireContext(),
                                    AuthActivity.class);
                            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                                    | Intent.FLAG_ACTIVITY_CLEAR_TASK);
                            startActivity(intent);
                        }))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void load() {
        binding.stateView.showLoading();
        repository.myClients(result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null) {
                    binding.stateView.showError(result.error.message, this::load);
                }
                return;
            }
            render(result.data);
        });
    }

    private void render(@NonNull List<RelationshipClientDto> clients) {
        if (clients.isEmpty()) {
            adapter.submit(new ArrayList<>());
            binding.stateView.showEmpty(
                    getString(R.string.relationship_home_empty_title),
                    getString(R.string.relationship_home_empty_body),
                    R.drawable.ic_tab_people, null, null);
            return;
        }
        binding.stateView.hide();

        List<RowAdapter.Row> rows = new ArrayList<>();
        for (RelationshipClientDto c : clients) {
            rows.add(new RowAdapter.Row(
                    c.leadName,
                    quietLine(c),
                    nextTouchLine(c),
                    // The badge is the nudge. Only clients who need one get it,
                    // so a screen full of badges means a real backlog. A client
                    // hinting they want to buy again outranks a quiet one:
                    // that is the most time-sensitive thing on this screen.
                    badgeFor(c),
                    () -> open(c.leadId)));
        }
        adapter.submit(rows);
    }

    @Nullable
    private String badgeFor(@NonNull RelationshipClientDto c) {
        if (c.opportunityOpen) return getString(R.string.relationship_badge_opportunity);
        return c.isQuiet ? getString(R.string.relationship_badge_quiet) : null;
    }

    /** "Not spoken to yet" reads as a state; "null days" reads as a bug. */
    private String quietLine(@NonNull RelationshipClientDto c) {
        if (c.daysQuiet == null) {
            return getString(R.string.relationship_never_spoken);
        }
        if (c.daysQuiet <= 0) {
            return getString(R.string.relationship_spoken_today);
        }
        return getResources().getQuantityString(
                R.plurals.relationship_days_quiet, c.daysQuiet, c.daysQuiet);
    }

    @Nullable
    private String nextTouchLine(@NonNull RelationshipClientDto c) {
        // An open opportunity replaces the next-touch line entirely: it is a
        // question waiting on this person, not a date in the diary.
        if (c.opportunityOpen && c.opportunityReason != null) {
            return c.opportunityReason;
        }
        if (c.nextTouchDate == null) return c.city;
        String when = c.nextTouchOverdue
                ? getString(R.string.relationship_touch_overdue, c.nextTouchDate)
                : getString(R.string.relationship_touch_planned, c.nextTouchDate);
        return c.nextTouchNote == null || c.nextTouchNote.isEmpty()
                ? when
                : when + " · " + c.nextTouchNote;
    }

    private void open(@NonNull String leadId) {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(LeadDetailFragment.create(leadId));
        }
    }
}
