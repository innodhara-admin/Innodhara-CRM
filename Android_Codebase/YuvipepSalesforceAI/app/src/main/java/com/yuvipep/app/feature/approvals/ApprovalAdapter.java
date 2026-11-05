package com.yuvipep.app.feature.approvals;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.ListAdapter;
import androidx.recyclerview.widget.RecyclerView;

import com.yuvipep.app.R;
import com.yuvipep.app.core.db.CachedApproval;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.ItemApprovalBinding;

import java.util.Objects;

/**
 * One approval card (03 §8): backend-provided facts verbatim, stage badge,
 * expiry countdown, inline Approve / Reject. Offline state rides on top —
 * queued cards lose their buttons, failed ones show the backend's refusal.
 */
public class ApprovalAdapter extends ListAdapter<CachedApproval, ApprovalAdapter.Holder> {

    public interface Listener {
        void onApprove(@NonNull CachedApproval approval);

        void onReject(@NonNull CachedApproval approval);

        void onOpen(@NonNull CachedApproval approval);

        void onDismissFailure(@NonNull CachedApproval approval);
    }

    private final Listener listener;

    public ApprovalAdapter(@NonNull Listener listener) {
        super(DIFF);
        this.listener = listener;
    }

    private static final DiffUtil.ItemCallback<CachedApproval> DIFF =
            new DiffUtil.ItemCallback<CachedApproval>() {
                @Override
                public boolean areItemsTheSame(@NonNull CachedApproval a,
                                               @NonNull CachedApproval b) {
                    return a.id.equals(b.id);
                }

                @Override
                public boolean areContentsTheSame(@NonNull CachedApproval a,
                                                  @NonNull CachedApproval b) {
                    return Objects.equals(a.reason, b.reason)
                            && Objects.equals(a.stage, b.stage)
                            && Objects.equals(a.localState, b.localState)
                            && Objects.equals(a.recommendation, b.recommendation);
                }
            };

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        return new Holder(ItemApprovalBinding.inflate(
                LayoutInflater.from(parent.getContext()), parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull Holder holder, int position) {
        holder.bind(getItem(position));
    }

    class Holder extends RecyclerView.ViewHolder {
        private final ItemApprovalBinding binding;

        Holder(ItemApprovalBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }

        void bind(CachedApproval approval) {
            android.content.Context context = binding.getRoot().getContext();
            binding.entityChip.setText(approval.entityType != null
                    ? approval.entityType.replace('_', ' ')
                    : context.getString(R.string.approval_entity_fallback));
            binding.stageBadge.setText("recommend".equals(approval.stage)
                    ? context.getString(R.string.approval_stage_recommend)
                    : context.getString(R.string.approval_stage_decide));
            binding.expiryText.setText(Times.untilLabel(approval.expiresAt));
            binding.reasonText.setText(approval.reason);
            if (approval.recommendation != null && !approval.recommendation.isEmpty()) {
                binding.recommendationText.setText(approval.recommendation);
                binding.recommendationText.setVisibility(View.VISIBLE);
            } else {
                binding.recommendationText.setVisibility(View.GONE);
            }

            String local = approval.localState != null ? approval.localState : "";
            if ("queued".equals(local)) {
                binding.localStateText.setText(R.string.approval_queued_offline);
                binding.localStateText.setVisibility(View.VISIBLE);
                binding.actionRow.setVisibility(View.GONE);
                binding.getRoot().setOnClickListener(null);
            } else if (local.startsWith("failed:")) {
                binding.localStateText.setText(context.getString(
                        R.string.approval_queue_failed, local.substring("failed:".length())));
                binding.localStateText.setVisibility(View.VISIBLE);
                binding.actionRow.setVisibility(View.VISIBLE);
                binding.approveButton.setVisibility(View.GONE);
                binding.rejectButton.setText(R.string.action_dismiss);
                binding.rejectButton.setOnClickListener(v ->
                        listener.onDismissFailure(approval));
                binding.getRoot().setOnClickListener(v -> listener.onOpen(approval));
                return;
            } else {
                binding.localStateText.setVisibility(View.GONE);
                binding.actionRow.setVisibility(View.VISIBLE);
                binding.getRoot().setOnClickListener(v -> listener.onOpen(approval));
            }
            binding.approveButton.setVisibility(View.VISIBLE);
            binding.rejectButton.setText(R.string.action_reject);
            binding.approveButton.setOnClickListener(v -> listener.onApprove(approval));
            binding.rejectButton.setOnClickListener(v -> listener.onReject(approval));
        }
    }
}
