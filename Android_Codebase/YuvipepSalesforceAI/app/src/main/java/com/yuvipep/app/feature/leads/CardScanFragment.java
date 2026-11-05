package com.yuvipep.app.feature.leads;

import android.Manifest;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.google.common.util.concurrent.ListenableFuture;
import com.yuvipep.app.R;
import com.yuvipep.app.databinding.FragmentCardScanBinding;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * Business-card capture (08 §2): CameraX with a card-outline guide and
 * torch toggle. The JPEG is re-encoded to ≤2MB and posted to
 * /leads/{id}/contacts/from-card; the OCR result comes back as a fragment
 * result which the lead detail opens in the verify sheet.
 */
@AndroidEntryPoint
public class CardScanFragment extends Fragment {

    public static final String RESULT_KEY = "card_scan";

    private static final String ARG_LEAD = "lead_id";
    private static final int MAX_UPLOAD_BYTES = 2 * 1024 * 1024;

    public static CardScanFragment create(@NonNull String leadId) {
        CardScanFragment fragment = new CardScanFragment();
        Bundle args = new Bundle();
        args.putString(ARG_LEAD, leadId);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject LeadsRepository repository;

    private FragmentCardScanBinding binding;
    private ImageCapture imageCapture;
    private Camera camera;
    private boolean torchOn;
    private ActivityResultLauncher<String> permissionLauncher;

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        permissionLauncher = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(), granted -> {
                    if (granted) {
                        startCamera();
                    } else {
                        Toast.makeText(requireContext(),
                                R.string.scan_camera_denied, Toast.LENGTH_LONG).show();
                        requireActivity().getOnBackPressedDispatcher().onBackPressed();
                    }
                });
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentCardScanBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.torchButton.setOnClickListener(v -> {
            torchOn = !torchOn;
            if (camera != null) camera.getCameraControl().enableTorch(torchOn);
        });
        binding.captureButton.setOnClickListener(v -> capture());

        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED) {
            startCamera();
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA);
        }
    }

    private void startCamera() {
        if (binding == null) return;
        ListenableFuture<ProcessCameraProvider> future =
                ProcessCameraProvider.getInstance(requireContext());
        future.addListener(() -> {
            if (binding == null) return;
            try {
                ProcessCameraProvider provider = future.get();
                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(binding.preview.getSurfaceProvider());
                imageCapture = new ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                        .build();
                provider.unbindAll();
                camera = provider.bindToLifecycle(getViewLifecycleOwner(),
                        CameraSelector.DEFAULT_BACK_CAMERA, preview, imageCapture);
            } catch (Exception e) {
                Toast.makeText(requireContext(),
                        getString(R.string.scan_camera_error, e.getMessage()),
                        Toast.LENGTH_LONG).show();
            }
        }, ContextCompat.getMainExecutor(requireContext()));
    }

    private void capture() {
        if (imageCapture == null || binding == null) return;
        binding.captureButton.setEnabled(false);
        File raw = new File(requireContext().getCacheDir(), "card_raw.jpg");
        ImageCapture.OutputFileOptions options =
                new ImageCapture.OutputFileOptions.Builder(raw).build();
        imageCapture.takePicture(options,
                ContextCompat.getMainExecutor(requireContext()),
                new ImageCapture.OnImageSavedCallback() {
                    @Override
                    public void onImageSaved(
                            @NonNull ImageCapture.OutputFileResults results) {
                        upload(raw);
                    }

                    @Override
                    public void onError(@NonNull ImageCaptureException exception) {
                        if (binding == null) return;
                        binding.captureButton.setEnabled(true);
                        Toast.makeText(requireContext(),
                                getString(R.string.scan_camera_error,
                                        exception.getMessage()),
                                Toast.LENGTH_LONG).show();
                    }
                });
    }

    private void upload(File raw) {
        if (binding == null) return;
        binding.uploadingOverlay.setVisibility(View.VISIBLE);
        File jpeg;
        try {
            jpeg = shrinkToLimit(raw);
        } catch (IOException e) {
            binding.uploadingOverlay.setVisibility(View.GONE);
            binding.captureButton.setEnabled(true);
            Toast.makeText(requireContext(),
                    getString(R.string.scan_camera_error, e.getMessage()),
                    Toast.LENGTH_LONG).show();
            return;
        }
        repository.scanCard(requireArguments().getString(ARG_LEAD, ""), jpeg, result -> {
            if (binding == null) return;
            binding.uploadingOverlay.setVisibility(View.GONE);
            binding.captureButton.setEnabled(true);
            if (result.isSuccess() && result.data != null
                    && result.data.contact != null) {
                // F38: the scan no longer queues an intro. It proposes fields;
                // the human edits them; the intro is drafted from what they
                // SAVE. Saying "an intro was drafted" here would be the same
                // false claim F2 was raised about, one step earlier.
                String introInfo = null;
                if (result.data.introMessage != null) {
                    // Older backend that still drafts at scan time.
                    introInfo = getString(R.string.contact_intro_drafted,
                            result.data.introMessage.to == null ? ""
                                    : result.data.introMessage.to);
                } else if (result.data.introError != null) {
                    introInfo = getString(R.string.contact_intro_error,
                            result.data.introError);
                } else if (result.data.introPending) {
                    introInfo = getString(R.string.contact_intro_pending);
                }
                getParentFragmentManager().setFragmentResult(RESULT_KEY,
                        ContactSheet.scanBundle(result.data.contact, introInfo));
                requireActivity().getOnBackPressedDispatcher().onBackPressed();
            } else if (result.isError() && result.error != null) {
                // Stay on camera so the user can re-shoot; message verbatim.
                Toast.makeText(requireContext(), result.error.message,
                        Toast.LENGTH_LONG).show();
            }
        });
    }

    /** Re-encode down (quality first, then dimensions) until ≤2MB. */
    private File shrinkToLimit(File raw) throws IOException {
        if (raw.length() <= MAX_UPLOAD_BYTES) return raw;
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(raw.getAbsolutePath(), bounds);
        int sample = 1;
        while ((bounds.outWidth / sample) * (bounds.outHeight / sample) > 4_000_000) {
            sample *= 2;
        }
        BitmapFactory.Options opts = new BitmapFactory.Options();
        opts.inSampleSize = sample;
        Bitmap bitmap = BitmapFactory.decodeFile(raw.getAbsolutePath(), opts);
        if (bitmap == null) throw new IOException("Could not decode captured image");
        File out = new File(requireContext().getCacheDir(), "card_upload.jpg");
        int quality = 90;
        do {
            try (FileOutputStream stream = new FileOutputStream(out)) {
                bitmap.compress(Bitmap.CompressFormat.JPEG, quality, stream);
            }
            quality -= 15;
        } while (out.length() > MAX_UPLOAD_BYTES && quality > 30);
        bitmap.recycle();
        return out;
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding = null;
    }
}
