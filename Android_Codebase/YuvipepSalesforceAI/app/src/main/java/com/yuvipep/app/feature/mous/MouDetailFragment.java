package com.yuvipep.app.feature.mous;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.yuvipep.app.MainActivity;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.MouDto;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentMouDetailBinding;
import com.yuvipep.app.feature.leads.LeadStates;
import com.yuvipep.app.feature.proposals.PdfViewerFragment;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The contract screen: what the MOU says, what went into it, and the document
 * itself.
 *
 * <p><b>Why it exists.</b> The client screen has listed a contract since the
 * MOU pipeline shipped, and tapping it did nothing — so a contract the
 * assistant had built could not be read anywhere in the app. The owner found
 * that on a phone, which is where this pipeline's defects have been found.
 *
 * <p><b>What it deliberately does NOT offer.</b> No pricing block, no
 * narrative edit, no re-upload, no approve-and-send. An MOU has no
 * commercials and no send path, and a screen that offered those would be
 * offering actions the backend refuses. Every decision that can be made
 * without a view lives in {@link MouLines}, which is where it can be tested:
 * there is no Robolectric here, so anything left in this class is untested by
 * construction.
 */
@AndroidEntryPoint
public class MouDetailFragment extends Fragment {

    private static final String ARG_ID = "mou_id";

    public static MouDetailFragment create(@NonNull String mouId) {
        MouDetailFragment fragment = new MouDetailFragment();
        Bundle args = new Bundle();
        args.putString(ARG_ID, mouId);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject MousRepository repository;

    private FragmentMouDetailBinding binding;
    private String mouId;
    private MouDto mou;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentMouDetailBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view,
                              @Nullable Bundle savedInstanceState) {
        mouId = requireArguments().getString(ARG_ID, "");
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.pdfButton.setOnClickListener(v -> openPdf());
    }

    @Override
    public void onResume() {
        super.onResume();
        load();
    }

    private void load() {
        binding.stateView.showLoading();
        repository.detail(mouId, result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                mou = result.data;
                binding.stateView.hide();
                render();
            } else if (result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    private void render() {
        binding.mouTitle.setText(MouLines.rowTitle(
                mou.title, getString(R.string.lead_mou)));
        binding.statusChip.setText(LeadStates.label(mou.status));

        StringBuilder meta = new StringBuilder();
        if (mou.templateVersion != null) {
            meta.append(getString(R.string.mou_template_version,
                    mou.templateVersion));
        }
        // The send path is not built yet, so this is normally absent — but the
        // backend already refuses a correction once it is set, so when it does
        // arrive the screen must say so rather than look like a draft.
        if (MouLines.isWithTheClient(mou)) {
            if (meta.length() > 0) meta.append(" · ");
            meta.append(mou.sentAt == null
                    ? getString(R.string.lead_mou_sent_meta)
                    : getString(R.string.mou_sent_meta,
                            Times.ago(Times.parseUtc(mou.sentAt))));
        }
        binding.mouMeta.setText(meta);

        renderFilled();
        renderRevisions();
        binding.documentText.setText(mou.contentMd == null ? "" : mou.contentMd);
        binding.pdfButton.setEnabled(MouLines.canBeRead(mou));
    }

    /**
     * Where each value in the contract came from.
     *
     * <p>The labels are {@link MouLines#sourceLabel}'s, and the fallback there
     * is the modest one on purpose: telling a salesperson that a figure they
     * typed themselves came out of the database is a claim nobody can check,
     * and it is a defect this project has already shipped once.
     */
    private void renderFilled() {
        binding.filledRows.removeAllViews();
        if (!MouLines.hasProvenance(mou)) {
            binding.filledCard.setVisibility(View.GONE);
            return;
        }
        binding.filledCard.setVisibility(View.VISIBLE);
        for (MouDto.Filled entry : mou.filled) {
            if (entry == null) continue;
            View row = LayoutInflater.from(requireContext())
                    .inflate(R.layout.item_filled_line, binding.filledRows, false);
            ((TextView) row.findViewById(R.id.filledSource))
                    .setText(MouLines.sourceLabel(entry.source));
            ((TextView) row.findViewById(R.id.filledBrief))
                    .setText(MouLines.heading(entry));
            ((TextView) row.findViewById(R.id.filledText))
                    .setText(entry.text == null ? "" : entry.text);
            binding.filledRows.addView(row);
        }
    }

    /** The corrections, newest first — revision 1 is the contract as built. */
    private void renderRevisions() {
        binding.revisionRows.removeAllViews();
        if (mou.revisions == null || mou.revisions.isEmpty()) {
            binding.revisionsTitle.setVisibility(View.GONE);
            return;
        }
        binding.revisionsTitle.setVisibility(View.VISIBLE);
        for (MouDto.Revision revision : mou.revisions) {
            if (revision == null) continue;
            TextView row = new TextView(requireContext());
            row.setTextAppearance(com.google.android.material.R.style
                    .TextAppearance_Material3_BodyMedium);
            row.setTextColor(ContextCompat.getColor(requireContext(),
                    R.color.md_light_onSurfaceVariant));
            row.setPadding(0, 8, 0, 8);
            String when = revision.editedAt == null ? ""
                    : " · " + Times.ago(Times.parseUtc(revision.editedAt));
            row.setText(getString(R.string.mou_revision_row,
                    revision.revisionNo == null ? 0 : revision.revisionNo,
                    revision.instruction == null ? "" : revision.instruction)
                    + when);
            binding.revisionRows.addView(row);
        }
    }

    private void openPdf() {
        if (getActivity() instanceof MainActivity) {
            ((MainActivity) getActivity()).push(PdfViewerFragment.forMou(
                    mouId, MouLines.versionTag(mou),
                    MouLines.rowTitle(mou == null ? null : mou.title,
                            getString(R.string.lead_mou))));
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
