package com.yuvipep.app.feature.home;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import com.yuvipep.app.core.net.dto.WaitingOnMeDto;

import org.junit.Test;

import java.util.HashMap;
import java.util.Map;

/**
 * "Blocked, waiting on Siva" reaches Siva (customer ask, 21 Sep 2026): the
 * Home card for the colleague, and the "Siva was told" line for the person
 * who pressed Blocked.
 */
public class WaitingOnYouTest {

    private static WaitingOnMeDto.Item item(String project, String lead, String school) {
        WaitingOnMeDto.Item i = new WaitingOnMeDto.Item();
        i.id = "t1";
        i.title = "Send the lab kit list";
        i.blockedReason = "waiting for inputs from Siva";
        i.waitingUserName = "Mithun Rao";
        i.projectId = project;
        i.projectName = project == null ? null : "Onboarding";
        i.leadId = lead;
        i.school = school;
        return i;
    }

    @Test
    public void theBodySaysWhatAndWhyAndForWhom() {
        assertEquals("Send the lab kit list — waiting for inputs from Siva · ABC School",
                WaitingOnYou.body(item("p1", "l1", "ABC School")));
    }

    @Test
    public void noClientNoTrailingDot() {
        assertEquals("Send the lab kit list — waiting for inputs from Siva",
                WaitingOnYou.body(item(null, null, null)));
    }

    @Test
    public void theProjectStandsInWhenThereIsNoClientName() {
        assertEquals("Send the lab kit list — waiting for inputs from Siva · Onboarding",
                WaitingOnYou.body(item("p1", null, null)));
    }

    @Test
    public void theTapGoesToTheProjectThenTheClient() {
        assertEquals(WaitingOnYou.Target.PROJECT, WaitingOnYou.target(item("p1", "l1", "ABC")));
        assertEquals(WaitingOnYou.Target.LEAD, WaitingOnYou.target(item(null, "l1", "ABC")));
        assertEquals(WaitingOnYou.Target.NONE, WaitingOnYou.target(item(null, null, null)));
    }

    @Test
    public void theBlockAnswerNamesWhoWasTold() {
        Map<String, Object> told = new HashMap<>();
        told.put("id", "u1");
        told.put("name", "Siva Kumar");
        Map<String, Object> response = new HashMap<>();
        response.put("ok", true);
        response.put("blocked_on", told);
        assertEquals("Siva Kumar", WaitingOnYou.blockedOnName(response));
    }

    @Test
    public void nobodyToldOrAnOlderServerGivesNull() {
        Map<String, Object> response = new HashMap<>();
        response.put("ok", true);
        response.put("blocked_on", null);
        assertNull(WaitingOnYou.blockedOnName(response));
        Map<String, Object> older = new HashMap<>();
        older.put("ok", true);
        assertNull(WaitingOnYou.blockedOnName(older));
        assertNull(WaitingOnYou.blockedOnName(null));
    }
}
