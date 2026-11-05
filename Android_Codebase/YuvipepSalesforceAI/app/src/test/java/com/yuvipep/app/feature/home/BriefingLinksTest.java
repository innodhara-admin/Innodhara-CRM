package com.yuvipep.app.feature.home;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

/**
 * The briefing names each task's client as a link, yuvipep://lead/&lt;id&gt;
 * (customer ask, 21 Sep 2026). Only that shape opens a lead in the app.
 */
public class BriefingLinksTest {

    @Test
    public void aLeadLinkGivesItsId() {
        assertEquals("3f2a9c0d1e", BriefingLinks.leadIdOf("yuvipep://lead/3f2a9c0d1e"));
    }

    @Test
    public void anythingElseIsNotALead() {
        assertNull(BriefingLinks.leadIdOf("https://example.com/lead/3f2a"));
        assertNull(BriefingLinks.leadIdOf("yuvipep://project/3f2a"));
        assertNull(BriefingLinks.leadIdOf("yuvipep://lead/"));
        assertNull(BriefingLinks.leadIdOf("yuvipep://lead/abc/extra"));
        assertNull(BriefingLinks.leadIdOf(null));
    }
}
