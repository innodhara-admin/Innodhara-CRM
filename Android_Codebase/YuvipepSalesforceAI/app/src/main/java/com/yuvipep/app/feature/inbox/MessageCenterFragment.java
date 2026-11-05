package com.yuvipep.app.feature.inbox;

import android.content.res.ColorStateList;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.chip.Chip;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.MessageDto;
import com.yuvipep.app.databinding.FragmentMessageCenterBinding;
import com.yuvipep.app.databinding.ItemMessageBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The message centre (03 §9): every message the org has drafted or sent, with
 * the status trail it has travelled. Tapping one opens its delivery trace.
 *
 * `GET /messages` is org-wide, so the Mine/All chips are a visible client-side
 * filter rather than a silent one — an agent defaults to their own messages,
 * a lead or admin to everything, and either can switch.
 */
@AndroidEntryPoint
public class MessageCenterFragment extends Fragment {

    private static final int PAGE = 100;

    @Inject InboxRepository repository;
    @Inject TokenStore tokenStore;

    private FragmentMessageCenterBinding binding;
    private final List<MessageDto> all = new ArrayList<>();
    private final List<MessageDto> shown = new ArrayList<>();
    private final Adapter adapter = new Adapter();

    private String status = "all";
    private boolean mineOnly;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentMessageCenterBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        // An agent looks at their own outbox first; the people who oversee the
        // org look at all of it. Both chips stay visible either way.
        mineOnly = com.yuvipep.app.core.auth.RoleGate.SALES_AGENT
                .equals(tokenStore.getRole());

        binding.messageList.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.messageList.setAdapter(adapter);
        binding.swipeRefresh.setOnRefreshListener(() -> {
            load();
            binding.swipeRefresh.setRefreshing(false);
        });
        buildStatusChips();
        buildScopeChips();
        load();
    }

    private void buildStatusChips() {
        binding.statusChips.removeAllViews();
        for (String value : MessageStatuses.FILTERS) {
            Chip chip = new Chip(requireContext());
            chip.setText("all".equals(value)
                    ? getString(R.string.message_filter_all)
                    : MessageStatuses.label(value));
            chip.setCheckable(true);
            chip.setChecked(value.equals(status));
            chip.setOnClickListener(v -> {
                status = value;
                load();
            });
            binding.statusChips.addView(chip);
        }
    }

    private void buildScopeChips() {
        binding.scopeChips.removeAllViews();
        addScopeChip(getString(R.string.message_scope_mine), true);
        addScopeChip(getString(R.string.message_scope_everyone), false);
    }

    private void addScopeChip(String label, boolean mine) {
        Chip chip = new Chip(requireContext());
        chip.setText(label);
        chip.setCheckable(true);
        chip.setChecked(mineOnly == mine);
        chip.setOnClickListener(v -> {
            mineOnly = mine;
            applyScope();
        });
        binding.scopeChips.addView(chip);
    }

    private void load() {
        binding.stateView.showLoading();
        repository.messages(status, PAGE, 0, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                all.clear();
                all.addAll(result.data);
                applyScope();
            } else if (result.isError() && result.error != null) {
                // 403 here is a real answer, not a failure to hide: this role
                // cannot send messages, so it has no outbox to read.
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    private void applyScope() {
        if (binding == null) return;
        String me = tokenStore.getUserId();
        shown.clear();
        for (MessageDto m : all) {
            if (!mineOnly || (me != null && me.equals(m.senderUserId))) {
                shown.add(m);
            }
        }
        adapter.notifyDataSetChanged();
        if (shown.isEmpty()) {
            binding.stateView.showEmpty(
                    getString(R.string.message_center_empty_title),
                    getString(mineOnly
                            ? R.string.message_center_empty_mine
                            : R.string.message_center_empty_all),
                    R.drawable.ic_tab_inbox, null, null);
        } else {
            binding.stateView.hide();
        }
    }

    private class Adapter extends RecyclerView.Adapter<Adapter.Holder> {
        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemMessageBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(shown.get(position));
        }

        @Override
        public int getItemCount() {
            return shown.size();
        }

        class Holder extends RecyclerView.ViewHolder {
            private final ItemMessageBinding row;

            Holder(ItemMessageBinding row) {
                super(row.getRoot());
                this.row = row;
            }

            void bind(MessageDto message) {
                row.statusDot.setBackgroundTintList(ColorStateList.valueOf(
                        ContextCompat.getColor(requireContext(),
                                MessageStatuses.color(message.status))));
                row.statusText.setText(MessageStatuses.label(message.status));
                row.kindChip.setText(LeadStates.label(message.kind));
                row.subjectText.setText(
                        message.subject != null && !message.subject.isEmpty()
                                ? message.subject
                                : preview(message.body));
                row.toText.setText(getString(R.string.message_to_line,
                        message.to == null ? "" : message.to,
                        LeadStates.label(message.channel)));
                row.trailText.setText(MessageStatuses.trail(message.status));
                if (message.lastError != null && !message.lastError.isEmpty()) {
                    row.errorText.setText(message.lastError);
                    row.errorText.setVisibility(View.VISIBLE);
                } else {
                    row.errorText.setVisibility(View.GONE);
                }
                row.getRoot().setOnClickListener(v -> {
                    if (getActivity() instanceof MainActivity) {
                        ((MainActivity) getActivity())
                                .push(DeliveryTraceFragment.create(message.id));
                    }
                });
            }

            private String preview(@Nullable String body) {
                if (body == null || body.isEmpty()) return "";
                String flat = body.replace('\n', ' ').trim();
                return flat.length() > 120 ? flat.substring(0, 117) + "…" : flat;
            }
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
