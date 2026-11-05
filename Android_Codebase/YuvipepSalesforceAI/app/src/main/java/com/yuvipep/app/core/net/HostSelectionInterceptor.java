package com.yuvipep.app.core.net;

import androidx.annotation.NonNull;

import java.io.IOException;

import javax.inject.Inject;
import javax.inject.Singleton;

import okhttp3.HttpUrl;
import okhttp3.Interceptor;
import okhttp3.Request;
import okhttp3.Response;

/**
 * Rewrites every request onto the runtime-selected server
 * (EnvironmentStore) so the base URL can change without rebuilding
 * Retrofit — the environment sheet applies instantly.
 */
@Singleton
public class HostSelectionInterceptor implements Interceptor {

    /**
     * ngrok's free tier serves an HTML "you're about to visit..." interstitial
     * to any request without this header, even non-browser API calls — which
     * would otherwise break every request (JSON parser choking on HTML) the
     * moment the base URL points at a *.ngrok-free.dev tunnel. Harmless noise
     * to every other host (Cloudflare tunnels, localhost, a real prod server).
     */
    private static final String NGROK_SKIP_WARNING_HEADER = "ngrok-skip-browser-warning";

    private final EnvironmentStore environmentStore;

    @Inject
    public HostSelectionInterceptor(EnvironmentStore environmentStore) {
        this.environmentStore = environmentStore;
    }

    @NonNull
    @Override
    public Response intercept(@NonNull Chain chain) throws IOException {
        Request request = chain.request();
        HttpUrl target = HttpUrl.parse(environmentStore.getBaseUrl());
        if (target != null) {
            HttpUrl newUrl = request.url().newBuilder()
                    .scheme(target.scheme())
                    .host(target.host())
                    .port(target.port())
                    .build();
            request = request.newBuilder().url(newUrl).build();
        }
        request = request.newBuilder()
                .header(NGROK_SKIP_WARNING_HEADER, "true")
                .build();
        return chain.proceed(request);
    }
}
