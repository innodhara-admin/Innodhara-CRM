package com.yuvipep.app.feature.leads;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.ContactDto;
import com.yuvipep.app.core.net.dto.LeadRequests;
import com.yuvipep.app.databinding.SheetContactBinding;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * One sheet for three moments: add a contact manually, edit an existing one
 * (a human save clears needs_review server-side), and verify a fresh card
 * scan (03 §4). Saving posts a fragment result so the detail reloads.
 */
@AndroidEntryPoint
public class ContactSheet extends BottomSheetDialogFragment {

    public static final String RESULT_KEY = "contact_saved";

    private static final String ARG_LEAD = "lead_id";
    private static final String ARG_CONTACT_ID = "contact_id";
    private static final String ARG_NAME = "name";
    private static final String ARG_TITLE = "title";
    private static final String ARG_EMAIL = "email";
    private static final String ARG_PHONE = "phone";
    private static final String ARG_PRIMARY = "primary";
    private static final String ARG_NEEDS_REVIEW = "needs_review";
    private static final String ARG_CONFIDENCE = "confidence";
    private static final String ARG_ORG_ON_CARD = "org_on_card";
    private static final String ARG_INTRO_INFO = "intro_info";
    private static final String ARG_SCAN = "is_scan";

    public static void showAdd(@NonNull FragmentManager fm, @NonNull String leadId) {
        ContactSheet sheet = new ContactSheet();
        Bundle args = new Bundle();
        args.putString(ARG_LEAD, leadId);
        sheet.setArguments(args);
        sheet.show(fm, "contact");
    }

    public static void showEdit(@NonNull FragmentManager fm, @NonNull String leadId,
                                @NonNull ContactDto contact) {
        ContactSheet sheet = new ContactSheet();
        Bundle args = new Bundle();
        args.putString(ARG_LEAD, leadId);
        args.putString(ARG_CONTACT_ID, contact.id);
        args.putString(ARG_NAME, contact.name);
        args.putString(ARG_TITLE, contact.title);
        args.putString(ARG_EMAIL, contact.email);
        args.putString(ARG_PHONE, contact.phone);
        args.putBoolean(ARG_PRIMARY, contact.isPrimary);
        args.putBoolean(ARG_NEEDS_REVIEW, contact.needsReview);
        sheet.setArguments(args);
        sheet.show(fm, "contact");
    }

    /** The bundle here is CardScanFragment.RESULT_KEY's payload. */
    public static void showScanResult(@NonNull FragmentManager fm,
                                      @NonNull String leadId,
                                      @NonNull Bundle scanResult) {
        ContactSheet sheet = new ContactSheet();
        Bundle args = new Bundle(scanResult);
        args.putString(ARG_LEAD, leadId);
        args.putBoolean(ARG_SCAN, true);
        sheet.setArguments(args);
        sheet.show(fm, "contact");
    }

    /** Builds the scan-result payload (used by CardScanFragment). */
    public static Bundle scanBundle(@NonNull ContactDto contact,
                                    @Nullable String introInfo) {
        Bundle out = new Bundle();
        out.putString(ARG_CONTACT_ID, contact.id);
        out.putString(ARG_NAME, contact.name);
        out.putString(ARG_TITLE, contact.title);
        out.putString(ARG_EMAIL, contact.email);
        out.putString(ARG_PHONE, contact.phone);
        out.putBoolean(ARG_NEEDS_REVIEW, contact.needsReview);
        if (contact.confidence != null) {
            out.putDouble(ARG_CONFIDENCE, contact.confidence);
        }
        out.putString(ARG_ORG_ON_CARD, contact.organisationOnCard);
        out.putString(ARG_INTRO_INFO, introInfo);
        return out;
    }

    @Inject LeadsRepository repository;

    private SheetContactBinding binding;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetContactBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        Bundle args = requireArguments();
        boolean isEdit = args.getString(ARG_CONTACT_ID) != null;
        boolean isScan = args.getBoolean(ARG_SCAN, false);

        binding.sheetTitle.setText(isScan ? getString(R.string.contact_scan_title)
                : isEdit ? getString(R.string.contact_edit_title)
                        : getString(R.string.contact_add_title));
        binding.nameInput.setText(args.getString(ARG_NAME));
        binding.titleInput.setText(args.getString(ARG_TITLE));
        binding.emailInput.setText(args.getString(ARG_EMAIL));
        binding.phoneInput.setText(args.getString(ARG_PHONE));
        binding.primarySwitch.setChecked(args.getBoolean(ARG_PRIMARY, false));

        if (args.getBoolean(ARG_NEEDS_REVIEW, false)) {
            binding.reviewBanner.setVisibility(View.VISIBLE);
            binding.reviewBannerText.setText(R.string.contact_review_banner);
        }
        if (isScan) {
            StringBuilder meta = new StringBuilder();
            if (args.containsKey(ARG_CONFIDENCE)) {
                meta.append(getString(R.string.contact_scan_confidence,
                        Math.round(args.getDouble(ARG_CONFIDENCE) * 100)));
            }
            String org = args.getString(ARG_ORG_ON_CARD);
            if (org != null && !org.isEmpty()) {
                if (meta.length() > 0) meta.append(" · ");
                meta.append(getString(R.string.contact_scan_org, org));
            }
            if (meta.length() > 0) {
                binding.scanMeta.setText(meta);
                binding.scanMeta.setVisibility(View.VISIBLE);
            }
            String intro = args.getString(ARG_INTRO_INFO);
            if (intro != null && !intro.isEmpty()) {
                binding.introInfo.setText(intro);
                binding.introInfo.setVisibility(View.VISIBLE);
            }
        }

        binding.saveButton.setOnClickListener(v -> save(args));
    }

    private void save(Bundle args) {
        String name = text(binding.nameInput.getText());
        if (name.isEmpty()) {
            Toast.makeText(requireContext(), R.string.contact_name_required,
                    Toast.LENGTH_SHORT).show();
            return;
        }
        binding.saveButton.setEnabled(false);
        LeadRequests.Contact body = new LeadRequests.Contact();
        body.name = name;
        body.title = nullable(text(binding.titleInput.getText()));
        body.email = nullable(text(binding.emailInput.getText()));
        body.phone = nullable(text(binding.phoneInput.getText()));
        body.isPrimary = binding.primarySwitch.isChecked();

        String contactId = args.getString(ARG_CONTACT_ID);
        com.yuvipep.app.core.util.RepoCallback<ContactDto> done = result -> {
            if (binding == null) return;
            binding.saveButton.setEnabled(true);
            if (result.isSuccess()) {
                getParentFragmentManager().setFragmentResult(RESULT_KEY, new Bundle());
                dismiss();
            } else if (result.error != null) {
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
            }
        };
        if (contactId != null) {
            repository.updateContact(contactId, body, done);
        } else {
            repository.addContact(args.getString(ARG_LEAD, ""), body, done);
        }
    }

    private static String text(@Nullable CharSequence value) {
        return value == null ? "" : value.toString().trim();
    }

    @Nullable
    private static String nullable(@NonNull String value) {
        return value.isEmpty() ? null : value;
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
