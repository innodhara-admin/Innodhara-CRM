package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/**
 * GET /mous/{id} — a memorandum of understanding.
 *
 * <p><b>Deliberately not a {@link ProposalDetailDto}.</b> An MOU is signed
 * AFTER a proposal has been accepted, so one carried as a proposal would
 * arrive on an already-closed deal; the backend keeps them in separate tables
 * and the lead screen keeps them under separate keys, and this class is the
 * app's half of that.
 *
 * <p><b>There is no {@code totalAmount}, no {@code lineItems} and no
 * {@code currency}, and their absence is the point.</b> The backend's
 * {@code mou_documents} table has no such columns, so a screen that sums a
 * client's documents cannot pick a contract up by accident. A contract states
 * what it is worth inside itself, in the words the salesperson approved, and
 * {@link #filled} carries those.
 */
public class MouDto {
    @SerializedName("id") public String id;
    @SerializedName("lead_id") public String leadId;
    @SerializedName("program_id") public String programId;
    @SerializedName("title") public String title;
    /** "draft" or "sent". There is no "accepted": signing happens on paper. */
    @SerializedName("status") public String status;
    /** The projected plain text of the document that was built. */
    @SerializedName("content_md") public String contentMd;
    @SerializedName("template_id") public String templateId;
    @SerializedName("template_version") public Integer templateVersion;
    /** What went into it, for the "what went into this" card. */
    @SerializedName("filled") public List<Filled> filled;
    /**
     * Whether each file exists. The backend serves the bytes from
     * {@code /mous/{id}/download?format=}; it never sends a storage path,
     * because a storage key is not something this app could fetch.
     */
    @SerializedName("has_docx") public Boolean hasDocx;
    @SerializedName("has_pdf") public Boolean hasPdf;
    @SerializedName("sent_at") public String sentAt;
    @SerializedName("created_at") public String createdAt;
    /** Newest first. Revision 1 is the contract as it was first built. */
    @SerializedName("revisions") public List<Revision> revisions;

    /**
     * One placeholder the fill wrote into the contract.
     *
     * <p>The same eight keys the proposal card reads, because it is the same
     * record: renaming one turns a working card into a blank one, which is a
     * defect this project has already shipped once.
     *
     * <p>{@code source} is the field the salesperson must be able to trust.
     * {@code "ai"} was worked out from the client's records and is worth
     * checking; {@code "user"} means they typed it themselves;
     * {@code "default"} means they accepted the template author's own
     * suggestion word for word.
     */
    public static class Filled {
        @SerializedName("key") public String key;
        @SerializedName("kind") public String kind;
        @SerializedName("source") public String source;
        @SerializedName("text") public String text;
        @SerializedName("brief") public String brief;
        /** The row label of the cell the tag sat in — "First Instalment". */
        @SerializedName("anchor") public String anchor;
        @SerializedName("computed_by") public String computedBy;
        @SerializedName("citation") public String citation;
    }

    /** What the contract said before a correction replaced it. */
    public static class Revision {
        @SerializedName("revision_no") public Integer revisionNo;
        @SerializedName("instruction") public String instruction;
        @SerializedName("edited_at") public String editedAt;
    }
}
