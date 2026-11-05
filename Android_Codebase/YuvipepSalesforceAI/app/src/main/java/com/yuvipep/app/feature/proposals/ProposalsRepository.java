package com.yuvipep.app.feature.proposals;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.FileRepository;
import com.yuvipep.app.core.net.dto.ProposalDetailDto;
import com.yuvipep.app.core.net.dto.ProposalRequests;
import com.yuvipep.app.core.net.dto.ProposalResponses;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.File;
import java.io.IOException;
import java.util.List;

import javax.inject.Inject;
import javax.inject.Singleton;

import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.RequestBody;
import retrofit2.Call;
import retrofit2.Response;

/** The /proposals routes + the rendered-PDF fetch through the file cache. */
@Singleton
public class ProposalsRepository {

    private final ApiService api;
    private final AppExecutors executors;
    private final FileRepository files;

    @Inject
    public ProposalsRepository(ApiService api, AppExecutors executors,
                               FileRepository files) {
        this.api = api;
        this.executors = executors;
        this.files = files;
    }

    public void detail(@NonNull String proposalId,
                       @NonNull RepoCallback<ProposalDetailDto> callback) {
        run(api.proposal(proposalId), callback);
    }

    public void edit(@NonNull String proposalId, @NonNull String instruction,
                     @NonNull RepoCallback<ProposalDetailDto> callback) {
        run(api.editProposal(proposalId, new ProposalRequests.Edit(instruction)),
                callback);
    }

    public void submitReview(@NonNull String proposalId,
                             @NonNull RepoCallback<ProposalResponses.SubmitReview> callback) {
        run(api.submitProposalReview(proposalId), callback);
    }

    public void approveSend(@NonNull String proposalId, @NonNull String toAddress,
                            @NonNull List<String> cc, @Nullable String extraNote,
                            @NonNull RepoCallback<ProposalResponses.ApproveSend> callback) {
        run(api.approveSendProposal(proposalId,
                new ProposalRequests.ApproveSend(toAddress, cc, extraNote)), callback);
    }

    /**
     * The rendered PDF, cached per revision count — an edit or upload bumps
     * the version tag so the viewer never shows a stale render.
     */
    public void pdf(@NonNull String proposalId, @NonNull String versionTag,
                    @NonNull RepoCallback<File> callback) {
        files.fetch(api.downloadProposal(proposalId, "pdf"),
                "proposal_" + proposalId + "_v" + versionTag, "pdf", callback);
    }

    public void uploadRevision(@NonNull String proposalId, @NonNull File file,
                               @NonNull String fileName,
                               @NonNull RepoCallback<ProposalResponses.UploadRevision> callback) {
        String mime = fileName.toLowerCase().endsWith(".pdf")
                ? "application/pdf"
                : "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        RequestBody body = RequestBody.create(file, MediaType.parse(mime));
        MultipartBody.Part part =
                MultipartBody.Part.createFormData("file", fileName, body);
        run(api.uploadProposalRevision(proposalId, part), callback);
    }

    private <T> void run(@NonNull Call<T> call, @NonNull RepoCallback<T> callback) {
        executors.io().execute(() -> {
            try {
                Response<T> response = call.execute();
                if (response.isSuccessful() && response.body() != null) {
                    post(callback, Result.success(response.body()));
                } else {
                    post(callback, Result.error(ErrorMapper.fromResponse(response)));
                }
            } catch (IOException e) {
                post(callback, Result.error(ErrorMapper.fromThrowable(e)));
            }
        });
    }

    private <T> void post(@NonNull RepoCallback<T> callback, @NonNull Result<T> result) {
        executors.main().execute(() -> callback.onResult(result));
    }
}
