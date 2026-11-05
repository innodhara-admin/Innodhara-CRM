/**
 * What a descriptor is — 06_DESIGN.md §3.3.
 *
 * **Only what OpenAPI cannot express lives here.** Field names, types,
 * optionality and every constraint the spec declares come from `generated.ts`
 * and `constraints.generated.ts`; vocabularies come from
 * `vocabularies.generated.ts`. A descriptor adds the things that are not API
 * concepts: CSV column order, the manual's own words, dependency ordering, and
 * who enforces each rule.
 *
 * The word *registry* is deliberately not used for this layer. It described the
 * earlier design in which the whole entity was hand-declared, and keeping the
 * name would imply a completeness this layer no longer has and should never
 * regain (§3.2).
 */
import type { schemas } from "../api/generated";
import type { ReadKey } from "../api/reads";
import type { Enforcement } from "../ui/enforcement";

export type { Enforcement };

export type SchemaName = keyof typeof schemas;

export type Control =
  | "text"
  | "number"
  | "select"
  | "checkbox"
  | "textarea"
  | "json"
  | "quantity";

export type FieldRule = {
  /** Must exist in the entity's generated write schema — asserted by a test. */
  field: string;
  label: string;
  control: Control;
  enforcement: Enforcement;
  /** Rendered beneath the control in small mono (§9). */
  caption: string;
  /** From `VOCAB`, never a literal list (A4). */
  options?: readonly string[];
  /**
   * The options are a **suggestion list, not a closed set**: a value outside it
   * is accepted and warned about rather than refused.
   *
   * Set on exactly one field today — `playbooks.phase` — and the reason is
   * worth stating, because the default (refuse) is right almost everywhere.
   * The server takes any string for `phase`, and this console blocking one
   * would be inventing a validation the backend does not have. The operator
   * may have a reason; what they must not have is the impression that it will
   * work. So the value goes through, and the screen says plainly that no plan
   * will ever fire it.
   */
  optionsAreSuggestions?: boolean;
};

export type Descriptor = {
  key: EntityKey;
  /** Checklist item number in `02_SEEDING_PREREQUISITES.md` / the manual. */
  item: number;
  title: string;
  /** The write body's component schema in `generated.ts`. */
  writeSchema: SchemaName;
  /** The response shape in `READS`, or null where the read is generated. */
  read: ReadKey | null;

  /** The manual's own words, verbatim. Never paraphrase these (§9). */
  quote: string;
  /** What the manual says breaks if the item is skipped. Also verbatim. */
  ifSkipped: string;
  manualRef: string;

  /** Hard predecessors, from `02` §0 — derived from FKs and handler checks. */
  dependsOn: EntityKey[];

  fields: FieldRule[];

  /**
   * CSV column order and an example row. Not an API concept (§3.3).
   *
   * `null` means **JSON only**, and three entities are: `playbooks` (a
   * `list[dict]` per row), `approvalRules` (two free dicts per row) and
   * `settings` (one row, not a list). The import screen reads this rather than
   * carrying its own list of which formats each entity accepts.
   */
  csv: {
    columns: readonly string[];
    example: Record<string, string>;
    /**
     * Set when a CSV **row is not an entity** but one element of a list field
     * — `pricing` is the only case: each row is a rate-card line, and the whole
     * file becomes one versioned card. Named rather than inferred from the
     * column set, because inferring it would silently change behaviour the day
     * an entity's columns happen to stop overlapping its field names.
     */
    linesOf?: string;
  } | null;

  /**
   * A worked example for the JSON template, for the three entities that have
   * no `csv` block to derive one from — playbooks, approval rules and settings.
   *
   * Required for those three and unused for the rest, which build theirs from
   * `csv.example`. A conformance test asserts exactly that split, and the
   * import round-trip test asserts that whatever this holds **validates
   * clean**: the file the console hands an operator has to be a file the
   * console accepts.
   */
  jsonExample?: Record<string, unknown>;

  /** Carried by the reseed bundle (§5.8). Staff is the one exclusion. */
  inBundle: boolean;

  /**
   * Write fields that are **directives, not data** — `make_current` tells the
   * server what to do, and there is nothing to read back. Excluded from the
   * round-trip check rather than silently ignored by it.
   */
  writeOnly?: readonly string[];

  /**
   * Write field → read field, where the two genuinely differ in name.
   * Each entry is a place the API is asymmetric, so each needs a reason.
   */
  aliases?: Readonly<Record<string, string>>;

  /**
   * Rules that span more than one field, so they cannot live in `fields`.
   *
   * There is exactly one in the checklist today — an email message template
   * must carry a subject — and it belongs here rather than in the screen that
   * happens to render it, because §3.4's five consumers all need it: the form
   * validates it, the format panel states it, and the import preview must
   * refuse a row that breaks it before applying anything.
   */
  crossFieldRules?: readonly CrossFieldRule[];

  /** Re-importing the same file does what? (§5.5, rendered in the preview.) */
  reimport: string;
};

export type CrossFieldRule = {
  /** The field the error attaches to, so the form marks the right control. */
  field: string;
  /** Stated as a requirement, for the format panel: "required when …". */
  says: string;
  enforcement: Enforcement;
  /** Returns a message when the row is wrong, or null when it is fine. */
  check: (row: Record<string, unknown>) => string | null;
};

export type EntityKey =
  | "staff"
  | "skills"
  | "programs"
  | "pricing"
  | "proposalTemplates"
  | "messageTemplates"
  | "playbooks"
  | "approvalRules"
  | "demoTeams"
  | "vendors"
  | "settings";
