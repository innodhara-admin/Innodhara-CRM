package com.yuvipep.app.core.net.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;
import java.util.Map;

/**
 * GET /proposals/{id} (and the echo of POST /edit). The pricing block is a
 * list of generic line-item maps — labels/units come from the org's pricing
 * table, never from app vocabulary.
 */
public class ProposalDetailDto {
    @SerializedName("id") public String id;
    @SerializedName("lead_id") public String leadId;
    @SerializedName("program_id") public String programId;
    @SerializedName("title") public String title;
    @SerializedName("status") public String status;
    @SerializedName("content_md") public String contentMd;
    @SerializedName("line_items") public List<Map<String, Object>> lineItems;
    @SerializedName("total_amount") public Double totalAmount;
    @SerializedName("currency") public String currency;
    @SerializedName("template_version") public Integer templateVersion;
    @SerializedName("pricing_version") public Integer pricingVersion;
    @SerializedName("sent_at") public String sentAt;
    @SerializedName("created_at") public String createdAt;
    @SerializedName("revisions") public List<Revision> revisions;
    /** "markdown" or "docx". A docx proposal was filled into the org's own
     *  Word document rather than rendered from a Markdown body. */
    @SerializedName("template_kind") public String templateKind;
    @SerializedName("filled") public List<Filled> filled;
    // Only present on the POST /edit echo.
    @SerializedName("edit_result") public Map<String, Object> editResult;

    /**
     * One placeholder in a document-template proposal (backend
     * {@code filled_json}, produced by {@code docx/fill.py::apply}).
     *
     * <p>{@code source} is the one field the salesperson must read:
     * {@code "system"} came from the org's records, {@code "ai"} was written
     * for this client and is worth checking, {@code "user"} means the
     * salesperson typed it themselves, {@code "default"} means they accepted
     * the template author's own suggestion word for word, and
     * {@code "unfilled"} is a place the model could not write from what was on
     * record — the document has a gap there, and nothing else on this screen
     * would say so.
     *
     * <p>The simple flow (backend {@code proposal_fill_service.filled_json})
     * produces {@code "ai"}, {@code "user"} and {@code "default"}; the complex
     * flow ({@code docx/fill.py::apply}) produces {@code "system"},
     * {@code "ai"} and {@code "unfilled"}.
     */
    public static class Filled {
        @SerializedName("key")    public String key;
        @SerializedName("kind")   public String kind;
        @SerializedName("source") public String source;
        @SerializedName("text")   public String text;
        @SerializedName("brief")  public String brief;
        @SerializedName("anchor") public String anchor;
        /**
         * Simple flow only, and absent on every older payload -- Gson leaves
         * both null, which is why adding them breaks nothing.
         *
         * <p>{@code computedBy} is {@code "python"} when the figure was
         * computed from the locked rate card rather than supplied by anyone,
         * and null otherwise. {@code citation} is the fact a model-written
         * value came from ({@code "client.name"}), or the turn in which the
         * person said it.
         */
        @SerializedName("computed_by") public String computedBy;
        @SerializedName("citation")    public String citation;
    }

    public static class Revision {
        @SerializedName("revision_no") public int revisionNo;
        @SerializedName("instruction") public String instruction;
        @SerializedName("total_amount") public Double totalAmount;
        @SerializedName("edited_at") public String editedAt;
    }
}
