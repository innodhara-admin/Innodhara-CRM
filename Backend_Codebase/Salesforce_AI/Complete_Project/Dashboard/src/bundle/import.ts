/**
 * The reseed bundle — import. 06_DESIGN.md §5.8, 07_BUILD_PLAN.md Task 24 Step 4.
 *
 * Reads a bundle back into the organisation it came from, in dependency order,
 * remapping the one thing that cannot survive a reset: **programme ids**.
 *
 * ## Refusals, and why each is here rather than left to the server
 *
 * | refused | because |
 * |---|---|
 * | not a bundle / wrong `format` | a stray JSON file applied entity-by-entity is fifty writes before the first error |
 * | `version` newer than this console | an unknown field would be dropped in silence, which is the one failure a reseed must not have |
 * | `org.id` ≠ the session's | **skills round-trip on `user_id`**, and those ids resolve to nobody in another organisation. §5.8: a reseed loop, not a cloning tool |
 * | an unknown entity key | it would be skipped silently, restoring less than the file holds |
 *
 * Everything else is left to the server and rendered verbatim, exactly as
 * `import/apply.ts` does — this module reuses `writeTargetFor` rather than
 * carrying a second table of where each entity is written.
 *
 * ## D21 and D17 hold here too
 *
 * Every row is attempted and nothing is retried. A reseed that stops at the
 * first refusal leaves an organisation half-restored **and** no knowledge of
 * what the rest would have done, which is worse than either outcome on its own.
 */
import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { isApiError } from "../api/errors";
import { DESCRIPTORS } from "../descriptors";
import type { EntityKey } from "../descriptors/types";
import { writeTargetFor } from "../import/apply";
import {
  BUNDLE_FORMAT,
  BUNDLE_VERSION,
  PROGRAM_KEY,
  PROGRAM_SCOPED,
  bundleOrder,
  type Bundle,
} from "./export";

export type BundleProblem = { fatal: true; why: string };

export type ParsedBundle = {
  bundle: Bundle;
  /** Rows per entity, in the order they will be sent. */
  plan: Array<{ key: EntityKey; rows: Record<string, unknown>[] }>;
  total: number;
};

/** The server's message, verbatim, or the best description of a non-HTTP failure. */
function refusal(cause: unknown): string {
  if (isApiError(cause)) return cause.detail;
  if (cause instanceof Error) return cause.message;
  return String(cause);
}

/**
 * Parse and check a bundle against the active session.
 *
 * Returns the problem rather than throwing, because the screen renders it as a
 * refusal with the same weight as a server's own.
 */
export function parseBundle(
  text: string,
  session: { orgId: string; orgName: string },
): ParsedBundle | BundleProblem {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (cause) {
    return { fatal: true, why: `This file is not valid JSON — ${refusal(cause)}` };
  }
  if (!raw || typeof raw !== "object") {
    return { fatal: true, why: "This file is not a bundle: it is not a JSON object." };
  }
  const candidate = raw as Partial<Bundle>;
  if (candidate.format !== BUNDLE_FORMAT) {
    return {
      fatal: true,
      why:
        `This file is not a reseed bundle. A bundle carries "format": ` +
        `"${BUNDLE_FORMAT}"; this one carries ${JSON.stringify(candidate.format ?? null)}.`,
    };
  }
  if (typeof candidate.version !== "number" || candidate.version > BUNDLE_VERSION) {
    return {
      fatal: true,
      why:
        `This bundle is version ${String(candidate.version)} and this console reads ` +
        `up to ${BUNDLE_VERSION}. Applying it would drop whatever the newer ` +
        `version added, without saying so.`,
    };
  }
  if (!candidate.org?.id) {
    return { fatal: true, why: "This bundle names no organisation, so it cannot be checked against your session." };
  }
  if (candidate.org.id !== session.orgId) {
    return {
      fatal: true,
      why:
        `This bundle was exported from "${candidate.org.name ?? candidate.org.id}" and ` +
        `you are signed in to "${session.orgName}". A bundle carries skills by ` +
        `user id, and those ids belong to the organisation that made it — this is ` +
        `a reseed loop, not a way to copy one organisation into another.`,
    };
  }
  const entities = candidate.entities;
  if (!entities || typeof entities !== "object") {
    return { fatal: true, why: "This bundle carries no entities object." };
  }

  const known = new Set<string>(bundleOrder());
  const unknown = Object.keys(entities).filter((k) => !known.has(k));
  if (unknown.length > 0) {
    return {
      fatal: true,
      why:
        `This bundle carries ${unknown.length === 1 ? "an entity" : "entities"} this ` +
        `console does not know how to restore: ${unknown.join(", ")}. Applying it ` +
        `would silently restore less than the file holds.`,
    };
  }

  const plan = bundleOrder().map((key) => ({
    key,
    rows: (entities[key] ?? []) as Record<string, unknown>[],
  }));

  return {
    bundle: candidate as Bundle,
    plan,
    total: plan.reduce((n, p) => n + p.rows.length, 0),
  };
}

export type BundleRowOutcome = {
  key: EntityKey;
  index: number;
  status: "applied" | "refused";
  /** The server's own words on a refusal. */
  message: string;
  /** How the row is named in the report — a code, a name, a kind/channel. */
  label: string;
};

export type BundleReport = {
  outcomes: BundleRowOutcome[];
  applied: number;
  refused: number;
};

/** A row's most identifying field, for the report. Never invented. */
export function labelFor(key: EntityKey, row: Record<string, unknown>): string {
  const parts = [row.code, row.name, row.kind && row.channel && `${row.kind}/${row.channel}`,
    row.phase, row.skill, row.entity_type, row[PROGRAM_KEY]]
    .filter((v) => typeof v === "string" && v.length > 0);
  return parts.length > 0 ? parts.join(" · ") : `${key} row`;
}

/**
 * Send a parsed bundle.
 *
 * **Programme ids are resolved as the run goes**, not up front: `programs` is
 * first in dependency order, so by the time a rate card is sent its programme
 * has just been created and its new id is known. A programme that failed to
 * create takes its dependants with it, and each says so by name rather than
 * failing with the server's "not found".
 */
export async function applyBundle(opts: {
  parsed: ParsedBundle;
  /** Programme code → id for programmes that already exist. */
  existingProgramIds?: Record<string, string>;
  onProgress?: (outcome: BundleRowOutcome, done: number, total: number) => void;
}): Promise<BundleReport> {
  const { parsed, existingProgramIds = {}, onProgress } = opts;
  const outcomes: BundleRowOutcome[] = [];
  const programIdByCode = new Map<string, string>(Object.entries(existingProgramIds));
  let done = 0;

  for (const { key, rows } of parsed.plan) {
    for (const [index, row] of rows.entries()) {
      const label = labelFor(key, row);
      const code = typeof row[PROGRAM_KEY] === "string" ? (row[PROGRAM_KEY] as string) : null;

      // Strip the bundle's own bookkeeping — no route accepts it.
      const body: Record<string, unknown> = {};
      for (const [field, value] of Object.entries(row)) {
        if (!field.startsWith("_")) body[field] = value;
      }

      let programId: string | undefined;
      if (PROGRAM_SCOPED.includes(key)) {
        if (!code) {
          outcomes.push({
            key, index, status: "refused", label,
            message: `This row names no programme code, so there is nothing to attach it to.`,
          });
          onProgress?.(outcomes[outcomes.length - 1], ++done, parsed.total);
          continue;
        }
        programId = programIdByCode.get(code.toUpperCase());
        if (!programId) {
          outcomes.push({
            key, index, status: "refused", label,
            message:
              `Programme "${code}" was not restored, so this row has nothing to ` +
              `attach to. Fix the programme and re-import.`,
          });
          onProgress?.(outcomes[outcomes.length - 1], ++done, parsed.total);
          continue;
        }
        // Playbooks carry it in the body; the other two in the URL.
        if (key === "playbooks") body.program_id = programId;
      }

      const target = writeTargetFor(DESCRIPTORS[key], { programId });
      if ("error" in target) {
        outcomes.push({ key, index, status: "refused", label, message: target.error });
        onProgress?.(outcomes[outcomes.length - 1], ++done, parsed.total);
        continue;
      }

      let outcome: BundleRowOutcome;
      try {
        const created = await request<Record<string, unknown>>(target.path, {
          as: "org",
          method: target.method,
          body,
        });
        // Learn the new id the moment it exists, so dependants can use it.
        if (key === "programs" && created && typeof created.id === "string") {
          const restored = typeof created.code === "string" ? created.code : String(body.code);
          programIdByCode.set(restored.toUpperCase(), created.id);
        }
        outcome = { key, index, status: "applied", message: "restored", label };
      } catch (cause) {
        // Per row, on purpose — this catch is D21.
        outcome = { key, index, status: "refused", message: refusal(cause), label };
      }
      outcomes.push(outcome);
      onProgress?.(outcome, ++done, parsed.total);
    }
  }

  return {
    outcomes,
    applied: outcomes.filter((o) => o.status === "applied").length,
    refused: outcomes.filter((o) => o.status === "refused").length,
  };
}

/** Where the bundle's programmes are read back from, for the screen's re-check. */
export const PROGRAMS_PATH = endpoints.programs;
