package com.yuvipep.app.feature.assistant.voice;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.io.File;

import ai.guiji.duix.sdk.client.Constant;
import ai.guiji.duix.sdk.client.DUIX;
import ai.guiji.duix.sdk.client.VirtualModelUtil;
import ai.guiji.duix.sdk.client.loader.ModelInfo;
import ai.guiji.duix.sdk.client.render.DUIXRenderer;

/**
 * Jarvis's faces: Duix Mobile avatars ({@link AvatarCatalog}), with lip sync
 * driven by whatever audio they are given.
 *
 * <p>Models are not in the APK. Each is a zip from the Duix GitHub releases,
 * plus one shared base pack (133 MB), downloaded into the app's external
 * files only when the person taps Download on that face. Downloaded faces
 * stay until removed from the voice screen's menu.
 */
public final class JarvisAvatar {

    public static final String BASE_URL =
            "https://github.com/duixcom/Duix-Mobile/releases/download/v1.0.0/gj_dh_res.zip";
    /** The shared base pack: 139,403,482 bytes. */
    public static final int BASE_MB = 133;

    private static final String PREFS = "yuvipep_voice";
    private static final String KEY_SELECTED = "avatar_selected";
    /** "Voice only": no face at all, even when one is downloaded. */
    private static final String KEY_HIDDEN = "avatar_hidden";

    public interface Listener {
        /** A download or unzip step, 0–100. Main thread. */
        void onAvatarProgress(@NonNull String step, int percent);

        /** Ready to speak; {@code width}/{@code height} are the video's (0 if unknown). */
        void onAvatarReady(@NonNull DUIX duix, int width, int height);

        void onAvatarFailed(@NonNull String message);

        /** Duix finished playing an utterance (any thread). */
        void onAvatarPlayEnd();
    }

    private static Boolean nativeOk;

    private JarvisAvatar() {
    }

    /**
     * Whether Duix can run here at all: it ships for 64/32-bit ARM only, and
     * its library loads inside Duix's own render thread — where a failure
     * would crash the app — so it is tried here first.
     */
    public static synchronized boolean deviceSupported() {
        if (nativeOk != null) return nativeOk;
        boolean arm = false;
        for (String abi : Build.SUPPORTED_ABIS) {
            if ("arm64-v8a".equals(abi) || "armeabi-v7a".equals(abi)) {
                arm = true;
                break;
            }
        }
        boolean ok = false;
        if (arm) {
            try {
                System.loadLibrary("gjduix");
                ok = true;
            } catch (Throwable t) {
                android.util.Log.w("JarvisAvatar", "Duix native library unavailable", t);
            }
        }
        nativeOk = ok;
        return ok;
    }

    public static boolean downloaded(@NonNull Context context,
                                     @NonNull AvatarCatalog.Avatar avatar) {
        try {
            return VirtualModelUtil.checkBaseConfig(context)
                    && VirtualModelUtil.checkModel(context, avatar.url);
        } catch (RuntimeException e) {
            return false;   // no external files dir (storage unavailable)
        }
    }

    /** What is still to download on this phone for {@code avatar}, in MB. */
    public static int remainingMb(@NonNull Context context,
                                  @NonNull AvatarCatalog.Avatar avatar) {
        int mb = 0;
        try {
            if (!VirtualModelUtil.checkBaseConfig(context)) mb += BASE_MB;
            if (!VirtualModelUtil.checkModel(context, avatar.url)) mb += avatar.sizeMb;
        } catch (RuntimeException e) {
            return BASE_MB + avatar.sizeMb;
        }
        return mb;
    }

    @NonNull
    public static AvatarCatalog.Avatar selected(@NonNull Context context) {
        return AvatarCatalog.byId(prefs(context).getString(KEY_SELECTED, null));
    }

    public static void select(@NonNull Context context, @NonNull AvatarCatalog.Avatar avatar) {
        prefs(context).edit().putString(KEY_SELECTED, avatar.id).apply();
    }

    public static boolean hidden(@NonNull Context context) {
        return prefs(context).getBoolean(KEY_HIDDEN, false);
    }

    public static void setHidden(@NonNull Context context, boolean hidden) {
        prefs(context).edit().putBoolean(KEY_HIDDEN, hidden).apply();
    }

    /** Remove one face's files. The shared base pack goes with the last face. */
    public static void deleteDownload(@NonNull Context context,
                                      @NonNull AvatarCatalog.Avatar avatar) {
        File duix = context.getExternalFilesDir("duix");
        if (duix == null) return;
        deleteTree(new File(duix, "model/" + avatar.folder()));
        deleteTree(new File(duix, "model/tmp/" + avatar.folder()));
        boolean anyLeft = false;
        for (AvatarCatalog.Avatar other : AvatarCatalog.ALL) {
            if (new File(duix, "model/" + other.folder()).exists()) anyLeft = true;
        }
        if (!anyLeft) deleteTree(duix);
    }

    // ── one download at a time, for the whole process ────────────────

    private interface DownloadListener {
        void onProgress(@NonNull String step, int percent);

        void onDone(@Nullable String error);
    }

    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    @Nullable private static DownloadListener downloadListener;
    @Nullable private static String downloadingId;
    private static String lastStep = "";
    private static int lastPercent = -1;

    /** The face being downloaded right now, or null. */
    @Nullable
    public static String downloadingId() {
        return downloadingId;
    }

    /**
     * Download what is missing, then start {@code avatar} on {@code renderer}.
     * Returns a handle to release. A download already running for this face
     * (the screen was closed and reopened) is joined rather than started
     * twice — both would write the same temporary file. Callers check
     * {@link #downloadingId()} before asking for a different face.
     */
    @NonNull
    public static Session load(@NonNull Context context, @NonNull DUIXRenderer renderer,
                               @NonNull AvatarCatalog.Avatar avatar,
                               @NonNull Listener listener) {
        Session session = new Session(context.getApplicationContext(), renderer, avatar,
                listener);
        session.begin();
        return session;
    }

    public static final class Session {
        private final Context app;
        private final DUIXRenderer renderer;
        private final AvatarCatalog.Avatar avatar;
        private final Listener listener;
        @Nullable private DUIX duix;
        private boolean released;

        Session(Context app, DUIXRenderer renderer, AvatarCatalog.Avatar avatar,
                Listener listener) {
            this.app = app;
            this.renderer = renderer;
            this.avatar = avatar;
            this.listener = listener;
        }

        @NonNull
        public AvatarCatalog.Avatar avatar() {
            return avatar;
        }

        void begin() {
            if (downloaded(app, avatar)) {
                start();
                return;
            }
            DownloadListener mine = new DownloadListener() {
                @Override
                public void onProgress(@NonNull String step, int percent) {
                    if (!released) listener.onAvatarProgress(step, percent);
                }

                @Override
                public void onDone(@Nullable String error) {
                    if (released) return;
                    if (error != null) listener.onAvatarFailed(error);
                    else start();
                }
            };
            if (downloadingId != null) {
                if (!downloadingId.equals(avatar.id)) {
                    listener.onAvatarFailed("Another face is still downloading.");
                    return;
                }
                downloadListener = mine;
                listener.onAvatarProgress(lastStep, Math.max(lastPercent, 0));
                return;
            }
            downloadListener = mine;
            downloadingId = avatar.id;
            downloadBase(app, avatar);
        }

        /**
         * Start Duix once the previous avatar's render thread is gone.
         *
         * <p>Duix's native side keeps one global model slot (task 0): a thread
         * that is still shutting down frees it on its way out, and a new
         * avatar started meanwhile crashes the whole app inside
         * {@code dhduix_free}. Swiping quickly between downloaded faces did
         * exactly that. A released Duix thread only exits after its model has
         * finished loading, so this can take a few seconds.
         */
        private void start() {
            listener.onAvatarProgress("Waking " + avatar.name + " up…", 100);
            STARTER.execute(() -> {
                long deadline = System.currentTimeMillis() + RENDER_EXIT_WAIT_MS;
                while (renderThreadAlive() && System.currentTimeMillis() < deadline) {
                    try {
                        Thread.sleep(100);
                    } catch (InterruptedException e) {
                        return;
                    }
                }
                if (renderThreadAlive()) {
                    MAIN.post(() -> {
                        if (!released) listener.onAvatarFailed(
                                "The previous face is still closing — swipe back in a moment.");
                    });
                    return;
                }
                MAIN.post(() -> {
                    if (!released) startNow();
                });
            });
        }

        private void startNow() {
            Listener l = listener;
            DUIX d = new DUIX(app, avatar.url, renderer, (event, msg, info) -> {
                if (Constant.CALLBACK_EVENT_INIT_READY.equals(event)) {
                    int w = 0;
                    int h = 0;
                    if (info instanceof ModelInfo) {
                        w = ((ModelInfo) info).getWidth();
                        h = ((ModelInfo) info).getHeight();
                    }
                    final int width = w;
                    final int height = h;
                    MAIN.post(() -> {
                        if (released || duix == null) return;
                        l.onAvatarReady(duix, width, height);
                    });
                } else if (Constant.CALLBACK_EVENT_INIT_ERROR.equals(event)) {
                    MAIN.post(() -> {
                        if (!released) l.onAvatarFailed("The avatar could not start: " + msg);
                    });
                } else if (Constant.CALLBACK_EVENT_AUDIO_PLAY_END.equals(event)) {
                    l.onAvatarPlayEnd();
                } else if (Constant.CALLBACK_EVENT_AUDIO_PLAY_ERROR.equals(event)) {
                    // Treat as finished: a silent avatar must not keep the mic shut.
                    l.onAvatarPlayEnd();
                }
            });
            duix = d;
            try {
                d.init();
            } catch (RuntimeException e) {
                l.onAvatarFailed("The avatar could not start.");
            }
        }

        public void release() {
            released = true;
            if (duix != null) {
                try {
                    duix.release();
                } catch (RuntimeException ignored) {
                    // already stopping
                }
                duix = null;
            }
        }
    }

    private static final String RENDER_THREAD_NAME = "DUIXRender-Thread";
    private static final long RENDER_EXIT_WAIT_MS = 30_000L;
    /** One start at a time: waits for the old render thread off the main thread. */
    private static final java.util.concurrent.ExecutorService STARTER =
            java.util.concurrent.Executors.newSingleThreadExecutor(r -> {
                Thread t = new Thread(r, "jarvis-avatar-start");
                t.setDaemon(true);
                return t;
            });

    /** A Duix render thread (named by the SDK) is still running. */
    static boolean renderThreadAlive() {
        for (Thread t : Thread.getAllStackTraces().keySet()) {
            if (RENDER_THREAD_NAME.equals(t.getName()) && t.isAlive()) return true;
        }
        return false;
    }

    private static void downloadBase(@NonNull Context app, @NonNull AvatarCatalog.Avatar avatar) {
        if (VirtualModelUtil.checkBaseConfig(app)) {
            downloadModel(app, avatar);
            return;
        }
        VirtualModelUtil.baseConfigDownload(app, BASE_URL,
                new Progress("Downloading voice engine", () -> downloadModel(app, avatar)));
    }

    private static void downloadModel(@NonNull Context app, @NonNull AvatarCatalog.Avatar avatar) {
        if (VirtualModelUtil.checkModel(app, avatar.url)) {
            finishDownload(null);
            return;
        }
        VirtualModelUtil.modelDownload(app, avatar.url,
                new Progress("Downloading " + avatar.name, () -> finishDownload(null)));
    }

    private static void finishDownload(@Nullable String error) {
        MAIN.post(() -> {
            downloadingId = null;
            lastPercent = -1;
            DownloadListener l = downloadListener;
            downloadListener = null;
            if (l != null) l.onDone(error);
        });
    }

    /** Throttles the SDK's per-kilobyte progress to one post per percent. */
    private static final class Progress implements VirtualModelUtil.ModelDownloadCallback {
        private final String label;
        private final Runnable next;
        private int lastDownload = -1;
        private int lastUnzip = -1;

        Progress(String label, Runnable next) {
            this.label = label;
            this.next = next;
        }

        @Override
        public void onDownloadProgress(String url, long current, long total) {
            int pct = total > 0 ? (int) (current * 100 / total) : 0;
            if (pct == lastDownload) return;
            lastDownload = pct;
            post(label + "…", pct);
        }

        @Override
        public void onUnzipProgress(String url, long current, long total) {
            int pct = total > 0 ? (int) (current * 100 / total) : 0;
            if (pct == lastUnzip) return;
            lastUnzip = pct;
            post("Unpacking…", pct);
        }

        @Override
        public void onDownloadComplete(String url, File dir) {
            MAIN.post(next);
        }

        @Override
        public void onDownloadFail(String url, int code, String msg) {
            finishDownload("The download failed — check the connection and try again.");
        }

        private static void post(String step, int pct) {
            MAIN.post(() -> {
                lastStep = step;
                lastPercent = pct;
                DownloadListener l = downloadListener;
                if (l != null) l.onProgress(step, pct);
            });
        }
    }

    private static SharedPreferences prefs(@NonNull Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static void deleteTree(@NonNull File file) {
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) deleteTree(child);
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
    }
}
