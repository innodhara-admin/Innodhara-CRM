package com.yuvipep.app.feature.assistant.voice;

import android.os.Handler;
import android.os.Looper;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.gson.JsonObject;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/**
 * One connection to {@code WS /api/v1/assistant/voice}.
 *
 * <p>Built on the app's OkHttp client, so the request goes through the same
 * interceptors as every API call: the runtime server (HostSelection), the
 * bearer token (Auth) and ngrok's interstitial header. Every callback is
 * delivered on the main thread, <b>in arrival order</b> — audio frames and the
 * {@code interrupted}/{@code speak_end} messages around them must not be
 * reordered, or a flush would drop the wrong audio.
 */
final class VoiceSocket {

    interface Listener {
        void onOpen();

        void onMessage(@NonNull JsonObject message);

        void onAudio(@NonNull byte[] pcm);

        /**
         * The socket is gone. {@code everOpened == false} means the handshake
         * itself failed — a proxy without WebSocket support looks like this.
         */
        void onClosed(int code, @Nullable String reason, boolean everOpened);
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private final Listener listener;
    @Nullable private WebSocket socket;
    private volatile boolean opened;
    /** The socket is over, either way — nothing more is sent. */
    private volatile boolean finished;
    /** We closed it: whatever is still queued for the main thread is dropped.
     *  A server close keeps its queue — the fatal error before it matters. */
    private volatile boolean closedByUs;

    VoiceSocket(@NonNull Listener listener) {
        this.listener = listener;
    }

    void connect(@NonNull OkHttpClient appClient, @NonNull String url) {
        OkHttpClient client = appClient.newBuilder()
                .readTimeout(0, TimeUnit.MILLISECONDS)   // a conversation has pauses
                .pingInterval(15, TimeUnit.SECONDS)      // notices a dead network
                .build();
        // OkHttp wants http(s) in the Request; it speaks ws on the wire.
        String httpUrl = url.startsWith("wss://") ? "https://" + url.substring(6)
                : url.startsWith("ws://") ? "http://" + url.substring(5) : url;
        Request request = new Request.Builder().url(httpUrl).build();
        socket = client.newWebSocket(request, new WebSocketListener() {
            @Override
            public void onOpen(@NonNull WebSocket webSocket, @NonNull Response response) {
                opened = true;
                post(listener::onOpen);
            }

            @Override
            public void onMessage(@NonNull WebSocket webSocket, @NonNull String text) {
                JsonObject message = VoiceProtocol.parse(text);
                if (message != null) post(() -> listener.onMessage(message));
            }

            @Override
            public void onMessage(@NonNull WebSocket webSocket, @NonNull ByteString bytes) {
                byte[] pcm = bytes.toByteArray();
                post(() -> listener.onAudio(pcm));
            }

            @Override
            public void onClosing(@NonNull WebSocket webSocket, int code, @NonNull String reason) {
                webSocket.close(code == 1005 ? VoiceProtocol.CLOSE_NORMAL : code, null);
                closed(code, reason);
            }

            @Override
            public void onClosed(@NonNull WebSocket webSocket, int code, @NonNull String reason) {
                closed(code, reason);
            }

            @Override
            public void onFailure(@NonNull WebSocket webSocket, @NonNull Throwable t,
                                  @Nullable Response response) {
                // 1006: "abnormal" — no close frame. A proxy refusing the
                // upgrade answers with an HTTP status instead of 101.
                closed(1006, response != null ? "HTTP " + response.code() : t.getMessage());
            }
        });
    }

    boolean sendText(@NonNull String json) {
        WebSocket s = socket;
        return s != null && !finished && s.send(json);
    }

    /** Thread-safe; OkHttp queues the frame. */
    boolean sendAudio(@NonNull byte[] frame) {
        WebSocket s = socket;
        return s != null && !finished && opened && s.send(ByteString.of(frame));
    }

    /** Close politely; no {@link Listener#onClosed} for a close we asked for. */
    void close() {
        if (finished) return;
        finished = true;
        closedByUs = true;
        main.removeCallbacksAndMessages(null);
        WebSocket s = socket;
        if (s != null) {
            s.send(VoiceProtocol.control("stop"));
            s.close(VoiceProtocol.CLOSE_NORMAL, null);
        }
    }

    private void closed(int code, @Nullable String reason) {
        if (finished) return;
        finished = true;
        boolean everOpened = opened;
        post(() -> listener.onClosed(code, reason, everOpened));
    }

    private void post(@NonNull Runnable r) {
        main.post(() -> {
            if (!closedByUs) r.run();
        });
    }
}
