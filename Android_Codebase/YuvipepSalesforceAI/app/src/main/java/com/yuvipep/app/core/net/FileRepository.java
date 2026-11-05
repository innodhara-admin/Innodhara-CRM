package com.yuvipep.app.core.net;

import android.content.Context;

import androidx.annotation.NonNull;

import com.yuvipep.app.core.util.AppExecutors;
import com.yuvipep.app.core.util.RepoCallback;
import com.yuvipep.app.core.util.Result;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import javax.inject.Inject;
import javax.inject.Singleton;

import dagger.hilt.android.qualifiers.ApplicationContext;
import okhttp3.ResponseBody;
import retrofit2.Call;
import retrofit2.Response;

/**
 * Authenticated file fetch with a disk cache (08 §4): PDFs and other stored
 * artifacts land in cacheDir/yuvipep_files keyed by a hash of what was asked
 * for, so re-opening a proposal is instant and offline-tolerant. Callers pass
 * a version tag (e.g. updated-at or revision count) so a re-rendered file
 * with the same name is fetched fresh, not served stale.
 */
@Singleton
public class FileRepository {

    private final AppExecutors executors;
    private final File cacheRoot;

    @Inject
    public FileRepository(@ApplicationContext Context context,
                          AppExecutors executors) {
        this.executors = executors;
        this.cacheRoot = new File(context.getCacheDir(), "yuvipep_files");
    }

    /**
     * Runs {@code call}, streams the body to cache, returns the file.
     * If a cached copy for this key already exists it is returned without
     * touching the network.
     */
    public void fetch(@NonNull Call<ResponseBody> call, @NonNull String cacheKey,
                      @NonNull String extension,
                      @NonNull RepoCallback<File> callback) {
        executors.io().execute(() -> {
            File target = new File(cacheRoot, hash(cacheKey) + "." + extension);
            if (target.isFile() && target.length() > 0) {
                post(callback, Result.success(target));
                return;
            }
            try {
                Response<ResponseBody> response = call.execute();
                if (response.isSuccessful() && response.body() != null) {
                    writeTo(response.body(), target);
                    post(callback, Result.success(target));
                } else {
                    post(callback, Result.error(ErrorMapper.fromResponse(response)));
                }
            } catch (IOException e) {
                //noinspection ResultOfMethodCallIgnored — a half-written cache
                // entry must not be served next time.
                target.delete();
                post(callback, Result.error(ErrorMapper.fromThrowable(e)));
            }
        });
    }

    private void writeTo(@NonNull ResponseBody body, @NonNull File target)
            throws IOException {
        File parent = target.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new IOException("Cannot create cache directory");
        }
        File temp = new File(target.getPath() + ".part");
        try (InputStream in = body.byteStream();
             OutputStream out = new FileOutputStream(temp)) {
            byte[] buffer = new byte[16 * 1024];
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
            }
        }
        if (!temp.renameTo(target)) {
            throw new IOException("Cannot finalise cached file");
        }
    }

    private static String hash(@NonNull String key) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(key.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (int i = 0; i < 16; i++) {
                hex.append(String.format("%02x", bytes[i]));
            }
            return hex.toString();
        } catch (Exception e) {
            return String.valueOf(key.hashCode());
        }
    }

    private void post(@NonNull RepoCallback<File> callback,
                      @NonNull Result<File> result) {
        executors.main().execute(() -> callback.onResult(result));
    }
}
