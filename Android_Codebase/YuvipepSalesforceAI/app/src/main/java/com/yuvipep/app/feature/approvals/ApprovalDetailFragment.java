package com.yuvipep.app.feature.approvals;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.db.CachedApproval;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentApprovalDetailBinding;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * ApprovalDetail (03 §8): the backend's facts verbatim; message approvals
 * additionally preview the full draft. Approve / Reject-with-note at the
 * bottom; queued/failed offline states shown honestly.
 */
@AndroidEntryPoint
public class ApprovalDetailFragment extends Fragment {

    private static final String ARG_ID = "approval_id";

    public static ApprovalDetailFragment create(@NonNull String approvalId) {
        ApprovalDetailFragment fragment = new ApprovalDetailFragment();
        Bundle args = new Bundle();
        args.putString(ARG_ID, approvalId);
        fragment.setArguments(args);
        return fragment;
    }

    private FragmentApprovalDetailBinding binding;
    private ApprovalsViewModel viewModel;
    private String approvalId;
    /** F30: blanks in the previewed draft, filled once the message loads. */
    private final List<String> draftBlanks = new ArrayList<>();
    /** This screen's own decision went through; the screen is closing. */
    private boolean decided;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentApprovalDetailBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        viewModel = new ViewModelProvider(this).get(ApprovalsViewModel.class);
        approvalId = requireArguments().getString(ARG_ID, "");

        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());

        // The Room feed is the source: re-render whenever it changes (a
        // decide elsewhere or a queue drain updates this screen live).
        viewModel.approvals().observe(getViewLifecycleOwner(), rows -> load());
        load();

        viewModel.decideEvent().observe(getViewLifecycleOwner(), result -> {
            if (result == null) return;
            if (result.isSuccess() && result.data != null) {
                // Deciding removes the row from the cached feed, and the
                // observer above reloads from that cache — which used to
                // paint "Something went wrong · This approval is no longer
                // pending" over the screen just before it closed. Remember
                // that the decision was ours and leave the screen as it is.
                decided = true;
                Toast.makeText(requireContext(), result.data.queuedOffline
                                ? getString(R.string.approval_queued_offline)
                                : getString(R.string.approval_decided_toast,
                                result.data.response != null
                                        ? result.data.response.status : "applied"),
                        Toast.LENGTH_SHORT).show();
                requireActivity().getOnBackPressedDispatcher().onBackPressed();
            } else if (result.isError() && result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
            }
        });
    }

    private void load() {
        if (decided) return;  // our own decision emptied the row; we are leaving
        viewModel.approval(approvalId, result -> {
            if (binding == null || decided) return;
            if (result.isSuccess() && result.data != null) {
                render(result.data);
            } else if (result.isError() && result.error != null) {
                // Decided by someone else, or expired: that is news, not a
                // fault. Say so plainly and offer the way back.
                binding.stateView.showEmpty(
                        getString(R.string.approval_gone_title),
                        getString(R.string.approval_gone_body), 0,
                        getString(R.string.approval_gone_action),
                        () -> requireActivity().getOnBackPressedDispatcher().onBackPressed());
                binding.actionRow.setVisibility(View.GONE);
            }
        });
    }

    private void render(@NonNull CachedApproval approval) {
        binding.stateView.hide();
        binding.entityChip.setText(approval.entityType != null
                ? approval.entityType.replace('_', ' ')
                : getString(R.string.approval_entity_fallback));
        binding.stageBadge.setText("recommend".equals(approval.stage)
                ? getString(R.string.approval_stage_recommend)
                : getString(R.string.approval_stage_decide));
        binding.expiryText.setText(Times.untilLabel(approval.expiresAt));
        binding.reasonText.setText(approval.reason);
        boolean hasRecommendation = approval.recommendation != null
                && !approval.recommendation.isEmpty();
        binding.recommendationTitle.setVisibility(hasRecommendation ? View.VISIBLE : View.GONE);
        binding.recommendationText.setVisibility(hasRecommendation ? View.VISIBLE : View.GONE);
        if (hasRecommendation) {
            binding.recommendationText.setText(approval.recommendation);
        }

        String local = approval.localState != null ? approval.localState : "";
        if ("queued".equals(local)) {
            binding.localStateText.setText(R.string.approval_queued_offline);
            binding.localStateText.setVisibility(View.VISIBLE);
            binding.actionRow.setVisibility(View.GONE);
        } else if (local.startsWith("failed:")) {
            binding.localStateText.setText(getString(R.string.approval_queue_failed,
                    local.substring("failed:".length())));
            binding.localStateText.setVisibility(View.VISIBLE);
            binding.actionRow.setVisibility(View.GONE);
        } else {
            binding.localStateText.setVisibility(View.GONE);
            binding.actionRow.setVisibility(View.VISIBLE);
            binding.approveButton.setOnClickListener(v -> {
                // F30: a draft still carrying "[Name]" needs one deliberate
                // confirmation. This screen already shows the whole body, so
                // the approver has genuinely seen them — the dialog names them
                // rather than leaving them to be spotted in a wall of text.
                if (!draftBlanks.isEmpty()) {
                    new MaterialAlertDialogBuilder(requireContext())
                            .setTitle(R.string.approval_blanks_title)
                            .setMessage(getString(R.string.approval_blanks_body,
                                    android.text.TextUtils.join(", ", draftBlanks)))
                            .setPositiveButton(R.string.approval_blanks_send_anyway,
                                    (d, w) -> viewModel.decide(approval.id, true, null, true))
                            .setNegativeButton(R.string.approval_blanks_cancel, null)
                            .show();
                    return;
                }
                viewModel.decide(approval.id, true, null);
            });
            binding.rejectButton.setOnClickListener(v ->
                    DecideDialogs.rejectWithNote(requireContext(), note ->
                            viewModel.decide(approval.id, false, note)));
        }

        if ("outbound_message".equals(approval.entityType) && approval.entityId != null) {
            viewModel.messagePreview(approval.entityId, result -> {
                if (binding == null) return;
                if (result.isSuccess() && result.data != null) {
                    binding.messageCard.setVisibility(View.VISIBLE);
                    StringBuilder meta = new StringBuilder();
                    meta.append("To: ").append(orDash(result.data.to));
                    if (result.data.cc != null && !result.data.cc.isEmpty()) {
                        meta.append("\nCC: ").append(String.join(", ", result.data.cc));
                    }
                    // The approver must see who is blind-copied before saying yes.
                    if (result.data.bcc != null && !result.data.bcc.isEmpty()) {
                        meta.append("\nBCC: ").append(String.join(", ", result.data.bcc));
                    }
                    if (result.data.subject != null && !result.data.subject.isEmpty()) {
                        meta.append("\nSubject: ").append(result.data.subject);
                    }
                    meta.append(String.format(Locale.US, "\nChannel: %s",
                            orDash(result.data.channel)));
                    binding.messageMeta.setText(meta.toString());
                    binding.messageBody.setText(result.data.body);
                    draftBlanks.clear();
                    if (result.data.blanks != null) draftBlanks.addAll(result.data.blanks);
                } else if (result.isError() && result.error != null) {
                    binding.messageCard.setVisibility(View.VISIBLE);
                    binding.messageMeta.setText(result.error.message);
                    binding.messageBody.setText("");
                }
            });
        }
    }

    private static String orDash(@Nullable String value) {
        return value != null && !value.isEmpty() ? value : "—";
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
