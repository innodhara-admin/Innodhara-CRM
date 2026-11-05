package com.yuvipep.app.feature.assistant.voice;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * The voice screen's faces. What must not drift: every face has its own
 * voice, every voice is one the server accepts, and each model unpacks into
 * the folder the app looks for.
 */
public class AvatarCatalogTest {

    /** Kokoro's American English voices — app/ai/tts.py VOICES on the backend. */
    private static final List<String> SERVER_VOICES = Arrays.asList(
            "af_heart", "af_bella", "af_sarah", "af_nicole", "af_kore", "af_aoede",
            "af_alloy", "af_jessica", "af_nova", "af_river", "af_sky",
            "am_michael", "am_fenrir", "am_puck", "am_adam", "am_echo", "am_eric",
            "am_liam", "am_onyx");

    @Test
    public void threeMenTwoWomenEachWithTheirOwnVoice() {
        // Five since 21 Sep 2026: Aixia was removed at the customer's request.
        assertEquals(5, AvatarCatalog.ALL.size());
        Set<String> ids = new HashSet<>();
        Set<String> voices = new HashSet<>();
        int women = 0;
        for (AvatarCatalog.Avatar a : AvatarCatalog.ALL) {
            assertTrue("duplicate id " + a.id, ids.add(a.id));
            assertTrue("shared voice " + a.voice, voices.add(a.voice));
            assertTrue("server has no voice " + a.voice, SERVER_VOICES.contains(a.voice));
            // Kokoro names say who speaks: af_ female, am_ male.
            assertEquals(a.name, a.female, a.voice.startsWith("af_"));
            assertTrue(a.url.startsWith("https://github.com/duixcom/Duix-Mobile/releases/"));
            assertTrue(a.sizeMb > 0);
            assertTrue(a.sample.contains(a.name));
            if (a.female) women++;
        }
        assertEquals(2, women);
    }

    @Test
    public void theSwipeOrderIsTheOneAskedFor() {
        StringBuilder order = new StringBuilder();
        for (AvatarCatalog.Avatar a : AvatarCatalog.ALL) order.append(a.name).append(' ');
        assertEquals("Ethan Sofia Oliver Lily Leo", order.toString().trim());
    }

    @Test
    public void onlyTheMaskedOnesAreCutOutsAndAixiaIsGone() {
        for (AvatarCatalog.Avatar a : AvatarCatalog.ALL) {
            assertTrue("Aixia was removed", !"aixia".equals(a.id));
        }
        // A phone that had chosen her gets the default face, not a crash.
        assertEquals(AvatarCatalog.DEFAULT_ID, AvatarCatalog.byId("aixia").id);
        assertTrue(AvatarCatalog.byId("ethan").cutout);
        assertTrue(!AvatarCatalog.byId("lily").cutout);
        assertEquals("Lily", AvatarCatalog.byId("lily").name);
    }

    @Test
    public void modelFoldersFollowDuixsRule() {
        assertEquals("Lily", AvatarCatalog.byId("lily").folder());
        assertEquals("bendi3_20240518", AvatarCatalog.byId("ethan").folder());
        assertEquals("x", AvatarCatalog.folderOf("https://h/a/x"));
    }

    @Test
    public void swipingWrapsRoundAndUnknownIdsFallBackToTheDefault() {
        AvatarCatalog.Avatar first = AvatarCatalog.ALL.get(0);
        AvatarCatalog.Avatar last = AvatarCatalog.ALL.get(AvatarCatalog.ALL.size() - 1);
        assertEquals(last, AvatarCatalog.step(first, -1));
        assertEquals(first, AvatarCatalog.step(last, 1));
        assertEquals(AvatarCatalog.ALL.get(1), AvatarCatalog.step(first, 1));
        assertEquals(AvatarCatalog.DEFAULT_ID, AvatarCatalog.byId("gone").id);
        assertEquals(AvatarCatalog.DEFAULT_ID, AvatarCatalog.byId(null).id);
    }
}
