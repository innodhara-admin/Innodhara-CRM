/**
 * Reset — the derivation behind the destructive screen. 06_DESIGN.md §5.7,
 * 07_BUILD_PLAN.md Task 24 Steps 1–3.
 *
 * Pure, and separated from `screens/Reset.tsx` for the reason `status.ts` and
 * `golive.ts` are: this is the one screen in the console where being wrong
 * destroys data, so what it claims has to be testable without a DOM.
 *
 * ## Two dry runs, not one — and this is a property of the endpoint
 *
 * `admin.py · reset_organisation` returns `counts` for **only the tables the
 * flags it was called with cover**, and computes `blocking_edges` **only** when
 * `wipe_catalogue and not wipe_transactional`. Those two facts pull in opposite
 * directions, so one preview call cannot answer both questions:
 *
 * | call | flags | answers |
 * |---|---|---|
 * | `PREVIEW_ALL` | all three | per-table counts for all 51 clearable tables — what each flag *would* clear, before the operator commits to one |
 * | `PREVIEW_CATALOGUE_ONLY` | catalogue alone | `blocking_edges`, which no other combination reports |
 *
 * Both are `dry_run: true` and neither writes. **The screen must say that the
 * counts come from a preview of all three flags**, or an operator reading a
 * count beside an unticked box would reasonably think it was about to be
 * cleared. It is stated on the screen, not here.
 *
 * The catalogue-only probe is made **always**, not only when that combination
 * is selected. D22's refusal is what the operator needs to see *before* they
 * choose it; a preview that only warns once the box is ticked has turned a
 * stated refusal into a surprise (Task 24 Step 2).
 *
 * ## The fourth bucket has no counts, and that is the honest answer
 *
 * `KEEP` is unreachable from `deletion_order`, so no reset response mentions
 * `organisations`, `org_settings`, `users` or `audit_log` at all. This module
 * renders the bucket with its tables and D16's reasons and **no numbers**,
 * rather than inventing them or hiding the bucket. The one real number the
 * console does hold — how many staff accounts survive — comes from
 * `GET /admin/users` and is passed in, so its provenance is visible.
 */
import { RESET_TAXONOMY } from "../api/vocabularies.generated";
import type { ResetPreview } from "../api/reads";

export type BucketName = keyof typeof RESET_TAXONOMY.buckets;

/** The three request fields, exactly as `ResetRequest` declares them. */
export type ResetFlags = {
  wipe_transactional: boolean;
  wipe_catalogue: boolean;
  wipe_org_config: boolean;
};

export const NO_FLAGS: ResetFlags = {
  wipe_transactional: false,
  wipe_catalogue: false,
  wipe_org_config: false,
};

export const ALL_FLAGS: ResetFlags = {
  wipe_transactional: true,
  wipe_catalogue: true,
  wipe_org_config: true,
};

export const CATALOGUE_ONLY: ResetFlags = {
  wipe_transactional: false,
  wipe_catalogue: true,
  wipe_org_config: false,
};

/**
 * `RESET_TAXONOMY.clearedBy` maps a bucket to `deletion_order`'s **parameter**
 * name (`transactional`), and the request field is that with a `wipe_` prefix
 * (`wipe_transactional`). The prefix is the one link in this chain that is
 * neither imported nor AST-read, so `reset.test.ts` asserts every value here is
 * a real field of the generated `ResetRequest` schema.
 */
export function flagFor(bucket: BucketName): keyof ResetFlags | null {
  const param = (RESET_TAXONOMY.clearedBy as Record<string, string>)[bucket];
  return param ? (`wipe_${param}` as keyof ResetFlags) : null;
}

/** Why each bucket is what it is — `app/core/reset_taxonomy.py`'s own reasons. */
export const BUCKET_NOTE: Record<BucketName, string> = {
  // Plain prose, no markdown: these strings are rendered as text, and a
  // backtick shows up as a backtick. Caught in a browser, where "`users`" was
  // on screen with its punctuation intact.
  KEEP:
    "Never removed, by any flag. No reset response mentions these tables at " +
    "all, so this console has no counts to show for them — the organisation " +
    "and its settings survive, the user accounts because the reset runs under " +
    "the account it would otherwise destroy, and the audit log because D13 " +
    "requires the reset to leave an audit row behind.",
  CONFIG:
    "Skills and approval rules. The reseed bundle exports both, so the reset " +
    "has to be able to clear them or a re-import collides.",
  REPLACE: "The catalogue — everything you sell and the templates around it.",
  WIPE: "Everything transactional.",
};

export const BUCKET_TITLE: Record<BucketName, string> = {
  KEEP: "Never touched",
  CONFIG: "Skills and approval rules",
  REPLACE: "The catalogue",
  WIPE: "Transactional data",
};

export type TableCount = {
  table: string;
  /** `null` where no reset response reports this table — the KEEP bucket. */
  count: number | null;
};

export type BucketView = {
  bucket: BucketName;
  title: string;
  note: string;
  /** The request field that clears it, or `null` for `KEEP`. */
  flag: keyof ResetFlags | null;
  /** Whether the operator has ticked that flag. `KEEP` is never selected. */
  selected: boolean;
  tables: TableCount[];
  /** Rows this bucket would clear, or `null` when nothing reports them. */
  total: number | null;
  /** Tables with at least one row — what the screen leads with. */
  nonEmpty: TableCount[];
};

const BUCKET_ORDER: BucketName[] = ["WIPE", "REPLACE", "CONFIG", "KEEP"];

/**
 * The four buckets, with the counts a **`PREVIEW_ALL` dry run** reported.
 *
 * `preview` is the response to the all-three-flags call, not to the operator's
 * selection. Passing the selection's own preview here would leave every
 * unticked bucket blank, which is exactly the information the operator needs in
 * order to decide.
 */
export function bucketsFor(
  preview: ResetPreview | null,
  flags: ResetFlags,
): BucketView[] {
  return BUCKET_ORDER.map((bucket) => {
    const flag = flagFor(bucket);
    const tables: TableCount[] = RESET_TAXONOMY.buckets[bucket].map((table) => ({
      table,
      // A table absent from `counts` is not zero — it is unreported. Only KEEP
      // is ever absent from a PREVIEW_ALL response, and it is absent by design.
      count: preview ? (preview.counts[table] ?? null) : null,
    }));
    const known = tables.filter((t) => t.count !== null);
    return {
      bucket,
      title: BUCKET_TITLE[bucket],
      note: BUCKET_NOTE[bucket],
      flag,
      selected: flag ? flags[flag] : false,
      tables,
      total:
        known.length === 0 ? null : known.reduce((n, t) => n + (t.count ?? 0), 0),
      nonEmpty: tables.filter((t) => (t.count ?? 0) > 0),
    };
  });
}

/**
 * Rows the **selected** flags would remove, summed from the `PREVIEW_ALL`
 * counts rather than from `preview.total` — which is the total for all three
 * flags and would overstate any narrower selection.
 */
export function selectedTotal(
  preview: ResetPreview | null,
  flags: ResetFlags,
): number | null {
  if (!preview) return null;
  return bucketsFor(preview, flags)
    .filter((b) => b.selected)
    .reduce((n, b) => n + (b.total ?? 0), 0);
}

export const anyFlagSet = (flags: ResetFlags): boolean =>
  Object.values(flags).some(Boolean);

/**
 * Why the apply button is disabled, or `null` when it is not.
 *
 * **The blocking-edge case is the one that matters.** It reproduces the
 * server's own condition — `wipe_catalogue && !wipe_transactional` with edges
 * present — so the screen refuses before sending rather than surfacing a 422
 * afterwards. It does **not** replace the server's check: the request is still
 * sent when this returns null, and a 422 is still rendered verbatim if the data
 * moved underneath the preview.
 */
export function blockedReason(opts: {
  flags: ResetFlags;
  blockingEdges: ResetPreview["blocking_edges"];
  typedName: string;
  orgName: string;
}): string | null {
  const { flags, blockingEdges, typedName, orgName } = opts;
  if (!anyFlagSet(flags)) {
    return "Choose at least one thing to clear.";
  }
  if (flags.wipe_catalogue && !flags.wipe_transactional && blockingEdges.length > 0) {
    return (
      "Clearing the catalogue on its own would orphan rows that still reference " +
      "it. Tick transactional data as well, or clear those rows first."
    );
  }
  if (typedName.trim() !== orgName) {
    return `Type the organisation's name exactly — ${orgName} — to confirm.`;
  }
  return null;
}

/**
 * `blocking_edges` is reported only by the catalogue-only dry run, so a
 * selection that also wipes transactional data must not render them as a
 * warning about itself — with both flags set the children are deleted first
 * (WIPE precedes REPLACE in `deletion_order`) and nothing can be orphaned.
 */
export function edgesApplyTo(flags: ResetFlags): boolean {
  return flags.wipe_catalogue && !flags.wipe_transactional;
}
