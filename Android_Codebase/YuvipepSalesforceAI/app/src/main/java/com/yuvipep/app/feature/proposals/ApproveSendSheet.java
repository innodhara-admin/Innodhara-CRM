package com.yuvipep.app.feature.proposals;

import android.os.Bundle;
import android.util.Patterns;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.FragmentManager;

import com.google.android.material.bottomsheet.BottomSheetDialogFragment;
import com.yuvipep.app.R;
import com.yuvipep.app.databinding.SheetApproveSendBinding;

import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * The one-tap gate made explicit (03 §6): who receives it, optional CC and
 * note, and a plain warning that this REALLY emails the client. The send is
 * queued server-side; failures surface in the message center.
 */
@AndroidEntryPoint
public class ApproveSendSheet extends BottomSheetDialogFragment {

    public static final String RESULT_KEY = "proposal_sent";
    public static final String RESULT_TO = "to";

    private static final String ARG_ID = "proposal_id";

    public static void open(@NonNull FragmentManager fm, @NonNull String proposalId) {
        ApproveSendSheet sheet = new ApproveSendSheet();
        Bundle args = new Bundle();
        args.putString(ARG_ID, proposalId);
        sheet.setArguments(args);
        sheet.show(fm, "approve_send");
    }

    @Inject ProposalsRepository repository;

    private SheetApproveSendBinding binding;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = SheetApproveSendBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.sendButton.setOnClickListener(v -> send());
    }

    private void send() {
        String to = binding.toInput.getText() == null ? ""
                : binding.toInput.getText().toString().trim();
        if (!Patterns.EMAIL_ADDRESS.matcher(to).matches()) {
            Toast.makeText(requireContext(), R.string.proposal_send_bad_to,
                    Toast.LENGTH_SHORT).show();
            return;
        }
        List<String> cc = new ArrayList<>();
        String ccRaw = binding.ccInput.getText() == null ? ""
                : binding.ccInput.getText().toString().trim();
        for (String part : ccRaw.split("[,;\\s]+")) {
            if (part.isEmpty()) continue;
            if (!Patterns.EMAIL_ADDRESS.matcher(part).matches()) {
                Toast.makeText(requireContext(),
                        getString(R.string.proposal_send_bad_cc, part),
                        Toast.LENGTH_SHORT).show();
                return;
            }
            cc.add(part);
        }
        String note = binding.noteInput.getText() == null ? null
                : binding.noteInput.getText().toString().trim();
        if (note != null && note.isEmpty()) note = null;

        binding.sendButton.setEnabled(false);
        repository.approveSend(requireArguments().getString(ARG_ID, ""),
                to, cc, note, result -> {
                    if (binding == null) return;
                    binding.sendButton.setEnabled(true);
                    if (result.isSuccess() && result.data != null) {
                        Bundle out = new Bundle();
                        out.putString(RESULT_TO, result.data.to);
                        getParentFragmentManager().setFragmentResult(RESULT_KEY, out);
                        dismiss();
                    } else if (result.error != null) {
                        Toast.makeText(requireContext(), result.error.message,
                                Toast.LENGTH_LONG).show();
                    }
                });
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
