package com.yuvipep.app.feature.meetings;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Customer ask, 21 Sep 2026: upload a recording file from the recorder screen. */
public class PickedRecordingTest {

    @Test
    public void theCommonFormatsAreAccepted() {
        assertEquals("mp3", PickedRecording.extensionOf("visit.mp3", "audio/mpeg"));
        assertEquals("m4a", PickedRecording.extensionOf("visit.m4a", "audio/mp4"));
        assertEquals("aac", PickedRecording.extensionOf("visit.aac", "audio/aac"));
        assertEquals("mp4", PickedRecording.extensionOf("visit.mp4", "video/mp4"));
        assertEquals("wav", PickedRecording.extensionOf("visit.wav", "audio/x-wav"));
    }

    @Test
    public void theNameWinsAndCaseDoesNotMatter() {
        assertEquals("mp3", PickedRecording.extensionOf("VISIT.MP3", null));
    }

    @Test
    public void aNamelessFileFallsBackToItsType() {
        // Some providers (WhatsApp, Drive) hand over a name with no extension.
        assertEquals("m4a", PickedRecording.extensionOf("AUD-20260921", "audio/mp4"));
        assertEquals("mp3", PickedRecording.extensionOf(null, "audio/mpeg"));
        assertEquals("wav", PickedRecording.extensionOf(null, "audio/wav"));
        assertEquals("ogg", PickedRecording.extensionOf(null, "audio/ogg"));
    }

    @Test
    public void somethingThatIsNotARecordingIsRefused() {
        assertNull(PickedRecording.extensionOf("notes.pdf", "application/pdf"));
        assertNull(PickedRecording.extensionOf(null, null));
        assertNull(PickedRecording.extensionOf("clip.mkv", "video/x-matroska"));
    }

    @Test
    public void theUploadCarriesTheRealType() {
        assertEquals("audio/mpeg", PickedRecording.mimeFor("mp3"));
        assertEquals("audio/mp4", PickedRecording.mimeFor("m4a"));
        assertEquals("audio/aac", PickedRecording.mimeFor("aac"));
        assertEquals("video/mp4", PickedRecording.mimeFor("mp4"));
        assertEquals("audio/wav", PickedRecording.mimeFor("wav"));
    }

    @Test
    public void theServerLimitIsCheckedBeforeCopying() {
        assertTrue(PickedRecording.fitsServerLimit(200L * 1024 * 1024));
        assertFalse(PickedRecording.fitsServerLimit(200L * 1024 * 1024 + 1));
        // Unknown size (-1): let it through, the server still enforces the cap.
        assertTrue(PickedRecording.fitsServerLimit(-1));
    }

    @Test
    public void durationRoundsToWholeSeconds() {
        assertEquals(125, PickedRecording.secondsOf(125_400));
        assertEquals(1, PickedRecording.secondsOf(300));
    }

    @Test
    public void anUnreadableLengthIsUnknownNotOneSecond() {
        // The server only displays duration_seconds and accepts it missing;
        // 0 tells the worker to leave the field out rather than invent a length.
        assertEquals(0, PickedRecording.secondsOf(-1));
        assertEquals(0, PickedRecording.secondsOf(0));
    }
}
