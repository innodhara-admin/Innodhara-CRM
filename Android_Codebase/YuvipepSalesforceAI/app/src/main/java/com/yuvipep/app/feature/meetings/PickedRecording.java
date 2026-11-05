package com.yuvipep.app.feature.meetings;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.media.MediaMetadataRetriever;
import android.net.Uri;
import android.provider.OpenableColumns;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.WorkerThread;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Locale;
import java.util.UUID;

/**
 * A recording file chosen from the phone instead of recorded here (customer
 * ask, 21 Sep 2026: "upload a recording from the Recording tab").
 *
 * <p>The system picker hands over a content URI, but {@link UploadMeetingWorker}
 * needs a real path it can retry from after a network drop, so the file is
 * copied into app storage first, keeping its extension: the server stores the
 * upload under its filename and decodes it with ffmpeg, which reads any of
 * these. The copy is deleted by the worker once the server has it, exactly as
 * a live recording is.
 */
public final class PickedRecording {

    /** The server's cap (`_MAX_AUDIO_BYTES` in app/api/meetings.py). */
    static final long MAX_BYTES = 200L * 1024 * 1024;

    /** What the picker offers. mp4 is the one video type asked for. */
    public static final String[] PICKER_TYPES = {"audio/*", "video/mp4"};

    private static final String[] EXTENSIONS = {"mp3", "m4a", "aac", "mp4", "wav", "ogg", "opus", "amr", "3gp"};

    @NonNull public final String path;
    @NonNull public final String displayName;
    @NonNull public final String mime;
    /** Whole seconds, or 0 when the length could not be read. */
    public final long seconds;

    PickedRecording(@NonNull String path, @NonNull String displayName,
                    @NonNull String mime, long seconds) {
        this.path = path;
        this.displayName = displayName;
        this.mime = mime;
        this.seconds = seconds;
    }

    /** Why a pick was refused, in words for the person. */
    public static final class Refused extends Exception {
        public Refused(@NonNull String message) {
            super(message);
        }
    }

    /**
     * The extension to store the copy under, or null if this is not a
     * recording we can send. The name wins; the type covers providers that
     * hand over a name without one (WhatsApp voice notes, some Drive files).
     */
    @Nullable
    static String extensionOf(@Nullable String displayName, @Nullable String mime) {
        if (displayName != null) {
            int dot = displayName.lastIndexOf('.');
            if (dot >= 0 && dot < displayName.length() - 1) {
                String ext = displayName.substring(dot + 1).toLowerCase(Locale.ROOT);
                for (String known : EXTENSIONS) {
                    if (known.equals(ext)) return ext;
                }
            }
        }
        if (mime == null) return null;
        switch (mime.toLowerCase(Locale.ROOT)) {
            case "audio/mpeg":
            case "audio/mp3":
                return "mp3";
            case "audio/mp4":
            case "audio/x-m4a":
            case "audio/m4a":
                return "m4a";
            case "audio/aac":
            case "audio/aacp":
                return "aac";
            case "video/mp4":
                return "mp4";
            case "audio/wav":
            case "audio/x-wav":
            case "audio/wave":
                return "wav";
            case "audio/ogg":
                return "ogg";
            case "audio/opus":
                return "opus";
            case "audio/amr":
                return "amr";
            case "audio/3gpp":
                return "3gp";
            default:
                return null;
        }
    }

    /** The Content-Type the upload is sent with. */
    @NonNull
    static String mimeFor(@NonNull String extension) {
        switch (extension) {
            case "mp3": return "audio/mpeg";
            case "aac": return "audio/aac";
            case "mp4": return "video/mp4";
            case "wav": return "audio/wav";
            case "ogg": return "audio/ogg";
            case "opus": return "audio/opus";
            case "amr": return "audio/amr";
            case "3gp": return "audio/3gpp";
            case "m4a":
            default:
                return "audio/mp4";
        }
    }

    /** -1 means the provider did not say; the server still enforces the cap. */
    static boolean fitsServerLimit(long bytes) {
        return bytes <= MAX_BYTES;
    }

    /** Whole seconds, or 0 for "unknown" (the worker then omits the field). */
    static long secondsOf(long millis) {
        if (millis <= 0) return 0;
        return Math.max(1, Math.round(millis / 1000.0));
    }

    /**
     * Check, copy and measure a picked file. Runs on a background thread:
     * copying a 100 MB file takes seconds.
     */
    @WorkerThread
    @NonNull
    public static PickedRecording copyIn(@NonNull Context context, @NonNull Uri uri)
            throws Refused {
        ContentResolver resolver = context.getContentResolver();
        String name = null;
        long size = -1;
        try (Cursor c = resolver.query(uri,
                new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE},
                null, null, null)) {
            if (c != null && c.moveToFirst()) {
                if (!c.isNull(0)) name = c.getString(0);
                if (!c.isNull(1)) size = c.getLong(1);
            }
        } catch (RuntimeException ignored) {
            // A provider that cannot answer: fall back to the type alone.
        }
        String ext = extensionOf(name, resolver.getType(uri));
        if (ext == null) {
            throw new Refused("That file is not a recording. Choose an mp3, m4a, aac, mp4 or wav file.");
        }
        if (!fitsServerLimit(size)) {
            throw new Refused("That file is over 200 MB, which is the most the server accepts.");
        }

        File dir = new File(context.getFilesDir(), "picked_recordings");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        File out = new File(dir, UUID.randomUUID() + "." + ext);
        long copied = 0;
        try (InputStream in = resolver.openInputStream(uri);
             OutputStream os = new FileOutputStream(out)) {
            if (in == null) throw new IOException("no stream");
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) {
                copied += n;
                if (copied > MAX_BYTES) {
                    throw new Refused("That file is over 200 MB, which is the most the server accepts.");
                }
                os.write(buf, 0, n);
            }
        } catch (Refused r) {
            //noinspection ResultOfMethodCallIgnored
            out.delete();
            throw r;
        } catch (IOException | SecurityException e) {
            //noinspection ResultOfMethodCallIgnored
            out.delete();
            throw new Refused("Could not read that file. Try copying it to the phone first.");
        }
        if (copied == 0) {
            //noinspection ResultOfMethodCallIgnored
            out.delete();
            throw new Refused("That file is empty.");
        }

        return new PickedRecording(out.getAbsolutePath(),
                name != null ? name : out.getName(), mimeFor(ext), readSeconds(out));
    }

    private static long readSeconds(@NonNull File file) {
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try {
            retriever.setDataSource(file.getAbsolutePath());
            String ms = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION);
            return ms == null ? 0 : secondsOf(Long.parseLong(ms));
        } catch (RuntimeException e) {
            // Raw ADTS .aac often has no duration header. Unknown, not wrong.
            return 0;
        } finally {
            try {
                retriever.release();
            } catch (IOException | RuntimeException ignored) {
                // Nothing to do.
            }
        }
    }
}
