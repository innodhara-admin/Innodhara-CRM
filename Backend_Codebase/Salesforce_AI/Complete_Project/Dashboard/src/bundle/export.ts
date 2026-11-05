/**
 * The reseed bundle — export. 06_DESIGN.md §5.8, 07_BUILD_PLAN.md Task 24 Step 4.
 *
 * One JSON file holding the nine entity types a reset can clear, stamped with
 * the organisation it came from. **The bundle and the reset flags are one
 * mechanism**: everything the bundle carries, the reset can clear, and nothing
 * else. Without that pairing the loop does not round-trip.
 *
 * ## The nine are derived, never listed
 *
 * `BUNDLE_ENTITIES` is `ALL_DESCRIPTORS.filter(d => d.inBundle)`. A tenth
 * entity marked `inBundle` appears here with no edit to this file, and
 * `roundtrip.test.ts` asserts the count is nine **and** that it matches §5.8's
 * two rows table-for-table, so the number cannot drift silently in either
 * direction.
 *
 * ## Staff is the one exclusion and it is not an oversight
 *
 * `users` can never be wiped — the reset runs under an `org_admin` session and
 * destroying that row would end the session mid-operation. So staff survives
 * every reset, needs no restoring, and is therefore not in the bundle.
 * `screens/Bundle.tsx` states that at the point of export, in §5.8's own words.
 *
 * ## Same organisation only
 *
 * Skills round-trip on `user_id`, which stays valid precisely because `users`
 * survives. Importing into a different organisation would carry user ids that
 * resolve to nobody there, so the bundle is stamped with `org_id` and
 * `import.ts` refuses a mismatch. It is a reseed loop, not a cloning tool.
 */
import { BUNDLE_ENTITIES, DESCRIPTORS, dependencyOrder } from "../descriptors";
import type { EntityKey } from "../descriptors/types";

export const BUNDLE_FORMAT = "innodhara.bundle";

/**
 * The programme a row belongs to, carried as its **code** rather than its id.
 *
 * Two things the plan's Step 4 does not mention, and both break the loop:
 *
 *  1. **A re-imported programme gets a new id.** `POST /admin/programs` mints
 *     one; nothing lets a client choose it. So a bundle storing `program_id`
 *     restores playbooks pointing at programmes that no longer exist —
 *     `upsert_playbook` does not check that the programme exists (the
 *     descriptor says so), so it would store them silently and no plan would
 *     ever fire them.
 *  2. **Pricing and proposal templates take their programme in the URL**, not
 *     the body, so the write schema has no field for it at all and a projection
 *     derived from `generated.ts` cannot carry one.
 *
 * `code` is the stable key: `add_program` refuses a duplicate compared
 * case-insensitively and stores it uppercased, so it is unique per organisation
 * and survives the round trip. The underscore marks it as the bundle's own
 * bookkeeping rather than a field any route accepts — `import.ts` strips it
 * before sending, and `roundtrip.test.ts` asserts no request body ever carries
 * a key starting with `_`.
 */
export const PROGRAM_KEY = "_program_code";

/**
 * Why a Word-document template is left out of the bundle.
 *
 * A bundle is a JSON file of things to POST. A docx template's substance is the
 * uploaded document itself, which is not in the file and cannot be — so
 * re-importing one would create a *markdown* template holding only the
 * plain-text projection of the original. The branding would disappear and
 * nobody would be told. Skipping it visibly is the honest failure.
 */
export const DOCX_SKIP_REASON =
  "A Word-document template cannot travel in a bundle — the document itself " +
  "is not part of it. Re-upload the .docx in the target organisation.";

export type BundleSkip = { key: EntityKey; label: string; reason: string };

/**
 * Rows `rowsFromReads` deliberately dropped, for the export screen to show.
 * Same inputs as the export, so the two cannot disagree about what was carried.
 */
export function skippedFromReads(opts: {
  programs: Array<{ id: string; code: string }>;
  templatesByProgram: Record<string, Array<Record<string, unknown>>>;
}): BundleSkip[] {
  const codeById = new Map(opts.programs.map((p) => [p.id, p.code]));
  return Object.entries(opts.templatesByProgram).flatMap(([programId, versions]) =>
    versions
      .filter((v) => v.is_current && v.kind === "docx")
      .map((v) => ({
        key: "proposalTemplates" as EntityKey,
        label: `${codeById.get(programId) ?? programId} · ${String(v.name ?? "")}`,
        reason: DOCX_SKIP_REASON,
      })),
  );
}

/** The three entities whose rows belong to one programme. */
export const PROGRAM_SCOPED: readonly EntityKey[] = [
  "pricing",
  "proposalTemplates",
  "playbooks",
];

/**
 * Read value → write value, where the two are genuinely different shapes.
 *
 * `aliases` renames a field; this converts one. There is exactly one today and
 * it is not cosmetic: `demoTeams` writes `member_ids: string[]` and reads back
 * `members: [{id, name}]`, so the alias alone would put objects where the
 * server wants ids and `register_demo_team` would reject the lot. Keyed
 * `entity.writeField` so an unused entry is visibly dead.
 */
export const BUNDLE_TRANSFORMS: Record<string, (value: unknown) => unknown> = {
  "demoTeams.member_ids": (value) =>
    Array.isArray(value)
      ? value.map((m) =>
          m && typeof m === "object" && "id" in m ? (m as { id: string }).id : m,
        )
      : value,
};

/** Bumped only when the shape changes in a way an older console cannot read. */
export const BUNDLE_VERSION = 1;

export type BundleEntityRows = Record<string, unknown[]>;

export type Bundle = {
  format: typeof BUNDLE_FORMAT;
  version: number;
  org: { id: string; name: string };
  exported_at: string;
  /** Keyed by `EntityKey`; every bundled entity is present, empty or not. */
  entities: BundleEntityRows;
};

/**
 * Bundle order is dependency order (`02` §0 — foreign keys and handler checks,
 * not the manual's flat list), filtered to the bundled nine. A re-import walks
 * it forwards, so a programme exists before the rate card that names it.
 */
export function bundleOrder(): EntityKey[] {
  const bundled = new Set<EntityKey>(BUNDLE_ENTITIES);
  return dependencyOrder().filter((key) => bundled.has(key));
}

/**
 * Rows this console read, per entity, reduced to what the **write** accepts.
 *
 * A read carries fields no write takes — `id`, `version`, `is_current`,
 * `updated_by` — and posting them back is at best ignored and at worst a 422.
 * The write schema is the authority on what goes in the file, so the projection
 * is derived from `generated.ts` rather than from a hand-kept field list.
 *
 * `aliases` is applied in reverse: where a read names a field differently from
 * the write, the bundle stores the **write's** name, because a bundle is a file
 * of things to send.
 */
export function projectRow(
  key: EntityKey,
  row: Record<string, unknown>,
  writeFields: readonly string[],
): Record<string, unknown> {
  const descriptor = DESCRIPTORS[key];
  const aliases = descriptor.aliases ?? {};
  const out: Record<string, unknown> = {};
  for (const field of writeFields) {
    // `writeOnly` fields are directives, not data — `make_current` tells the
    // server what to do and has nothing to read back. Excluded rather than
    // exported as undefined.
    if ((descriptor.writeOnly ?? []).includes(field)) continue;
    const source = aliases[field] ?? field;
    if (!(source in row)) continue;
    const transform = BUNDLE_TRANSFORMS[`${key}.${field}`];
    out[field] = transform ? transform(row[source]) : row[source];
  }
  // A playbook's programme goes out as a code as well, since its id will not
  // survive the reset that this bundle exists to undo.
  if (key === "playbooks") delete out.program_id;
  return out;
}

export function buildBundle(opts: {
  org: { id: string; name: string };
  /**
   * Rows per entity, exactly as the reads returned them. Rows of a
   * programme-scoped entity must already carry `PROGRAM_KEY`; `fromReads`
   * below is what puts it there.
   */
  rows: Partial<Record<EntityKey, Record<string, unknown>[]>>;
  /**
   * Write fields per entity, from `generated.ts`. `Partial` because it is built
   * by mapping over `BUNDLE_ENTITIES`, and a bundled entity with no entry
   * throws below rather than exporting empty rows that look like an empty
   * organisation.
   */
  writeFields: Partial<Record<EntityKey, readonly string[]>>;
  now?: () => Date;
}): Bundle {
  const { org, rows, writeFields, now = () => new Date() } = opts;
  const entities: BundleEntityRows = {};
  for (const key of bundleOrder()) {
    const fields = writeFields[key];
    if (!fields) {
      throw new Error(
        `no write fields for bundled entity "${key}" — it would export as empty ` +
          "rows, which is indistinguishable from an organisation that has none",
      );
    }
    entities[key] = (rows[key] ?? []).map((row) => {
      const projected = projectRow(key, row, fields);
      if (PROGRAM_SCOPED.includes(key) && PROGRAM_KEY in row) {
        projected[PROGRAM_KEY] = row[PROGRAM_KEY];
      }
      return projected;
    });
  }
  return {
    format: BUNDLE_FORMAT,
    version: BUNDLE_VERSION,
    org,
    exported_at: now().toISOString(),
    entities,
  };
}

/** Stable, indented JSON — a bundle is a file a human may open and diff. */
export function serialiseBundle(bundle: Bundle): string {
  return JSON.stringify(bundle, null, 2) + "\n";
}

export function bundleFilename(bundle: Bundle): string {
  const day = bundle.exported_at.slice(0, 10);
  return `innodhara-bundle-${bundle.org.id.slice(0, 8)}-${day}.json`;
}

/** Rows per entity, for the export screen's summary. */
export function bundleTally(bundle: Bundle): Array<{ key: string; rows: number }> {
  return bundleOrder().map((key) => ({ key, rows: bundle.entities[key]?.length ?? 0 }));
}

/**
 * Turn the reads the console already holds into `buildBundle`'s `rows`,
 * attaching `PROGRAM_KEY` where the entity needs it.
 *
 * `pricing` and `proposalTemplates` arrive keyed by programme id (that is how
 * the rail fans them out), and only the **current** version of each is
 * exported: the endpoints create a new version per write, so re-importing a
 * whole history would restore it as a stack of versions in import order with
 * the wrong one current. A reseed restores the state, not the audit trail.
 */
export function rowsFromReads(opts: {
  programs: Array<{ id: string; code: string }>;
  skills: Record<string, unknown>[];
  programRows: Record<string, unknown>[];
  pricingByProgram: Record<string, Array<Record<string, unknown>>>;
  templatesByProgram: Record<string, Array<Record<string, unknown>>>;
  messageTemplates: Record<string, unknown>[];
  playbooks: Record<string, unknown>[];
  approvalRules: Record<string, unknown>[];
  demoTeams: Record<string, unknown>[];
  vendors: Record<string, unknown>[];
}): Partial<Record<EntityKey, Record<string, unknown>[]>> {
  const codeById = new Map(opts.programs.map((p) => [p.id, p.code]));

  const currentPerProgram = (
    byProgram: Record<string, Array<Record<string, unknown>>>,
  ): Record<string, unknown>[] =>
    Object.entries(byProgram).flatMap(([programId, versions]) => {
      // A docx template is skipped, not exported: see DOCX_SKIP_REASON.
      // `skippedFromReads` reports the same rows to the export screen.
      const current = versions.filter((v) => v.is_current && v.kind !== "docx");
      const code = codeById.get(programId);
      // A programme the console could not name is skipped rather than exported
      // with a code it would fail to resolve on the way back in.
      if (!code) return [];
      return current.map((v) => ({ ...v, [PROGRAM_KEY]: code }));
    });

  return {
    skills: opts.skills,
    programs: opts.programRows,
    pricing: currentPerProgram(opts.pricingByProgram),
    proposalTemplates: currentPerProgram(opts.templatesByProgram),
    messageTemplates: opts.messageTemplates.filter((t) => t.is_current),
    playbooks: opts.playbooks
      .filter((p) => p.is_current)
      .flatMap((p) => {
        const code = codeById.get(String(p.program_id));
        return code ? [{ ...p, [PROGRAM_KEY]: code }] : [];
      }),
    approvalRules: opts.approvalRules,
    demoTeams: opts.demoTeams,
    vendors: opts.vendors,
  };
}
