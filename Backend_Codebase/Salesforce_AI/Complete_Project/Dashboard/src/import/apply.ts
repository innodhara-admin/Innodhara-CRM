/**
 * Applying an import — 07_BUILD_PLAN.md Task 22 Steps 1–2, D21.
 *
 * **The first thing in this console that writes real data in bulk**, against a
 * backend with no bulk transaction and no idempotency. Three rules follow from
 * that, and none of them is negotiable.
 *
 * ## 1. Every row is attempted (D21)
 *
 * Halting at row 12 of 50 leaves a half-applied file **and no knowledge of rows
 * 13–50** — the operator cannot tell whether the rest would have worked, so
 * they cannot decide whether to fix twelve rows or thirty-eight. Continuing
 * costs nothing (the twelve are already written either way) and turns an
 * unknown into a list. The loop below therefore catches per row and moves on.
 *
 * ## 2. Nothing is retried (D17)
 *
 * The server reads no `Idempotency-Key` and has no dedupe on any admin write —
 * verified across all of `app/`. A retried POST creates a *second* programme,
 * vendor or approval rule and says nothing. `request()` does not retry, and
 * this module must never add one.
 *
 * ## 3. The server's refusal is carried verbatim
 *
 * Into the report, and from there into the `_error` column of the failures
 * file. The backend's messages already say what to do — *"Staff email must use
 * your organisation's domain @x.com"* — and a paraphrase would lose the domain.
 *
 * ## The two shapes
 *
 * Most files are one HTTP call per row. A **`pricing` CSV is one call for the
 * whole file**: its rows are rate-card lines and the file is a single versioned
 * card. That distinction is decided in `validate.ts` and carried here as
 * `FileVerdict.shape`, so this module never re-derives it.
 */
import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { isApiError } from "../api/errors";
import type { Descriptor, EntityKey } from "../descriptors/types";
import type { Row } from "./parse";
import type { FileVerdict } from "./validate";

export type RowOutcome = {
  line: number;
  status: "applied" | "refused";
  /** The server's own words on a refusal; a short confirmation on success. */
  message: string;
  /** The row exactly as it was parsed — what the failures file re-emits. */
  source: Row;
};

export type ApplyReport = {
  outcomes: RowOutcome[];
  applied: number;
  refused: number;
};

/** Where a row of this entity is written, and how. */
export type WriteTarget = { path: string; method: "POST" | "PATCH" };

/**
 * Two entities hang off a programme by path, so the file cannot say which one
 * — `POST /admin/programs/{id}/pricing` takes it in the URL and there is no
 * `program_id` column. The screen asks; this is the type that carries it.
 */
export type ApplyContext = { programId?: string };

export function writeTargetFor(
  descriptor: Descriptor,
  context: ApplyContext,
): WriteTarget | { error: string } {
  const key: EntityKey = descriptor.key;
  switch (key) {
    case "staff":
      return { path: endpoints.staff, method: "POST" };
    case "skills":
      return { path: endpoints.skills, method: "POST" };
    case "programs":
      return { path: endpoints.programs, method: "POST" };
    case "messageTemplates":
      return { path: endpoints.messageTemplates, method: "POST" };
    case "playbooks":
      // The only per-programme entity whose programme is a body field, not a
      // path segment — so its files are self-contained.
      return { path: endpoints.playbooks, method: "POST" };
    case "approvalRules":
      return { path: endpoints.approvalRules, method: "POST" };
    case "demoTeams":
      return { path: endpoints.demoTeams, method: "POST" };
    case "vendors":
      return { path: endpoints.vendors, method: "POST" };
    case "settings":
      // One row, and an update rather than a create.
      return { path: endpoints.settings, method: "PATCH" };
    case "pricing":
      return context.programId
        ? { path: endpoints.pricing(context.programId), method: "POST" }
        : { error: "Choose which offering this rate card belongs to." };
    case "proposalTemplates":
      return context.programId
        ? { path: endpoints.proposalTemplates(context.programId), method: "POST" }
        : { error: "Choose which offering these templates belong to." };
    default: {
      // Exhaustiveness: a new entity must be given a target here rather than
      // silently falling through to a wrong one.
      const never: never = key;
      return { error: `no write target for ${String(never)}` };
    }
  }
}

/** The server's message, verbatim, or the best description of a non-HTTP failure. */
function refusal(cause: unknown): string {
  if (isApiError(cause)) return cause.detail;
  if (cause instanceof Error) return cause.message;
  return String(cause);
}

/**
 * Send the file. Sequential and deliberately so: the backend has no bulk
 * endpoint, and firing fifty writes at once would interleave audit rows and
 * make a partial failure impossible to reason about afterwards.
 */
export async function applyFile(opts: {
  descriptor: Descriptor;
  verdict: FileVerdict;
  context: ApplyContext;
  /** Called after each row, so the screen can show the run progressing. */
  onProgress?: (outcome: RowOutcome, index: number, total: number) => void;
}): Promise<ApplyReport> {
  const { descriptor, verdict, context, onProgress } = opts;
  const target = writeTargetFor(descriptor, context);
  if ("error" in target) {
    throw new Error(target.error);
  }

  const outcomes: RowOutcome[] = [];

  // A pricing CSV: one call, and every line shares its fate. Reported per row
  // anyway, because the operator is looking at a table of lines.
  if (verdict.shape === "file-is-one-call") {
    let outcome: Omit<RowOutcome, "line" | "source">;
    try {
      await request(target.path, {
        as: "org",
        method: target.method,
        body: verdict.grouped,
      });
      outcome = { status: "applied", message: "published as one new version" };
    } catch (cause) {
      outcome = { status: "refused", message: refusal(cause) };
    }
    verdict.rows.forEach((row, i) => {
      const full: RowOutcome = { ...outcome, line: row.line, source: row.source };
      outcomes.push(full);
      onProgress?.(full, i, verdict.rows.length);
    });
    return tally(outcomes);
  }

  for (const [index, row] of verdict.rows.entries()) {
    let outcome: RowOutcome;
    try {
      await request(target.path, { as: "org", method: target.method, body: row.body });
      outcome = { line: row.line, status: "applied", message: "applied", source: row.source };
    } catch (cause) {
      // Caught per row, on purpose. This `catch` **is** D21: without it the
      // loop stops and rows below this one are never attempted.
      outcome = {
        line: row.line,
        status: "refused",
        message: refusal(cause),
        source: row.source,
      };
    }
    outcomes.push(outcome);
    onProgress?.(outcome, index, verdict.rows.length);
  }

  return tally(outcomes);
}

function tally(outcomes: RowOutcome[]): ApplyReport {
  return {
    outcomes,
    applied: outcomes.filter((o) => o.status === "applied").length,
    refused: outcomes.filter((o) => o.status === "refused").length,
  };
}
