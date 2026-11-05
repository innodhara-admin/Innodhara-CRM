package com.yuvipep.app.feature.assistant;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * How a tool's result reads on a card. The shape here is the one a customer
 * complained about on 21 Sep 2026 ("Can we improve the readability?"): a
 * client with two contacts and a "false" flag.
 */
public class PrettyTest {

    private static Map<String, Object> contact(String name, String title) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("name", name);
        out.put("title", title);
        return out;
    }

    private static Map<String, Object> client() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", "dc4bd23d53394d5a84eececab84639cb");
        out.put("name", "SJBC Tumkur");
        out.put("state", "open");
        out.put("important", false);
        out.put("city", "Tumkur");
        out.put("open_action_items", 4.0);
        out.put("contacts", Arrays.asList(
                contact("Principal", "Principal"),
                contact("Other heads of institutions", "Head Of Institution")));
        return out;
    }

    @Test
    public void aFlagThatIsFalseIsNotWorthALine() {
        String out = Pretty.value(client());
        assertFalse(out, out.contains("false"));
        assertFalse(out, out.contains("Important"));
    }

    @Test
    public void aFlagThatIsTrueIsJustItsName() {
        Map<String, Object> lead = new LinkedHashMap<>();
        lead.put("name", "SJBC Tumkur");
        lead.put("important", true);
        assertEquals("Name: SJBC Tumkur\nImportant", Pretty.value(lead));
    }

    @Test
    public void contactsAreAPersonPerBulletUnderTheirHeading() {
        String out = Pretty.value(client());
        assertEquals("Name: SJBC Tumkur\n"
                + "State: open\n"
                + "City: Tumkur\n"
                + "Open action items: 4\n"
                + "Contacts:\n"
                + "  • Name: Principal\n"
                + "  Title: Principal\n"
                + "  • Name: Other heads of institutions\n"
                + "  Title: Head Of Institution", out);
    }

    @Test
    public void idsAreStillDroppedAndWholeNumbersStayWhole() {
        String out = Pretty.value(client());
        assertFalse(out, out.contains("dc4bd23d"));
        assertTrue(out, out.contains("Open action items: 4"));
    }

    @Test
    public void aLongResultIsCutWithAnEllipsis() {
        Map<String, Object> many = new LinkedHashMap<>();
        for (int i = 0; i < 40; i++) many.put("field" + i, "value " + i);
        String out = Pretty.value(many);
        assertTrue(out, out.endsWith("…"));
        assertEquals(19, out.split("\n").length);
    }
}
