package com.yuvipep.app.feature.mous;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.StringRes;

import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.MouDto;

/**
 * The decisions the contract rows and the "what went into this" card make,
 * kept out of the fragment so they can be tested.
 *
 * <p>This project's JVM suite is pure logic and there is no Robolectric, so
 * <b>anything left inside a fragment cannot be tested at all</b> — which is
 * exactly how E1's two defects survived a green suite. Moving the decisions
 * out is what makes them provable; nothing about the screen changes.
 *
 * <p>It lives in its own package rather than beside {@code
 * ProposalFilledLines} on purpose. An MOU is not a proposal (D-A): it is
 * signed after one is accepted, it has no commercial fields, and putting its
 * decisions in the proposals package is the first step towards someone
 * reusing a proposal's rule on a contract.
 */
public final class MouLines {

    private MouLines() {
    }

    /**
     * Does this contract have a record of what went into it?
     *
     * <p>Every MOU is built by filling the tags in a Word document, so unlike
     * a proposal there is no template kind to gate on — the only question is
     * whether the backend actually sent the provenance. It is asked at all
     * because a card rendered from an empty list is a heading over nothing,
     * and because gating this wrongly is precisely how the proposal card was
     * hidden for the whole of the simple flow.
     */
    public static boolean hasProvenance(@Nullable MouDto mou) {
        return mou != null && mou.filled != null && !mou.filled.isEmpty();
    }

    /**
     * What to tell the salesperson about where a value came from.
     *
     * <p><b>The fallback is the important part, and it is E1's defect.</b> It
     * has to be the most modest claim available rather than the most
     * flattering one: labelling an unrecognised source "From your records" is
     * the screen making a provenance claim on the backend's behalf that
     * nobody can check. That is how {@code "user"} and {@code "default"}
     * silently became "From your records" — telling a salesperson that a
     * figure they had typed themselves came out of the database.
     *
     * <p>A contract's fill produces {@code "ai"}, {@code "user"} and
     * {@code "default"}; all three are named here, so nothing real falls
     * through.
     */
    @StringRes
    public static int sourceLabel(@Nullable String source) {
        if ("ai".equals(source)) return R.string.proposal_filled_ai;
        if ("user".equals(source)) return R.string.proposal_filled_user;
        if ("default".equals(source)) return R.string.proposal_filled_default;
        if ("unfilled".equals(source)) return R.string.proposal_filled_unfilled;
        return R.string.proposal_filled_system;
    }

    /**
     * What to call one line of the provenance card.
     *
     * <p>The anchor carries the row label of the table cell the tag sat in —
     * "First Instalment", "Student Grades" — which is what the salesperson
     * will recognise from the document in front of them. The brief holds the
     * model's own reasoning and reads as "the salesperson said so" on every
     * row a person answered, so it is only a fallback.
     */
    @NonNull
    public static String heading(@Nullable MouDto.Filled entry) {
        if (entry == null) return "";
        if (notBlank(entry.anchor)) return entry.anchor.trim();
        if (notBlank(entry.brief)) return entry.brief.trim();
        return entry.key == null ? "" : entry.key;
    }

    /**
     * What to call a contract in the client screen's list.
     *
     * <p>A backend that sent no title leaves the row blank rather than
     * unlabelled, and a row a salesperson cannot name is a row they will not
     * tap.
     */
    @NonNull
    public static String rowTitle(@Nullable String title,
                                  @NonNull String fallback) {
        return notBlank(title) ? title.trim() : fallback;
    }

    /**
     * Is this contract with the client already?
     *
     * <p>Once it is sent they are holding it, and the backend refuses to
     * rewrite the file behind that — so the screen must not offer a
     * correction it would be refused. {@code sent_at} is believed as well as
     * the status: a send that recorded when it went and then failed to move
     * the status still means the client has it.
     */
    public static boolean isWithTheClient(@Nullable MouDto mou) {
        if (mou == null) return false;
        return "sent".equals(mou.status) || notBlank(mou.sentAt);
    }

    /**
     * Can the salesperson actually open and read this contract?
     *
     * <p><b>Asked of the .docx, not of the PDF, and that is the whole point.</b>
     * The backend leaves {@code pdf_path} null when LibreOffice fails to
     * convert — deliberately, because losing an approved contract over a
     * converter hiccup is worse than converting it late — and
     * {@code /mous/{id}/download?format=pdf} renders it on the way out. A
     * button gated on {@code has_pdf} would therefore be missing for exactly
     * the contracts whose conversion is the one that needs retrying.
     *
     * <p>Neither flag sent is read as "no", not as "probably fine". A button
     * that opens an error is worse than a button that is not there.
     */
    public static boolean canBeRead(@Nullable MouDto mou) {
        if (mou == null) return false;
        return Boolean.TRUE.equals(mou.hasDocx) || Boolean.TRUE.equals(mou.hasPdf);
    }

    /**
     * What the cached render of this contract is keyed on.
     *
     * <p>The number of revisions, so a correction is never served the previous
     * render from the file cache. A correction writes new files against the
     * same row (the MOU keeps its id), so the id alone is not enough to tell
     * two renders apart — the same mistake would show the salesperson the
     * wording they had just corrected and let them send it.
     */
    @NonNull
    public static String versionTag(@Nullable MouDto mou) {
        return String.valueOf(mou == null || mou.revisions == null
                ? 0 : mou.revisions.size());
    }

    private static boolean notBlank(@Nullable String value) {
        return value != null && !value.trim().isEmpty();
    }
}
