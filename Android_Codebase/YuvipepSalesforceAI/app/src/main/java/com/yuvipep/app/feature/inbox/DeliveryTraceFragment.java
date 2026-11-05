package com.yuvipep.app.feature.inbox;

import android.content.res.ColorStateList;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.FileRepository;
import com.yuvipep.app.core.net.dto.MessageDto;
import com.yuvipep.app.core.util.Times;
import com.yuvipep.app.databinding.FragmentDeliveryTraceBinding;
import com.yuvipep.app.databinding.ItemDeliveryEventBinding;
import com.yuvipep.app.feature.leads.LeadStates;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * One message's delivery trace (03 §9): the timeline the backend recorded in
 * `delivery_log[]` — drafted, queued, sent, and whatever the provider said
 * afterwards — plus the message as it was written.
 *
 * Two honest limits, both stated on screen rather than hidden:
 *  • Attachments are stored by the backend but not returned by GET /messages,
 *    so this screen cannot list them.
 *  • The .eml button only appears for a dry-run send, because that is the only
 *    case where the "sent" event's detail names a file we can fetch. A real
 *    SMTP send records the account it went through, not a copy of the mail.
 */
@AndroidEntryPoint
public class DeliveryTraceFragment extends Fragment {

    private static final String ARG_MESSAGE = "message_id";
    private static final String DRY_RUN = "dry_run:";

    public static DeliveryTraceFragment create(@NonNull String messageId) {
        DeliveryTraceFragment fragment = new DeliveryTraceFragment();
        Bundle args = new Bundle();
        args.putString(ARG_MESSAGE, messageId);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject InboxRepository repository;
    @Inject FileRepository files;
    @Inject ApiService api;

    private FragmentDeliveryTraceBinding binding;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentDeliveryTraceBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        load();
    }

    private void load() {
        binding.stateView.showLoading();
        repository.message(requireArguments().getString(ARG_MESSAGE, ""), result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                binding.stateView.hide();
                render(result.data);
            } else if (result.isError() && result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        });
    }

    private void render(@NonNull MessageDto message) {
        binding.statusText.setText(MessageStatuses.label(message.status));
        binding.subjectText.setText(
                message.subject != null && !message.subject.isEmpty()
                        ? message.subject
                        : getString(R.string.delivery_trace_no_subject));
        binding.metaText.setText(getString(R.string.delivery_trace_meta,
                message.to == null ? "" : message.to,
                LeadStates.label(message.channel),
                LeadStates.label(message.kind)));
        if (message.lastError != null && !message.lastError.isEmpty()) {
            binding.errorText.setText(message.lastError);
            binding.errorText.setVisibility(View.VISIBLE);
        } else {
            binding.errorText.setVisibility(View.GONE);
        }
        binding.bodyText.setText(message.body);

        binding.timelineContainer.removeAllViews();
        if (message.deliveryLog == null || message.deliveryLog.isEmpty()) {
            // Not an error: a draft nobody has acted on has no events yet.
            ItemDeliveryEventBinding row = ItemDeliveryEventBinding.inflate(
                    LayoutInflater.from(requireContext()),
                    binding.timelineContainer, false);
            row.eventText.setText(R.string.delivery_trace_no_events);
            row.eventAt.setVisibility(View.GONE);
            binding.timelineContainer.addView(row.getRoot());
        } else {
            for (MessageDto.DeliveryEvent event : message.deliveryLog) {
                binding.timelineContainer.addView(eventRow(event));
            }
        }

        String eml = dryRunPath(message);
        binding.openEmlButton.setVisibility(eml == null ? View.GONE : View.VISIBLE);
        if (eml != null) {
            binding.openEmlButton.setOnClickListener(v -> openEml(eml));
        }
    }

    private View eventRow(@NonNull MessageDto.DeliveryEvent event) {
        ItemDeliveryEventBinding row = ItemDeliveryEventBinding.inflate(
                LayoutInflater.from(requireContext()),
                binding.timelineContainer, false);
        row.eventText.setText(LeadStates.label(event.event));
        row.eventAt.setText(Times.dateTimeLabel(event.at));
        row.eventDot.setBackgroundTintList(ColorStateList.valueOf(
                ContextCompat.getColor(requireContext(), eventColor(event.event))));
        if (event.detail != null && !event.detail.isEmpty()) {
            row.eventDetail.setText(event.detail);
            row.eventDetail.setVisibility(View.VISIBLE);
        } else {
            row.eventDetail.setVisibility(View.GONE);
        }
        return row.getRoot();
    }

    private int eventColor(@Nullable String event) {
        if (event == null) return R.color.lead_open;
        if (event.contains("fail") || event.contains("bounce")
                || event.contains("reject") || event.contains("dead")) {
            return R.color.lead_lost;
        }
        // Same reading as the status dots: arrived = green, still moving = teal.
        if (event.contains("deliver") || event.contains("sent")) {
            return R.color.lead_active;
        }
        return R.color.lead_client_execution;
    }

    /**
     * The storage path of a dry-run send, from the "sent" event's detail
     * ({@code dry_run:orgs/<org>/outbox/<file>.eml}), or null for a real send.
     */
    @Nullable
    private String dryRunPath(@NonNull MessageDto message) {
        if (message.deliveryLog == null) return null;
        for (MessageDto.DeliveryEvent event : message.deliveryLog) {
            if (event.detail != null && event.detail.startsWith(DRY_RUN)) {
                String path = event.detail.substring(DRY_RUN.length());
                return path.isEmpty() ? null : path;
            }
        }
        return null;
    }

    private void openEml(@NonNull String relPath) {
        binding.openEmlButton.setEnabled(false);
        files.fetch(api.file(relPath), relPath, "eml", result -> {
            if (binding == null) return;
            binding.openEmlButton.setEnabled(true);
            if (result.isSuccess() && result.data != null) {
                showEml(result.data);
            } else if (result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
            }
        });
    }

    private void showEml(@NonNull File file) {
        String raw;
        try {
            raw = new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
        } catch (Exception e) {
            Toast.makeText(requireContext(),
                    getString(R.string.delivery_trace_eml_unreadable, e.getMessage()),
                    Toast.LENGTH_LONG).show();
            return;
        }
        // The raw RFC-822 bytes, verbatim: this is exactly what left the system.
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.delivery_trace_eml_title)
                .setMessage(raw)
                .setPositiveButton(R.string.action_close, null)
                .show();
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
