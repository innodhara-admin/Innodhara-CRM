/**
 * The fill plan, and the six edits the editor can make to it.
 *
 * A plan addresses positions inside an uploaded document that is never
 * rewritten: generation is `source.docx + plan + values -> a new file`. That is
 * what makes a positional path such as `body[7]` safe to store, and it is also
 * why every function here is pure — the plan is the whole of what the editor
 * produces, and it is worth being able to reason about it without a browser.
 *
 * The shapes are `app/services/docx/fill.py`'s, not this console's. Anything
 * saved here is read back by `validate_plan` and then by `apply`, so a field
 * renamed on this side is a plan the backend refuses (at best) or mis-fills.
 *
 * Two invariants are load-bearing:
 *
 * - **An anchor and its fingerprint travel together.** `apply` verifies
 *   `outline.verify(doc, path, entry.fingerprint)` before it writes anything,
 *   so any function that changes an anchor must also change the fingerprint.
 * - **Nothing mutates.** These are React state transitions.
 */
import type { Block } from "../../api/reads";

/** The four kinds `fill.py::PLAN_KINDS` accepts. */
export type PlanEntryKind = "token" | "table" | "insert" | "replace";

/** How an inserted value is broken into paragraphs (`fill.py::_paragraph_texts`). */
export type PlanShape = "paragraph" | "paragraphs" | "bullets";

export type PlanColumn = { col: number; field: string };

export type PlanEntry = {
  kind: PlanEntryKind;
  key: string;
  /** token: the literal phrase standing in for a field. */
  literal?: string;
  /** table and replace: the block this entry addresses. */
  path?: string;
  /** insert: the block the new paragraphs go after… */
  after?: string;
  /** …or before. Exactly one of the two. */
  before?: string;
  /** insert: an existing paragraph whose formatting the new one copies. */
  style_ref?: string;
  fingerprint?: string;
  shape?: PlanShape;
  brief?: string;
  max_words?: number;
  required?: boolean;
  columns?: PlanColumn[];
  header_rows?: number;
  total_row?: { label_col: number; value_col: number } | null;
};

export type Plan = { version: number; entries: PlanEntry[] };

/**
 * What `POST .../suggest` returns: a plan entry, plus the two fields that exist
 * only to help a human decide. Those two are dropped on accept — see
 * `acceptSuggestion`.
 */
export type Suggestion = PlanEntry & { confidence?: number; why?: string };

export type MoveDirection = "up" | "down";

export const EMPTY_PLAN: Plan = { version: 1, entries: [] };

/** Where an entry sits in the document, or null when it sits everywhere. */
export function anchorOf(entry: PlanEntry): string | null {
  return entry.path ?? entry.after ?? entry.before ?? null;
}

/**
 * The part of a path before its final index — `body`, `sec[0]/ftr/body`.
 *
 * Movement is confined to one of these. The outline lists every body block
 * first and then the headers and footers, so a plain "next block in the list"
 * would walk a greeting off the end of the document and into a footer.
 */
function containerOf(path: string): string {
  const open = path.lastIndexOf("[");
  return open === -1 ? path : path.slice(0, open);
}

function withEntries(plan: Plan, entries: PlanEntry[]): Plan {
  return { ...plan, entries };
}

/**
 * Add a suggestion to the plan, or update it in place if it is already there.
 *
 * In place, rather than appended: entries are read in document order in the
 * flow, and re-accepting a placeholder whose brief was reworded should not send
 * it to the bottom of the list.
 */
export function acceptSuggestion(plan: Plan, suggestion: Suggestion): Plan {
  // `confidence` and `why` are the model's reasoning about a decision a human
  // has now made. The plan is stored on the row for the life of the template
  // and is the contract with fill.py; neither field belongs in it.
  const { confidence: _confidence, why: _why, ...entry } = suggestion;
  const at = plan.entries.findIndex((e) => e.key === entry.key);
  if (at === -1) return withEntries(plan, [...plan.entries, entry]);
  const entries = [...plan.entries];
  entries[at] = entry;
  return withEntries(plan, entries);
}

export function rejectSuggestion(plan: Plan, key: string): Plan {
  const entries = plan.entries.filter((e) => e.key !== key);
  return entries.length === plan.entries.length ? plan : withEntries(plan, entries);
}

export function updateBrief(plan: Plan, key: string, brief: string): Plan {
  const at = plan.entries.findIndex((e) => e.key === key);
  if (at === -1) return plan;
  const entries = [...plan.entries];
  entries[at] = { ...entries[at], brief };
  return withEntries(plan, entries);
}

/**
 * Move an entry one block up or down the flow.
 *
 * Returns the plan unchanged — the same object, so a caller can tell — when the
 * move is not available: at either end of the entry's own container, on a token
 * (which has no position), or on a table binding (which can only live on the
 * table it maps).
 */
export function moveEntry(
  plan: Plan,
  key: string,
  direction: MoveDirection,
  blocks: readonly Block[],
): Plan {
  const at = plan.entries.findIndex((e) => e.key === key);
  if (at === -1) return plan;
  const entry = plan.entries[at];
  if (entry.kind === "token" || entry.kind === "table") return plan;

  const anchor = anchorOf(entry);
  if (anchor === null) return plan;
  const from = blocks.findIndex((b) => b.path === anchor);
  if (from === -1) return plan;

  const to = direction === "up" ? from - 1 : from + 1;
  const target = blocks[to];
  if (!target || containerOf(target.path) !== containerOf(anchor)) return plan;

  const moved: PlanEntry = { ...entry, fingerprint: target.fingerprint };
  if (entry.path !== undefined) moved.path = target.path;
  else if (entry.after !== undefined) moved.after = target.path;
  else moved.before = target.path;

  const entries = [...plan.entries];
  entries[at] = moved;
  return withEntries(plan, entries);
}

/**
 * The nearest paragraph at or before `afterPath`, whose formatting an inserted
 * paragraph copies.
 *
 * The anchor itself counts: inserting after a body paragraph should look like
 * that paragraph. Headings deliberately do not — copying a Heading 1 would set
 * the client's greeting at 18pt bold, which is precisely the "the document
 * looks rebuilt" failure this feature exists to remove.
 */
function nearestParagraph(blocks: readonly Block[], afterPath: string): string | null {
  const at = blocks.findIndex((b) => b.path === afterPath);
  if (at === -1) return null;
  const container = containerOf(afterPath);
  for (let i = at; i >= 0; i -= 1) {
    const b = blocks[i];
    if (containerOf(b.path) !== container) continue;
    if (b.kind === "paragraph") return b.path;
  }
  return null;
}

/** The lowest `prefix_N` this plan is not already using. */
function nextKey(plan: Plan, prefix: string): string {
  const taken = new Set(plan.entries.map((e) => e.key));
  for (let n = 1; ; n += 1) {
    const key = `${prefix}_${n}`;
    if (!taken.has(key)) return key;
  }
}

/**
 * Add a placeholder the model did not suggest, after `afterPath`.
 *
 * `styleRefPath` is the administrator's choice when they have one and `null`
 * when they do not, in which case it is derived. Throwing, rather than
 * returning a plan with no style reference, is deliberate: `validate_plan`
 * would refuse that plan on save with a message about a block path, and the
 * administrator would have no idea which control caused it.
 */
export function addInsert(
  plan: Plan,
  afterPath: string,
  styleRefPath: string | null,
  blocks: readonly Block[],
): Plan {
  const anchor = blocks.find((b) => b.path === afterPath);
  if (!anchor) {
    throw new Error(
      `There is no block at ${afterPath} in this document, so nothing can be ` +
        "added there. Re-open the template — it may have been superseded.",
    );
  }
  const styleRef = styleRefPath ?? nearestParagraph(blocks, afterPath);
  if (!styleRef) {
    throw new Error(
      `There is no ordinary paragraph before ${afterPath} to copy formatting ` +
        "from, so a new paragraph here would have none. Add it after a " +
        "paragraph instead.",
    );
  }
  const entry: PlanEntry = {
    kind: "insert",
    key: nextKey(plan, "insert"),
    after: afterPath,
    style_ref: styleRef,
    fingerprint: anchor.fingerprint,
    shape: "paragraph",
    brief: "",
    max_words: 90,
    required: false,
  };
  return withEntries(plan, [...plan.entries, entry]);
}

/** Every entry anchored at this block, in the plan's own order. */
export function entriesForBlock(plan: Plan, path: string): PlanEntry[] {
  return plan.entries.filter((e) => anchorOf(e) === path);
}

/**
 * The suggestions from `POST .../suggest`, reduced to the ones this editor can
 * actually place.
 *
 * `docx_suggest._validate` already drops anything whose anchor is not in the
 * outline, so in normal operation this removes nothing. It exists because the
 * reply is the only payload the console consumes without a read shape, and
 * because a chip anchored at a block that is not rendered would simply never
 * appear — a silent loss, which is the one failure mode this feature was
 * written to remove.
 */
export function usableSuggestions(raw: unknown, blocks: readonly Block[]): Suggestion[] {
  const list = (raw as { suggestions?: unknown } | null)?.suggestions;
  if (!Array.isArray(list)) return [];
  const paths = new Set(blocks.map((b) => b.path));
  const kinds: PlanEntryKind[] = ["token", "table", "insert", "replace"];
  const seen = new Set<string>();
  const kept: Suggestion[] = [];

  for (const item of list) {
    if (typeof item !== "object" || item === null) continue;
    const s = item as Suggestion;
    if (typeof s.key !== "string" || !s.key || seen.has(s.key)) continue;
    if (!kinds.includes(s.kind)) continue;

    if (s.kind === "token") {
      if (typeof s.literal !== "string" || !s.literal.trim()) continue;
    } else if (s.kind === "insert") {
      const anchor = s.after ?? s.before;
      if (!anchor || !paths.has(anchor)) continue;
      if (!s.style_ref || !paths.has(s.style_ref)) continue;
    } else if (!s.path || !paths.has(s.path)) {
      continue;
    }

    seen.add(s.key);
    kept.push(s);
  }
  return kept;
}

/**
 * `save_plan`'s refusal, split back into the lines it was built from.
 *
 * `admin.py::save_proposal_template_plan` collects `validate_plan`'s problems
 * and raises one 422 whose detail is `PREFIX + "; ".join(problems)`. There is
 * no `problems` array on the wire, so this is where the list comes back — one
 * line per problem, which is how an administrator fixes them one at a time.
 * Anything that does not carry the prefix is passed through whole rather than
 * chopped at a semicolon that might belong to a sentence.
 */
const PLAN_REFUSAL_PREFIX = "This plan does not match the document: ";

export function planProblems(detail: string): string[] {
  const message = (detail ?? "").trim();
  if (!message.startsWith(PLAN_REFUSAL_PREFIX)) return message ? [message] : [];
  return message
    .slice(PLAN_REFUSAL_PREFIX.length)
    .split("; ")
    .map((p) => p.trim())
    .filter(Boolean);
}

/* ── Token binding (Task 21) ──────────────────────────────────────────────── */

/**
 * The fields a literal can be bound to.
 *
 * Every one is a key of `proposal_service`'s `variables` dict, and that is not
 * decoration: `build_docx_content` does
 * `values[entry.key] = variables.get(entry.key)`, so a key that dict does not
 * carry resolves to `None`, `fill.apply` records the placeholder as unfilled,
 * and the literal — "School Name" — is still standing in the document that
 * reaches the client. `plan.test.ts` checks this list against the Python source
 * rather than trusting it.
 *
 * Three keys of that dict are deliberately absent here. `school_name` is a
 * legacy alias for `client_name` and offering both would let one value be
 * bound twice under different keys; `pricing_table` is a rendered Markdown
 * block, which is what the table mapping below exists to avoid; and
 * `context_summary` is a paragraph rather than a phrase.
 */
export const BINDABLE_FIELDS = [
  "client_name",
  "contact_name",
  "contact_title",
  "sender_name",
  "sender_email",
  "org_name",
  "program_name",
  "program_description",
  "date",
  "total_amount",
] as const;

export type BindableField = (typeof BINDABLE_FIELDS)[number];

/**
 * The shortest literal that may be bound.
 *
 * `docx_suggest._is_plausible_literal` applies the same floor to the model's
 * suggestions, for a reason it measured: a suggested literal of a single space
 * was accepted and would have rewritten 533 occurrences in `Essential Lab.docx`
 * — every space replaced by the client's name — and "e" 369. Token replacement
 * is global and runs over headers and footers too, so one acceptance corrupts
 * the whole file. Nothing guarded a literal typed by hand: `validate_plan` only
 * checks that it is non-empty. This is that guard.
 */
export const MIN_LITERAL_CHARS = 4;

const tokenAt = (plan: Plan, literal: string) =>
  plan.entries.findIndex((e) => e.kind === "token" && e.literal === literal);

export function fieldForLiteral(plan: Plan, literal: string): string | null {
  const at = tokenAt(plan, literal);
  return at === -1 ? null : plan.entries[at].key;
}

export function literalForField(plan: Plan, field: string): string | null {
  const entry = plan.entries.find((e) => e.kind === "token" && e.key === field);
  return entry?.literal ?? null;
}

/**
 * Bind a literal to a field, or unbind it when `field` is empty.
 *
 * **A field can be held by only one literal.** The entry's key *is* the field,
 * keys are unique per plan, and `validate_plan` refuses a plan that repeats one
 * with "'client_name' is used more than once". So binding a field that another
 * literal already holds moves it, rather than producing a plan the panel could
 * display but the server would not store.
 */
export function bindToken(plan: Plan, literal: string, field: string): Plan {
  const at = tokenAt(plan, literal);
  if (!field) {
    return at === -1 ? plan : withEntries(plan, plan.entries.filter((_, i) => i !== at));
  }
  const entry: PlanEntry = { kind: "token", key: field, literal };
  // Drop whatever else held this field, then place the entry where this
  // literal already sat so the panel does not reorder under the operator.
  const others = plan.entries.filter(
    (e, i) => i !== at && !(e.kind === "token" && e.key === field),
  );
  if (at === -1) return withEntries(plan, [...others, entry]);
  const keptBefore = plan.entries
    .slice(0, at)
    .filter((e) => !(e.kind === "token" && e.key === field)).length;
  return withEntries(plan, [
    ...others.slice(0, keptBefore),
    entry,
    ...others.slice(keptBefore),
  ]);
}

/** Every occurrence of `literal` this console can see in the outline. */
function countLiteral(literal: string, blocks: readonly Block[]): number {
  let n = 0;
  for (const b of blocks) {
    const haystacks = [b.text, ...(b.table ? b.table.sample.flat() : [])];
    for (const text of haystacks) {
      let from = 0;
      for (;;) {
        const at = (text || "").indexOf(literal, from);
        if (at === -1) break;
        n += 1;
        from = at + literal.length;
      }
    }
  }
  return n;
}

export type LiteralCheck = {
  verdict: "too-slight" | "found" | "not-found";
  occurrences: number;
};

/**
 * Can this hand-typed literal be bound, and how many times does it appear?
 *
 * The count is a **lower bound**, and the panel says so. A table block's `text`
 * is only its header row and its `sample` only the first four rows, and nothing
 * in the outline descends into a text box — whereas `docx_text.count_token`,
 * which does the replacing, sees all of it. Measured on `Essential Lab.docx`:
 * the top-level block text holds "School Name" 4 times where `count_token`
 * finds 7. So "not-found" means "this console cannot see it", never "it is not
 * there", and the panel offers to add it anyway.
 */
export function checkLiteral(literal: string, blocks: readonly Block[]): LiteralCheck {
  const trimmed = (literal ?? "").trim();
  if (trimmed.length < MIN_LITERAL_CHARS || !/[a-z]/i.test(trimmed)) {
    return { verdict: "too-slight", occurrences: 0 };
  }
  const occurrences = countLiteral(trimmed, blocks);
  return occurrences > 0
    ? { verdict: "found", occurrences }
    : { verdict: "not-found", occurrences: 0 };
}

/* ── The rate-card table mapping (Task 21) ────────────────────────────────── */

/** The columns `_pricing_value` can supply. Each is a key of a line item. */
export const TABLE_FIELDS = [
  "label",
  "unit",
  "unit_price",
  "quantity",
  "line_total",
] as const;

export type TableField = (typeof TABLE_FIELDS)[number];

export type TableMapping = {
  columns: PlanColumn[];
  header_rows: number;
  total_row: { label_col: number; value_col: number } | null;
};

/** Two obviously-fake line items, shaped as `proposal_service` builds them. */
const SAMPLE_ITEMS: Record<TableField, string | number>[] = [
  {
    label: "Robotics lab setup",
    unit: "per lab",
    unit_price: 120000,
    quantity: 2,
    line_total: 240000,
  },
  {
    label: "Teacher training",
    unit: "per teacher",
    unit_price: 3500,
    quantity: 12,
    line_total: 42000,
  },
];

/** `proposal_service._money`, without the currency symbol — see below. */
function grouped(value: number): string {
  return Number.isInteger(value)
    ? value.toLocaleString("en-US")
    : value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function tableMappingFor(plan: Plan, path: string): TableMapping | null {
  const entry = plan.entries.find((e) => e.kind === "table" && e.path === path);
  if (!entry) return null;
  return {
    columns: entry.columns ?? [],
    header_rows: entry.header_rows ?? 1,
    total_row: entry.total_row ?? null,
  };
}

/**
 * Store a table mapping, keeping the entry's key across edits.
 *
 * The entry carries the block's fingerprint like every other structural entry:
 * `fill.apply` verifies all of them before it writes anything, so a table
 * mapping without one is a mapping nothing checks.
 */
export function setTableMapping(plan: Plan, block: Block, mapping: TableMapping): Plan {
  const at = plan.entries.findIndex((e) => e.kind === "table" && e.path === block.path);
  const entry: PlanEntry = {
    kind: "table",
    key: at === -1 ? nextKey(plan, "pricing") : plan.entries[at].key,
    path: block.path,
    fingerprint: block.fingerprint,
    columns: mapping.columns,
    header_rows: mapping.header_rows,
    total_row: mapping.total_row,
  };
  if (at === -1) return withEntries(plan, [...plan.entries, entry]);
  const entries = [...plan.entries];
  entries[at] = entry;
  return withEntries(plan, entries);
}

export function clearTableMapping(plan: Plan, path: string): Plan {
  const entries = plan.entries.filter((e) => !(e.kind === "table" && e.path === path));
  return entries.length === plan.entries.length ? plan : withEntries(plan, entries);
}

/**
 * The most header rows this table can keep verbatim.
 *
 * `edit.py::fill_table` clones the first **body** row as the template for every
 * generated row, and raises `AnchorError` when there is none — at proposal
 * time, against a plan that saved cleanly, because `validate_plan` does not
 * check this. Negative means the table is too small to map at all.
 */
export function maxHeaderRows(rows: number, hasTotalRow: boolean): number {
  return rows - 1 - (hasTotalRow ? 1 : 0);
}

export function tableMappingProblems(mapping: TableMapping, block: Block): string[] {
  const table = block.table;
  if (!table) return ["This block is not a table."];
  const problems: string[] = [];

  if (mapping.columns.length === 0) {
    problems.push("Map at least one column to a rate-card field.");
  }
  const seenFields = new Set<string>();
  const seenCols = new Set<number>();
  for (const { col, field } of mapping.columns) {
    if (seenFields.has(field)) {
      problems.push(`The rate-card field “${field}” is mapped to two columns.`);
    }
    seenFields.add(field);
    if (seenCols.has(col)) problems.push(`Column ${col + 1} is mapped twice.`);
    seenCols.add(col);
    if (col < 0 || col >= table.cols) {
      problems.push(`Column ${col + 1} is not one of this table's ${table.cols} columns.`);
    }
  }

  const max = maxHeaderRows(table.rows, mapping.total_row !== null);
  if (mapping.header_rows < 0 || mapping.header_rows > max) {
    problems.push(
      `This table has ${table.rows} rows` +
        (mapping.total_row !== null ? " and a total row" : "") +
        `, so at most ${max} can be header rows — otherwise there is no body ` +
        "row left to copy the styling from.",
    );
  }

  const total = mapping.total_row;
  if (total && (total.value_col < 0 || total.value_col >= table.cols)) {
    problems.push(
      `The total's value column must be one of this table's ${table.cols} columns.`,
    );
  }
  return problems;
}

/**
 * What the generated rows would look like, against two obviously-fake items.
 *
 * Every column the mapping does not name comes back **empty**, and that is the
 * behaviour worth seeing before saving rather than after: `fill_table` writes
 * `""` into each cell whose index is not in `columns`, so a column left
 * unmapped is cleared in every generated row, not left as the document had it.
 *
 * Money is grouped but carries no symbol. `_money` prefixes the currency of the
 * rate card, which this screen has not read; showing a guessed symbol beside
 * real column positions would be the one part of this preview that lied.
 */
export function tablePreviewTotal(): string {
  return grouped(SAMPLE_ITEMS.reduce((sum, i) => sum + Number(i.line_total), 0));
}

export function tablePreviewRows(mapping: TableMapping, block: Block): string[][] {
  const cols = block.table?.cols ?? 0;
  return SAMPLE_ITEMS.map((item) => {
    const row = Array.from({ length: cols }, () => "");
    for (const { col, field } of mapping.columns) {
      if (col < 0 || col >= cols) continue;
      const raw = item[field as TableField];
      if (field === "unit_price" || field === "line_total") {
        row[col] = grouped(Number(raw ?? 0));
      } else if (field === "quantity") {
        row[col] = String(Math.trunc(Number(raw ?? 0)));
      } else {
        row[col] = String(raw ?? "");
      }
    }
    return row;
  });
}
