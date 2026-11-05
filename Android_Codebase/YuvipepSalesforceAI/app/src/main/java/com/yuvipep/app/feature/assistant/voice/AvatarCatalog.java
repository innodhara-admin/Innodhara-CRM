package com.yuvipep.app.feature.assistant.voice;

import androidx.annotation.DrawableRes;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.R;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * The faces Jarvis can wear in voice mode, each with its own server voice.
 *
 * <p>All six are public Duix Mobile models (github.com/duixcom/Duix-Mobile
 * releases). Two kinds:
 * <ul>
 *   <li><b>Cut-out</b> — the model ships a transparency mask per frame, so
 *   only the person is drawn, standing on the voice screen's own backdrop.</li>
 *   <li><b>Video</b> — no mask: the whole studio shot is the picture, so it is
 *   shown as a rounded "video call" window. These carry Duix's watermark in
 *   the video itself.</li>
 * </ul>
 * Voices are Kokoro's American English set, which the backend accepts in the
 * session's start message (see {@code app/ai/tts.py} VOICES).
 */
public final class AvatarCatalog {

    public static final class Avatar {
        @NonNull public final String id;
        @NonNull public final String name;
        public final boolean female;
        /** Model zip; Duix unpacks it into a folder named after the zip. */
        @NonNull public final String url;
        /** Download size of the model alone, in MB (the base pack is extra, once). */
        public final int sizeMb;
        /** Kokoro voice the server speaks with for this face. */
        @NonNull public final String voice;
        /** How the voice sounds, for the picker. */
        @NonNull public final String voiceLabel;
        /** Transparent background (true) or a full video frame (false). */
        public final boolean cutout;
        @DrawableRes public final int preview;
        /** Said in this avatar's voice when someone lands on a face not yet downloaded. */
        @NonNull public final String sample;

        Avatar(@NonNull String id, @NonNull String name, boolean female, @NonNull String url,
               int sizeMb, @NonNull String voice, @NonNull String voiceLabel, boolean cutout,
               @DrawableRes int preview) {
            this.id = id;
            this.name = name;
            this.female = female;
            this.url = url;
            this.sizeMb = sizeMb;
            this.voice = voice;
            this.voiceLabel = voiceLabel;
            this.cutout = cutout;
            this.preview = preview;
            this.sample = "Hi, I'm " + name + ". Download me, and I'll be your Jarvis.";
        }

        /** The folder Duix unpacks the model into: the zip's own name. */
        @NonNull
        public String folder() {
            return folderOf(url);
        }
    }

    private static final String V1 = "https://github.com/duixcom/Duix-Mobile/releases/download/v1.0.0/";
    private static final String V2 = "https://github.com/duixcom/Duix-Mobile/releases/download/v2.0.1/";

    // Measured from the release assets on 2026-09-17. The order is the
    // swipe order on the voice screen.
    public static final List<Avatar> ALL = Collections.unmodifiableList(Arrays.asList(
            new Avatar("ethan", "Ethan", false, V1 + "bendi3_20240518.zip", 178,
                    "am_michael", "Steady, deep voice", true, R.drawable.avatar_ethan),
            new Avatar("sofia", "Sofia", true, V2 + "Sofia.zip", 30,
                    "af_sarah", "Calm, clear voice", false, R.drawable.avatar_sofia),
            new Avatar("oliver", "Oliver", false, V2 + "Oliver.zip", 30,
                    "am_fenrir", "Confident voice", false, R.drawable.avatar_oliver),
            new Avatar("lily", "Lily", true, V2 + "Lily.zip", 34,
                    "af_bella", "Bright, lively voice", false, R.drawable.avatar_lily),
            new Avatar("leo", "Leo", false, V2 + "Leo.zip", 26,
                    "am_puck", "Friendly, upbeat voice", false, R.drawable.avatar_leo)));
    // Aixia was the sixth face until 21 Sep 2026. Removed at the customer's
    // request (her dress cannot be changed and the model is not configurable);
    // a phone that had chosen her falls back to the default below.

    /** Who greets someone who has never chosen. */
    public static final String DEFAULT_ID = "lily";

    private AvatarCatalog() {
    }

    @NonNull
    public static Avatar byId(@Nullable String id) {
        for (Avatar a : ALL) {
            if (a.id.equals(id)) return a;
        }
        return ALL.get(indexOf(DEFAULT_ID));
    }

    public static int indexOf(@Nullable String id) {
        for (int i = 0; i < ALL.size(); i++) {
            if (ALL.get(i).id.equals(id)) return i;
        }
        return 0;
    }

    /** The face {@code step} places away (±1), wrapping round. */
    @NonNull
    public static Avatar step(@NonNull Avatar from, int step) {
        int n = ALL.size();
        int i = ((indexOf(from.id) + step) % n + n) % n;
        return ALL.get(i);
    }

    /** Duix's rule: the zip's file name without ".zip". */
    @NonNull
    static String folderOf(@NonNull String url) {
        String name = url.substring(url.lastIndexOf('/') + 1);
        return name.endsWith(".zip") ? name.substring(0, name.length() - 4) : name;
    }
}
