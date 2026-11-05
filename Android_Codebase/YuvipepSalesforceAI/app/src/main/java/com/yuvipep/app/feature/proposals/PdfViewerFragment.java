package com.yuvipep.app.feature.proposals;

import android.graphics.Bitmap;
import android.graphics.pdf.PdfRenderer;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.yuvipep.app.R;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.databinding.FragmentPdfViewerBinding;
import com.yuvipep.app.feature.mous.MousRepository;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import javax.inject.Inject;

import dagger.hilt.android.AndroidEntryPoint;

/**
 * In-app PDF preview (08 §4): the rendered proposal, fetched through the
 * authenticated file cache and drawn page-by-page with the platform
 * PdfRenderer — no external viewer, no file leaves the sandbox.
 */
@AndroidEntryPoint
public class PdfViewerFragment extends Fragment {

    private static final String ARG_ID = "proposal_id";
    private static final String ARG_VERSION = "version";
    private static final String ARG_TITLE = "title";
    /** Which repository holds this document's bytes. */
    private static final String ARG_KIND = "kind";
    private static final String KIND_MOU = "mou";

    public static PdfViewerFragment create(@NonNull String proposalId,
                                           @NonNull String versionTag,
                                           @NonNull String title) {
        return of("proposal", proposalId, versionTag, title);
    }

    /**
     * The same viewer, for a contract.
     *
     * <p>Only the fetch differs. A second renderer, page adapter and bitmap
     * cache for the sake of the word "MOU" would be three more places for the
     * descriptor leak {@code onDestroyView} closes here to come back. Which
     * document it is stays an ARGUMENT rather than becoming an assumption, so
     * nothing in here treats a contract as a proposal.
     */
    public static PdfViewerFragment forMou(@NonNull String mouId,
                                           @NonNull String versionTag,
                                           @NonNull String title) {
        return of(KIND_MOU, mouId, versionTag, title);
    }

    private static PdfViewerFragment of(@NonNull String kind, @NonNull String id,
                                        @NonNull String versionTag,
                                        @NonNull String title) {
        PdfViewerFragment fragment = new PdfViewerFragment();
        Bundle args = new Bundle();
        args.putString(ARG_KIND, kind);
        args.putString(ARG_ID, id);
        args.putString(ARG_VERSION, versionTag);
        args.putString(ARG_TITLE, title);
        fragment.setArguments(args);
        return fragment;
    }

    @Inject ProposalsRepository repository;
    @Inject MousRepository mous;

    private FragmentPdfViewerBinding binding;
    private PdfRenderer renderer;
    private ParcelFileDescriptor descriptor;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentPdfViewerBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        binding.pdfTitle.setText(requireArguments().getString(ARG_TITLE, ""));
        binding.backButton.setOnClickListener(v ->
                requireActivity().getOnBackPressedDispatcher().onBackPressed());
        binding.pageList.setLayoutManager(new LinearLayoutManager(requireContext()));
        load();
    }

    private void load() {
        binding.stateView.showLoading();
        String id = requireArguments().getString(ARG_ID, "");
        String version = requireArguments().getString(ARG_VERSION, "0");
        RepoCallback<File> callback = result -> {
            if (binding == null) return;
            if (result.isSuccess() && result.data != null) {
                open(result.data);
            } else if (result.error != null) {
                binding.stateView.showError(result.error.message, this::load);
            }
        };
        if (KIND_MOU.equals(requireArguments().getString(ARG_KIND))) {
            mous.pdf(id, version, callback);
        } else {
            repository.pdf(id, version, callback);
        }
    }

    private void open(@NonNull File file) {
        try {
            descriptor = ParcelFileDescriptor.open(file,
                    ParcelFileDescriptor.MODE_READ_ONLY);
            renderer = new PdfRenderer(descriptor);
            binding.stateView.hide();
            binding.pageList.setAdapter(new PageAdapter(renderer));
        } catch (IOException | SecurityException e) {
            // A corrupt cache entry must not wedge the screen: drop and retry
            // fetches a fresh copy.
            //noinspection ResultOfMethodCallIgnored
            file.delete();
            binding.stateView.showError(getString(R.string.pdf_open_failed,
                    e.getMessage() == null ? "" : e.getMessage()), this::load);
        }
    }

    private static class PageAdapter extends RecyclerView.Adapter<PageAdapter.Holder> {

        private final PdfRenderer renderer;
        private final List<Bitmap> cache = new ArrayList<>();

        PageAdapter(PdfRenderer renderer) {
            this.renderer = renderer;
            for (int i = 0; i < renderer.getPageCount(); i++) cache.add(null);
        }

        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            ImageView image = (ImageView) LayoutInflater.from(parent.getContext())
                    .inflate(R.layout.item_pdf_page, parent, false);
            return new Holder(image);
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            Bitmap bitmap = cache.get(position);
            if (bitmap == null) {
                synchronized (renderer) {
                    try (PdfRenderer.Page page = renderer.openPage(position)) {
                        int width = holder.itemView.getResources()
                                .getDisplayMetrics().widthPixels;
                        int height = (int) ((float) width
                                / page.getWidth() * page.getHeight());
                        bitmap = Bitmap.createBitmap(width, height,
                                Bitmap.Config.ARGB_8888);
                        bitmap.eraseColor(android.graphics.Color.WHITE);
                        page.render(bitmap, null, null,
                                PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                    }
                }
                cache.set(position, bitmap);
            }
            ((ImageView) holder.itemView).setImageBitmap(bitmap);
        }

        @Override
        public int getItemCount() {
            return renderer.getPageCount();
        }

        static class Holder extends RecyclerView.ViewHolder {
            Holder(@NonNull ImageView view) {
                super(view);
            }
        }
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        binding.pageList.setAdapter(null);
        if (renderer != null) {
            renderer.close();
            renderer = null;
        }
        if (descriptor != null) {
            try {
                descriptor.close();
            } catch (IOException ignored) {
                // already closed
            }
            descriptor = null;
        }
        binding = null;
    }
}
