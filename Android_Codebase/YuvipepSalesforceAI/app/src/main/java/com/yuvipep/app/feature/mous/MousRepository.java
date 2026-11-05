package com.yuvipep.app.feature.mous;

import androidx.annotation.NonNull;

import com.yuvipep.app.core.net.ApiService;
import com.yuvipep.app.core.net.ErrorMapper;
import com.yuvipep.app.core.net.FileRepository;
import com.yuvipep.app.core.net.dto.MouDto;
import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.File;
import java.io.IOException;

import javax.inject.Inject;
import javax.inject.Singleton;

import retrofit2.Call;
import retrofit2.Response;

/**
 * The /mous routes + the rendered-PDF fetch through the file cache.
 *
 * <p><b>Its own class rather than a pair of methods on
 * {@code ProposalsRepository}, for the reason {@code MouLines} is its own
 * package.</b> An MOU is not a proposal: it is signed after one is accepted,
 * it has no commercials, and it has no send path. Sharing the repository is
 * the first step towards a proposal's rule — "a sent proposal means the deal
 * is agreed" — being applied to a contract, which would advance a deal that
 * closed weeks ago.
 */
@Singleton
public class MousRepository {

    private final ApiService api;
    private final AppExecutors executors;
    private final FileRepository files;

    @Inject
    public MousRepository(ApiService api, AppExecutors executors,
                          FileRepository files) {
        this.api = api;
        this.executors = executors;
        this.files = files;
    }

    public void detail(@NonNull String mouId,
                       @NonNull RepoCallback<MouDto> callback) {
        run(api.mou(mouId), callback);
    }

    /**
     * The contract as a PDF, cached per correction.
     *
     * <p>Keyed on {@link MouLines#versionTag}, which counts the corrections: a
     * correction writes new files against the SAME row, so the id alone would
     * serve the salesperson the wording they had just corrected — and let them
     * send it.
     *
     * <p>Asked for as {@code format=pdf} even when the contract's stored PDF is
     * missing. The backend renders one on the way out, which is the retry that
     * a failed conversion needs.
     */
    public void pdf(@NonNull String mouId, @NonNull String versionTag,
                    @NonNull RepoCallback<File> callback) {
        files.fetch(api.downloadMou(mouId, "pdf"),
                "mou_" + mouId + "_v" + versionTag, "pdf", callback);
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

    private <T> void post(@NonNull RepoCallback<T> callback,
                          @NonNull Result<T> result) {
        executors.main().execute(() -> callback.onResult(result));
    }
}
