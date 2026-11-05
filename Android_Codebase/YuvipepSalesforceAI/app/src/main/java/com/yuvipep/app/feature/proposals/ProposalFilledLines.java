package com.yuvipep.app.feature.proposals;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.StringRes;

import com.yuvipep.app.R;
import com.yuvipep.app.core.net.dto.ProposalDetailDto;

/**
 * The three decisions the "What went into this proposal" card makes, kept out
 * of the fragment so they can be tested.
 *
 * <p>They lived inside {@code ProposalDetailFragment} and two of them were
 * wrong for the whole of the simple flow -- the card was hidden entirely, and
 * a value the salesperson had typed was labelled "From your records". Neither
 * could be caught by a test, because this project's JVM suite is pure logic
 * and a fragment needs Robolectric. Moving the decisions out is what makes
 * them provable; nothing else about the screen changes.
 */
public final class ProposalFilledLines {

    private ProposalFilledLines() {
    }

    /**
     * Does this proposal have a document behind it, and therefore a record of
     * what went into it?
     *
     * <p>Both flows do. {@code "docx"} is the complex one, where an
     * administrator marked the placeholders up in the console;
     * {@code "docx_simple"} is the one where the template author wrote the
     * tags into the Word file and the assistant filled them with the
     * salesperson. Gating on {@code "docx"} alone hid this card for every
     * proposal of the second kind.
     */
    public static boolean isDocumentProposal(@Nullable String templateKind) {
        return "docx".equals(templateKind) || "docx_simple".equals(templateKind);
    }

    /**
     * What to tell the salesperson about where a value came from.
     *
     * <p>The fallback is the important part. It has to be the most modest
     * claim available rather than the most flattering one: labelling an
     * unrecognised source "From your records" is the screen making a
     * provenance claim on the backend's behalf that nobody can check, which is
     * how {@code "user"} and {@code "default"} silently became "From your
     * records" the moment the simple flow started sending them.
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
     * What to call one line.
     *
     * <p>In the complex flow the brief is what a human asked the model for and
     * is the best name there is. In the simple flow there is no brief: the
     * anchor carries the row label of the table cell the tag sits in --
     * "Laptops", "Number of Students" -- which is what the salesperson will
     * recognise, while the brief holds the model's reasoning and would read as
     * "the salesperson said so" on every row.
     */
    @NonNull
    public static String heading(@Nullable String templateKind,
                                 @NonNull ProposalDetailDto.Filled entry) {
        if ("docx_simple".equals(templateKind)
                && entry.anchor != null && !entry.anchor.trim().isEmpty()) {
            return entry.anchor.trim();
        }
        if (entry.brief != null && !entry.brief.trim().isEmpty()) {
            return entry.brief.trim();
        }
        return entry.key == null ? "" : entry.key;
    }
}
