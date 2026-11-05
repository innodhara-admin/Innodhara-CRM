package com.yuvipep.app.feature.leads;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.List;

/**
 * The bulk-upload JSON file's own schema — a plain array of leads, each
 * optionally carrying its own contacts. Deliberately separate from
 * {@link com.yuvipep.app.core.net.dto.LeadRequests}, which is the backend's
 * wire format (snake_case in places): this is what a human hand-writes into
 * a file, mapped into the wire format per-entry by {@link BulkLeadImporter}.
 */
public final class BulkLeadImport {

    private BulkLeadImport() {
    }

    public static class Lead {
        public String name;
        public String city;
        public String source;
        public String website;
        public String notes;
        /**
         * Who should cold call this school — an agent's email or full name.
         * Omit it and the lead is yours, which is what the single-lead form
         * does when its picker is left alone.
         */
        public String owner;
        public List<Contact> contacts;
    }

    public static class Contact {
        public String name;
        public String title;
        public String email;
        public String phone;
        public boolean isPrimary;
    }

    /** Mirrors NewLeadSheet's own rule. Null means valid. */
    @Nullable
    public static String leadError(@NonNull Lead lead) {
        if (lead.name == null || lead.name.trim().length() < 2) {
            return "name too short";
        }
        return null;
    }

    /** Mirrors ContactSheet's own rule. Null means valid. */
    @Nullable
    public static String contactError(@NonNull Contact contact) {
        if (contact.name == null || contact.name.trim().isEmpty()) {
            return "name required";
        }
        return null;
    }
}
