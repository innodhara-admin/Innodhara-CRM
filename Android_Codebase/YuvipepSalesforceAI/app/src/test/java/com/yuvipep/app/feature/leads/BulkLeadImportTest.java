package com.yuvipep.app.feature.leads;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;

import org.junit.Test;

import java.lang.reflect.Type;
import java.util.List;

/**
 * The bulk-upload JSON schema (leads list "Bulk upload leads" button): a top
 * level array of leads, each optionally carrying its own contacts array.
 * Field names are camelCase and parsed as-is (NetModule's Gson has no
 * naming policy), independent of LeadRequests' wire format.
 */
public class BulkLeadImportTest {

    private static final Gson GSON = new Gson();
    private static final Type LIST_TYPE =
            new TypeToken<List<BulkLeadImport.Lead>>() { }.getType();

    @Test
    public void parsesALeadWithAllFieldsAndOneContact() {
        String json = "[{"
                + "\"name\":\"Acme Textiles\","
                + "\"city\":\"Coimbatore\","
                + "\"source\":\"referral\","
                + "\"website\":\"https://acme.example\","
                + "\"notes\":\"Interested in bulk order\","
                + "\"contacts\":[{"
                + "  \"name\":\"Priya Shah\","
                + "  \"title\":\"Procurement Head\","
                + "  \"email\":\"priya@acme.example\","
                + "  \"phone\":\"+91 98765 43210\","
                + "  \"isPrimary\":true"
                + "}]"
                + "}]";

        List<BulkLeadImport.Lead> leads = GSON.fromJson(json, LIST_TYPE);

        assertEquals(1, leads.size());
        BulkLeadImport.Lead lead = leads.get(0);
        assertEquals("Acme Textiles", lead.name);
        assertEquals("Coimbatore", lead.city);
        assertEquals("referral", lead.source);
        assertEquals("https://acme.example", lead.website);
        assertEquals("Interested in bulk order", lead.notes);
        assertEquals(1, lead.contacts.size());
        BulkLeadImport.Contact contact = lead.contacts.get(0);
        assertEquals("Priya Shah", contact.name);
        assertEquals("Procurement Head", contact.title);
        assertEquals("priya@acme.example", contact.email);
        assertEquals("+91 98765 43210", contact.phone);
        assertTrue(contact.isPrimary);
    }

    @Test
    public void aLeadWithOnlyANameHasNullOptionalsAndNoContacts() {
        List<BulkLeadImport.Lead> leads =
                GSON.fromJson("[{\"name\":\"Bare Corp\"}]", LIST_TYPE);

        BulkLeadImport.Lead lead = leads.get(0);
        assertEquals("Bare Corp", lead.name);
        assertNull(lead.city);
        assertNull(lead.source);
        assertNull(lead.website);
        assertNull(lead.notes);
        assertNull(lead.contacts);
    }

    @Test
    public void aContactDefaultsIsPrimaryToFalseWhenAbsent() {
        List<BulkLeadImport.Lead> leads = GSON.fromJson(
                "[{\"name\":\"Bare Corp\",\"contacts\":[{\"name\":\"Bob\"}]}]",
                LIST_TYPE);

        assertEquals(false, leads.get(0).contacts.get(0).isPrimary);
    }

    // ── leadError: mirrors NewLeadSheet's own rule ──────────────────────────

    @Test
    public void aLeadNameUnderTwoCharsIsRejected() {
        BulkLeadImport.Lead lead = new BulkLeadImport.Lead();
        lead.name = "A";
        assertNotNull(BulkLeadImport.leadError(lead));
    }

    @Test
    public void aMissingLeadNameIsRejected() {
        BulkLeadImport.Lead lead = new BulkLeadImport.Lead();
        assertNotNull(BulkLeadImport.leadError(lead));
    }

    @Test
    public void aBlankLeadNameIsRejected() {
        BulkLeadImport.Lead lead = new BulkLeadImport.Lead();
        lead.name = "   ";
        assertNotNull(BulkLeadImport.leadError(lead));
    }

    @Test
    public void aValidLeadNameIsAccepted() {
        BulkLeadImport.Lead lead = new BulkLeadImport.Lead();
        lead.name = "Ok";
        assertNull(BulkLeadImport.leadError(lead));
    }

    // ── contactError: mirrors ContactSheet's own rule ───────────────────────

    @Test
    public void aMissingContactNameIsRejected() {
        BulkLeadImport.Contact contact = new BulkLeadImport.Contact();
        assertNotNull(BulkLeadImport.contactError(contact));
    }

    @Test
    public void aBlankContactNameIsRejected() {
        BulkLeadImport.Contact contact = new BulkLeadImport.Contact();
        contact.name = "   ";
        assertNotNull(BulkLeadImport.contactError(contact));
    }

    @Test
    public void aSingleCharacterContactNameIsAccepted() {
        // ContactSheet only requires non-empty, unlike the 2-char lead rule.
        BulkLeadImport.Contact contact = new BulkLeadImport.Contact();
        contact.name = "B";
        assertNull(BulkLeadImport.contactError(contact));
    }
}
