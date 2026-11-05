package com.yuvipep.app.feature.inbox;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import com.google.android.material.chip.Chip;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.ContactDto;
import com.yuvipep.app.core.net.dto.InboundIngestRequest;
import com.yuvipep.app.core.net.dto.LeadDetailResponse;
import com.yuvipep.app.core.net.dto.LeadDto;
import com.yuvipep.app.databinding.SheetLogClientReplyBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * "Log client reply" (03 §9): a call or a WhatsApp that arrived outside the
 * system, typed or dictated in by whoever took it.
 *
 * It goes through POST /inbound/ingest — the same door an email arrives by —
 * so the engines classify, match and route it identically. What they made of
 * it is shown back verbatim instead of a "Saved" toast, because the person who
 * logged it is the only one who can tell if the system misread them.
 */
@AndroidEntryPoint
public class LogClientReplySheet extends BottomSheetDialogFragment {

    /** Refresh your list when this fires — a logged reply may land in triage. */
    public static final String RESULT_KEY = "client_reply_logged";

    private static final String[] CHANNELS = {"email", "whatsapp", "call"};

    public static void open(@NonNull FragmentManager fm) {
        new LogClientReplySheet().show(fm, "log_client_reply");
    }

    @Inject InboxRepository repository;

    private SheetLogClientReplyBinding binding;
    @Nullable private ContactDto contact;
    @Nullable private String leadName;
    private String channel = CHANNELS[0];

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetLogClientReplyBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        buildChannelChips();
        binding.contactButton.setOnClickListener(v -> pickLead());
        binding.submitButton.setOnClickListener(v -> submit());
    }

    private void buildChannelChips() {
        binding.channelChips.removeAllViews();
        for (String value : CHANNELS) {
            Chip chip = new Chip(requireContext());
            chip.setText(LeadStates.label(value));
            chip.setCheckable(true);
            chip.setChecked(value.equals(channel));
            chip.setOnClickListener(v -> channel = value);
            binding.channelChips.addView(chip);
        }
    }

    private void pickLead() {
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
                    picked -> pickContact(picked.id, picked.label));
        });
    }

    private void pickContact(@NonNull String leadId, @NonNull String name) {
        repository.lead(leadId, result -> {
            if (binding == null) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null) toast(result.error.message);
                return;
            }
            LeadDetailResponse lead = result.data;
            List<PickerSheet.Option> options = new ArrayList<>();
            List<ContactDto> contacts = lead.contacts == null
                    ? new ArrayList<>() : lead.contacts;
            for (ContactDto row : contacts) {
                // The message is matched to a client by the address it came
                // from, so a contact with neither email nor phone cannot be
                // the sender of anything.
                if (addressOf(row) == null) continue;
                options.add(new PickerSheet.Option(row.id, row.name, addressOf(row)));
            }
            if (options.isEmpty()) {
                toast(getString(R.string.log_reply_no_reachable_contacts, name));
                return;
            }
            PickerSheet.open(getParentFragmentManager(),
                    getString(R.string.triage_pick_contact),
                    getString(R.string.triage_pick_contact_hint, name), options,
                    picked -> {
                        for (ContactDto row : contacts) {
                            if (row.id.equals(picked.id)) contact = row;
                        }
                        leadName = name;
                        if (binding != null && contact != null) {
                            binding.contactButton.setText(
                                    getString(R.string.log_reply_from,
                                            contact.name, name));
                        }
                    });
        });
    }

    /** WhatsApp and calls come from a phone, email from an address. */
    @Nullable
    private String addressOf(@NonNull ContactDto row) {
        if ("email".equals(channel)) {
            return row.email != null && !row.email.isEmpty() ? row.email : null;
        }
        if (row.phone != null && !row.phone.isEmpty()) return row.phone;
        return row.email != null && !row.email.isEmpty() ? row.email : null;
    }

    private void submit() {
        if (contact == null) {
            toast(getString(R.string.log_reply_needs_contact));
            return;
        }
        String from = addressOf(contact);
        if (from == null) {
            toast(getString(R.string.log_reply_contact_unreachable, channel));
            return;
        }
        String body = text(binding.bodyInput.getText());
        if (body.isEmpty()) {
            toast(getString(R.string.log_reply_needs_body));
            return;
        }
        String subject = text(binding.subjectInput.getText());
        binding.submitButton.setEnabled(false);
        repository.logClientReply(
                new InboundIngestRequest(channel, from,
                        subject.isEmpty() ? null : subject, body),
                result -> {
                    if (binding == null) return;
                    binding.submitButton.setEnabled(true);
                    if (result.isSuccess() && result.data != null) {
                        // Show what the engines made of it — this is the only
                        // moment the person who heard the client can correct a
                        // misreading.
                        binding.resultText.setText(getString(
                                R.string.log_reply_result,
                                LeadStates.label(result.data.intent),
                                LeadStates.label(result.data.status)));
                        binding.resultText.setVisibility(View.VISIBLE);
                        getParentFragmentManager().setFragmentResult(
                                RESULT_KEY, new Bundle());
                    } else if (result.error != null) {
                        toast(result.error.message);
                    }
                });
    }

    private String text(@Nullable CharSequence value) {
        return value == null ? "" : value.toString().trim();
    }

    private void toast(@NonNull String message) {
        Toast.makeText(requireContext(), message, Toast.LENGTH_LONG).show();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
