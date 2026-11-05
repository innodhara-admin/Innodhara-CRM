package com.yuvipep.app.feature.proposals;

import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.snackbar.Snackbar;
import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.auth.RoleGate;
import com.yuvipep.app.core.net.TokenStore;
import com.yuvipep.app.core.net.dto.ProposalDetailDto;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentProposalDetailBinding;
import com.yuvipep.app.feature.assistant.ContextBus;
import com.yuvipep.app.feature.assistant.WhySheet;
import com.yuvipep.app.feature.leads.LeadStates;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Proposal detail (03 §6): narrative + the machine-owned pricing block
 * (words are editable by instruction; numbers only via the pricing table),
 * the revision trail, PDF preview, manual re-upload (G3 — total re-verified
 * server-side), submit-review and the one-tap approve-and-send.
 */
@AndroidEntryPoint
public class ProposalDetailFragment extends Fragment {

    private static final String ARG_ID = "proposal_id";

    public static ProposalDetailFragment create(@NonNull String proposalId) {
        ProposalDetailFragment fragment = new ProposalDetailFragment();
        Bundle args = new Bundle();
        args.putString(ARG_ID, proposalId);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject ProposalsRepository repository;
    @Inject TokenStore tokenStore;
    @Inject ContextBus contextBus;

    private FragmentProposalDetailBinding binding;
    private String proposalId;
    private ProposalDetailDto proposal;
    private ActivityResultLauncher<String[]> filePicker;

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        filePicker = registerForActivityResult(
                new ActivityResultContracts.OpenDocument(), this::onFilePicked);
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentProposalDetailBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        proposalId = requireArguments().getString(ARG_ID, "");
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.whyButton.setOnClickListener(v ->
                WhySheet.open(getParentFragmentManager(), "proposal", proposalId));
        binding.pdfButton.setOnClickListener(v -> openPdf());
        binding.editButton.setOnClickListener(v -> editDialog());
        binding.uploadButton.setOnClickListener(v -> filePicker.launch(new String[]{
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}));
        binding.submitReviewButton.setOnClickListener(v -> submitReview());
        binding.approveSendButton.setOnClickListener(v ->
                ApproveSendSheet.open(getParentFragmentManager(), proposalId));
        getParentFragmentManager().setFragmentResultListener(
                ApproveSendSheet.RESULT_KEY, this, (key, result) -> {
                    Snackbar.make(binding.getRoot(),
                            getString(R.string.proposal_sent_to,
                                    result.getString(ApproveSendSheet.RESULT_TO, "")),
                            Snackbar.LENGTH_LONG).show();
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
        if (proposal == null) binding.stateView.showLoading();
        repository.detail(proposalId, result -> {
            if (binding == null) return;
            binding.stateView.hide();
            if (result.isSuccess() && result.data != null) {
                proposal = result.data;
                contextBus.set("proposal", proposalId, proposal.title);
                render();
            } else if (result.isError() && result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    private void render() {
        binding.proposalTitle.setText(proposal.title == null
                ? getString(R.string.proposal_untitled) : proposal.title);
        binding.statusChip.setText(LeadStates.label(proposal.status));

        StringBuilder meta = new StringBuilder();
        if (proposal.totalAmount != null) {
            meta.append(money(proposal.totalAmount, proposal.currency));
        }
        if (proposal.templateVersion != null) {
            if (meta.length() > 0) meta.append(" · ");
            meta.append(getString(R.string.proposal_versions,
                    proposal.templateVersion,
                    proposal.pricingVersion == null ? 0 : proposal.pricingVersion));
        }
        if (proposal.sentAt != null) {
            if (meta.length() > 0) meta.append(" · ");
            meta.append(getString(R.string.proposal_sent_meta,
                    Times.ago(Times.parseUtc(proposal.sentAt))));
        }
        binding.proposalMeta.setText(meta);

        renderPricing();
        renderNarrative();
        renderFilled();
        renderRevisions();
        renderButtons();
    }

    /** The locked commercial table — rendered from line_items, labelled as
     *  machine-owned (the whole point of the G3 tamper check). */
    private void renderPricing() {
        binding.pricingRows.removeAllViews();
        if (proposal.lineItems == null || proposal.lineItems.isEmpty()) {
            binding.pricingCard.setVisibility(View.GONE);
            return;
        }
        binding.pricingCard.setVisibility(View.VISIBLE);
        for (Map<String, Object> item : proposal.lineItems) {
            View row = LayoutInflater.from(requireContext())
                    .inflate(R.layout.item_price_line, binding.pricingRows, false);
            Object label = item.get("label");
            Object quantity = item.get("quantity");
            Object unit = item.get("unit");
            Object lineTotal = item.get("line_total");
            ((TextView) row.findViewById(R.id.lineLabel)).setText(
                    label == null ? "—" : String.valueOf(label));
            ((TextView) row.findViewById(R.id.lineQty)).setText(
                    String.format(Locale.getDefault(), "%s %s",
                            quantity instanceof Number
                                    ? String.valueOf(((Number) quantity).longValue())
                                    : "—",
                            unit == null ? "" : String.valueOf(unit)).trim());
            ((TextView) row.findViewById(R.id.lineTotal)).setText(
                    lineTotal instanceof Number
                            ? money(((Number) lineTotal).doubleValue(), proposal.currency)
                            : "—");
            binding.pricingRows.addView(row);
        }
        binding.pricingTotal.setText(proposal.totalAmount == null ? "—"
                : money(proposal.totalAmount, proposal.currency));
    }

    private void renderNarrative() {
        String content = proposal.contentMd == null ? "" : proposal.contentMd;
        // The pricing block renders as a table above; strip the raw markdown
        // between the machine markers so the narrative reads clean.
        content = content.replaceAll(
                "(?s)<!--PRICING_START-->.*?<!--PRICING_END-->", "\n")
                .replaceAll("\\n{3,}", "\n\n").trim();
        binding.narrativeText.setText(content.isEmpty()
                ? getString(R.string.proposal_no_narrative) : content);
    }

    /**
     * What the model wrote, and what it could not.
     *
     * <p>Only for a document-template proposal: a markdown one has no
     * placeholders and the card stays hidden, so that screen is unchanged.
     *
     * <p><b>Unfilled entries come first.</b> They are the ones that block a
     * send: the document has a gap where a section should be, and nothing else
     * on this screen says so — the narrative simply reads as if that paragraph
     * was never meant to exist.
     */
    private void renderFilled() {
        binding.filledRows.removeAllViews();
        boolean isDocx = isDocumentProposal();
        if (!isDocx || proposal.filled == null || proposal.filled.isEmpty()) {
            binding.filledCard.setVisibility(View.GONE);
            return;
        }
        binding.filledCard.setVisibility(View.VISIBLE);

        List<ProposalDetailDto.Filled> ordered = new ArrayList<>();
        for (ProposalDetailDto.Filled f : proposal.filled) {
            if (f != null && "unfilled".equals(f.source)) ordered.add(f);
        }
        for (ProposalDetailDto.Filled f : proposal.filled) {
            if (f != null && !"unfilled".equals(f.source)) ordered.add(f);
        }

        for (ProposalDetailDto.Filled entry : ordered) {
            View row = LayoutInflater.from(requireContext())
                    .inflate(R.layout.item_filled_line, binding.filledRows, false);
            boolean unfilled = "unfilled".equals(entry.source);
            ((TextView) row.findViewById(R.id.filledSource))
                    .setText(sourceLabel(entry.source));
            // The brief is what a human asked for; the key is the fallback,
            // because a token binding has no brief at all.
            String heading = headingFor(entry);
            ((TextView) row.findViewById(R.id.filledBrief)).setText(heading);
            TextView text = row.findViewById(R.id.filledText);
            if (unfilled) {
                text.setText(R.string.proposal_filled_empty_hint);
                text.setTextColor(ContextCompat.getColor(requireContext(),
                        R.color.md_light_error));
            } else {
                text.setText(entry.text == null ? "" : entry.text);
            }
            binding.filledRows.addView(row);
        }
    }

    /**
     * The three decisions this card makes live in {@link ProposalFilledLines}
     * so they can be tested: this project's JVM suite is pure logic and a
     * fragment would need Robolectric, which is why two of them were wrong for
     * the whole of the simple flow without anything noticing.
     */
    private boolean isDocumentProposal() {
        return ProposalFilledLines.isDocumentProposal(proposal.templateKind);
    }

    @NonNull
    private String headingFor(@NonNull ProposalDetailDto.Filled entry) {
        return ProposalFilledLines.heading(proposal.templateKind, entry);
    }

    @NonNull
    private String sourceLabel(@Nullable String source) {
        return getString(ProposalFilledLines.sourceLabel(source));
    }

    private void renderRevisions() {
        binding.revisionRows.removeAllViews();
        if (proposal.revisions == null || proposal.revisions.isEmpty()) {
            binding.revisionsTitle.setVisibility(View.GONE);
            return;
        }
        binding.revisionsTitle.setVisibility(View.VISIBLE);
        for (ProposalDetailDto.Revision revision : proposal.revisions) {
            TextView row = new TextView(requireContext());
            row.setTextAppearance(com.google.android.material.R.style
                    .TextAppearance_Material3_BodyMedium);
            row.setTextColor(ContextCompat.getColor(requireContext(),
                    R.color.md_light_onSurfaceVariant));
            row.setPadding(0, 8, 0, 8);
            String when = revision.editedAt == null ? ""
                    : " · " + Times.ago(Times.parseUtc(revision.editedAt));
            row.setText(getString(R.string.proposal_revision_row,
                    revision.revisionNo,
                    revision.instruction == null ? "" : revision.instruction) + when);
            binding.revisionRows.addView(row);
        }
    }

    private void renderButtons() {
        boolean canSend = RoleGate.has(tokenStore.getRole(), RoleGate.SEND_PROPOSAL);
        boolean sent = "sent".equals(proposal.status)
                || "accepted".equals(proposal.status)
                || "declined".equals(proposal.status);
        binding.editButton.setVisibility(canSend && !sent ? View.VISIBLE : View.GONE);
        binding.uploadButton.setVisibility(canSend && !sent ? View.VISIBLE : View.GONE);
        binding.submitReviewButton.setVisibility(canSend && !sent
                ? View.VISIBLE : View.GONE);
        binding.approveSendButton.setVisibility(canSend && !sent
                ? View.VISIBLE : View.GONE);
    }

    // ── Actions ──────────────────────────────────────────────────────

    private void openPdf() {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(PdfViewerFragment.create(
                    proposalId, versionTag(),
                    proposal == null || proposal.title == null
                            ? getString(R.string.proposal_untitled) : proposal.title));
        }
    }

    @NonNull
    private String versionTag() {
        int revisionCount = proposal == null || proposal.revisions == null
                ? 0 : proposal.revisions.size();
        return String.valueOf(revisionCount);
    }

    private void editDialog() {
        final android.widget.EditText input = new android.widget.EditText(requireContext());
        input.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        input.setMinLines(2);
        input.setHint(R.string.proposal_edit_hint);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.proposal_edit_title)
                .setMessage(R.string.proposal_edit_note)
                .setView(input)
                .setPositiveButton(R.string.proposal_edit_apply, (d, w) -> {
                    String instruction = input.getText().toString().trim();
                    if (instruction.length() < 3) {
                        Toast.makeText(requireContext(),
                                R.string.proposal_edit_too_short,
                                Toast.LENGTH_SHORT).show();
                        return;
                    }
                    applyEdit(instruction);
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void applyEdit(@NonNull String instruction) {
        binding.stateView.showLoading();
        setButtonsEnabled(false);
        repository.edit(proposalId, instruction, result -> {
            if (binding == null) return;
            binding.stateView.hide();
            setButtonsEnabled(true);
            if (result.isSuccess() && result.data != null) {
                proposal = result.data;
                render();
                String detail = result.data.editResult == null ? ""
                        : com.yuvipep.app.feature.assistant.Pretty
                                .value(result.data.editResult);
                Snackbar.make(binding.getRoot(),
                        detail.isEmpty() ? getString(R.string.proposal_edited)
                                : detail,
                        Snackbar.LENGTH_LONG).show();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message,
                        Snackbar.LENGTH_LONG).show();
            }
        });
    }

    private void submitReview() {
        setButtonsEnabled(false);
        repository.submitReview(proposalId, result -> {
            if (binding == null) return;
            setButtonsEnabled(true);
            if (result.isSuccess() && result.data != null) {
                String note = result.data.note == null ? "" : " — " + result.data.note;
                Snackbar.make(binding.getRoot(),
                        getString(R.string.proposal_review_result,
                                LeadStates.label(result.data.status)) + note,
                        Snackbar.LENGTH_LONG).show();
                load();
            } else if (result.error != null) {
                Snackbar.make(binding.getRoot(), result.error.message,
                        Snackbar.LENGTH_LONG).show();
            }
        });
    }

    private void onFilePicked(@Nullable Uri uri) {
        if (uri == null || binding == null) return;
        String name = displayName(uri);
        try {
            File copy = new File(requireContext().getCacheDir(), "upload_" + name);
            try (InputStream in = requireContext().getContentResolver()
                    .openInputStream(uri);
                 OutputStream out = new FileOutputStream(copy)) {
                if (in == null) throw new IOException("Cannot open the picked file");
                byte[] buffer = new byte[16 * 1024];
                int read;
                while ((read = in.read(buffer)) != -1) out.write(buffer, 0, read);
            }
            binding.stateView.showLoading();
            setButtonsEnabled(false);
            repository.uploadRevision(proposalId, copy, name, result -> {
                if (binding == null) return;
                binding.stateView.hide();
                setButtonsEnabled(true);
                //noinspection ResultOfMethodCallIgnored
                copy.delete();
                if (result.isSuccess() && result.data != null) {
                    // The backend's own honesty: verified / verify-by-eye note.
                    new MaterialAlertDialogBuilder(requireContext())
                            .setTitle(getString(R.string.proposal_upload_done,
                                    result.data.revisionNo))
                            .setMessage(result.data.note == null ? ""
                                    : result.data.note)
                            .setPositiveButton(android.R.string.ok, null)
                            .show();
                    load();
                } else if (result.error != null) {
                    // Tampered totals land here — the message names the rule.
                    new MaterialAlertDialogBuilder(requireContext())
                            .setTitle(R.string.proposal_upload_refused)
                            .setMessage(result.error.message)
                            .setPositiveButton(android.R.string.ok, null)
                            .show();
                }
            });
        } catch (IOException | SecurityException e) {
            Toast.makeText(requireContext(),
                    getString(R.string.proposal_upload_read_failed,
                            e.getMessage() == null ? "" : e.getMessage()),
                    Toast.LENGTH_LONG).show();
        }
    }

    @NonNull
    private String displayName(@NonNull Uri uri) {
        try (Cursor cursor = requireContext().getContentResolver().query(
                uri, null, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (index >= 0) {
                    String name = cursor.getString(index);
                    if (name != null && !name.isEmpty()) return name;
                }
            }
        } catch (Exception ignored) {
            // fall through to a safe default below
        }
        return "upload.pdf";
    }

    private void setButtonsEnabled(boolean enabled) {
        binding.editButton.setEnabled(enabled);
        binding.uploadButton.setEnabled(enabled);
        binding.submitReviewButton.setEnabled(enabled);
        binding.approveSendButton.setEnabled(enabled);
        binding.pdfButton.setEnabled(enabled);
    }

    @NonNull
    private String money(double amount, @Nullable String currency) {
        // One money renderer for the whole app (F31) — this screen already did
        // the right thing with the currency, it just did it privately.
        return com.yuvipep.app.core.util.Money.format(amount, currency);
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
