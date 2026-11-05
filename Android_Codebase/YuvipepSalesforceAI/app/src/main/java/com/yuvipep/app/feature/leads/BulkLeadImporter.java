package com.yuvipep.app.feature.leads;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.yuvipep.app.core.net.ApiError;
import com.yuvipep.app.core.net.dto.LeadRequests;
import com.yuvipep.app.core.net.dto.OrgUserDto;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Drives a parsed bulk-upload file through the same create-lead /
 * add-contact endpoints the manual forms use (LeadsRepository#create,
 * #addContact) — one lead, and then its contacts, at a time. A failure
 * anywhere never rolls back what already succeeded; it is only recorded,
 * so the batch always runs to completion.
 */
public class BulkLeadImporter {

    public static final class Failure {
        @NonNull public final String label;
        @NonNull public final String reason;

        Failure(@NonNull String label, @NonNull String reason) {
            this.label = label;
            this.reason = reason;
        }
    }

    public static final class Outcome {
        public final int created;
        @NonNull public final List<Failure> failures;

        Outcome(int created, @NonNull List<Failure> failures) {
            this.created = created;
            this.failures = failures;
        }
    }

    public interface Listener {
        void onProgress(int done, int total);

        void onFinished(@NonNull Outcome outcome);
    }

    /** Thrown for a row naming an owner we cannot pin to exactly one agent. */
    private static final class UnknownOwner extends RuntimeException {
        UnknownOwner(String message) {
            super(message);
        }
    }

    private final LeadsRepository repository;
    private final List<BulkLeadImport.Lead> leads;
    private final List<OrgUserDto> owners;
    private final Listener listener;
    private final List<Failure> failures = new ArrayList<>();

    private int index;
    private int created;

    /**
     * @param owners the org's assignable sales agents, used to turn each row's
     *               `owner` string into an id. May be empty — then any row
     *               that names an owner fails with a clear reason, rather than
     *               silently landing on the importer instead.
     */
    public BulkLeadImporter(@NonNull LeadsRepository repository,
                            @NonNull List<BulkLeadImport.Lead> leads,
                            @NonNull List<OrgUserDto> owners,
                            @NonNull Listener listener) {
        this.repository = repository;
        this.leads = leads;
        this.owners = owners;
        this.listener = listener;
    }

    public void start() {
        index = 0;
        created = 0;
        failures.clear();
        processNext();
    }

    private void processNext() {
        if (index >= leads.size()) {
            listener.onFinished(new Outcome(created, failures));
            return;
        }
        BulkLeadImport.Lead lead = leads.get(index);
        listener.onProgress(index, leads.size());
        String label = displayName(lead);

        String error = BulkLeadImport.leadError(lead);
        if (error != null) {
            failures.add(new Failure(label, error));
            advance();
            return;
        }

        LeadRequests.Create body;
        try {
            body = toCreateBody(lead);
        } catch (UnknownOwner e) {
            // A mistyped owner must not quietly become "assigned to me": the
            // named agent would never be told, and only the owner can take
            // the lead out of cold calling.
            failures.add(new Failure(label, e.getMessage()));
            advance();
            return;
        }

        repository.create(body, result -> {
            if (result.isSuccess() && result.data != null) {
                created++;
                importContacts(label, result.data.id, lead.contacts, 0);
            } else {
                failures.add(new Failure(label, message(result.error)));
                advance();
            }
        });
    }

    private void importContacts(@NonNull String leadLabel, @NonNull String leadId,
                                @Nullable List<BulkLeadImport.Contact> contacts,
                                int contactIndex) {
        if (contacts == null || contactIndex >= contacts.size()) {
            advance();
            return;
        }
        BulkLeadImport.Contact contact = contacts.get(contactIndex);
        String error = BulkLeadImport.contactError(contact);
        if (error != null) {
            failures.add(new Failure(contactLabel(leadLabel, contact), error));
            importContacts(leadLabel, leadId, contacts, contactIndex + 1);
            return;
        }
        repository.addContact(leadId, toContactBody(contact), result -> {
            if (result.isError() && result.error != null) {
                failures.add(new Failure(contactLabel(leadLabel, contact),
                        message(result.error)));
            }
            importContacts(leadLabel, leadId, contacts, contactIndex + 1);
        });
    }

    private void advance() {
        index++;
        processNext();
    }

    @NonNull
    private LeadRequests.Create toCreateBody(@NonNull BulkLeadImport.Lead lead) {
        LeadRequests.Create body = new LeadRequests.Create();
        body.name = lead.name.trim();
        body.city = blankToNull(lead.city);
        body.source = blankToNull(lead.source);
        body.website = blankToNull(lead.website);
        body.notes = blankToNull(lead.notes);
        body.ownerId = resolveOwner(blankToNull(lead.owner));
        return body;
    }

    /**
     * Turn a row's `owner` into an agent id: email first, then full name,
     * both case-insensitive and exact.
     *
     * No fuzzy matching on purpose. A near-miss that picks the wrong Priya is
     * worse than a row that fails and says so, because nothing downstream
     * would ever reveal the mistake.
     *
     * @return null when the row named nobody — the backend then assigns the
     *         creator, exactly as it always has.
     */
    @Nullable
    private String resolveOwner(@Nullable String owner) {
        if (owner == null) return null;
        String needle = owner.toLowerCase(Locale.ROOT);

        for (OrgUserDto user : owners) {
            if (user.email != null && user.email.toLowerCase(Locale.ROOT).equals(needle)) {
                return user.id;
            }
        }

        String matchedId = null;
        for (OrgUserDto user : owners) {
            if (user.name != null && user.name.toLowerCase(Locale.ROOT).equals(needle)) {
                if (matchedId != null) {
                    throw new UnknownOwner("owner \"" + owner
                            + "\" matches more than one agent — use their email");
                }
                matchedId = user.id;
            }
        }
        if (matchedId != null) return matchedId;
        throw new UnknownOwner("owner \"" + owner + "\" is not a sales agent here");
    }

    @NonNull
    private static LeadRequests.Contact toContactBody(@NonNull BulkLeadImport.Contact contact) {
        LeadRequests.Contact body = new LeadRequests.Contact();
        body.name = contact.name.trim();
        body.title = blankToNull(contact.title);
        body.email = blankToNull(contact.email);
        body.phone = blankToNull(contact.phone);
        body.isPrimary = contact.isPrimary;
        return body;
    }

    @NonNull
    private static String displayName(@NonNull BulkLeadImport.Lead lead) {
        return lead.name == null || lead.name.trim().isEmpty()
                ? "(unnamed lead)" : lead.name.trim();
    }

    @NonNull
    private static String contactLabel(@NonNull String leadLabel,
                                       @NonNull BulkLeadImport.Contact contact) {
        String name = contact.name == null || contact.name.trim().isEmpty()
                ? "(unnamed)" : contact.name.trim();
        return leadLabel + " — contact \"" + name + "\"";
    }

    @NonNull
    private static String message(@Nullable ApiError error) {
        return error != null ? error.message : "Something went wrong";
    }

    @Nullable
    private static String blankToNull(@Nullable String value) {
        if (value == null) return null;
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
