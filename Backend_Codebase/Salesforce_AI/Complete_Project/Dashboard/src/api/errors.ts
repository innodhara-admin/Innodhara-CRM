/**
 * The backend's error shapes, normalised — 06_DESIGN.md §4.1.
 *
 * Read from `app/core/exceptions.py` and `app/main.py`, then confirmed against
 * the running server rather than inferred:
 *
 *   401  {"detail": "Missing bearer token"}
 *   403  {"detail": "This endpoint is organisation-scoped; …"}
 *   409  {"detail": "3 open task(s) need 'x' and nobody else holds it. …"}
 *   422  {"detail": "To apply this reset, send confirm_org_name exactly as …"}
 *   422  {"detail": [{"type": "string_pattern_mismatch",
 *                     "loc": ["body", "slug"],
 *                     "msg": "String should match pattern '^[a-z0-9-]+$'",
 *                     "input": "BAD SLUG", "ctx": {...}}]}
 *
 * **Both 422 shapes are real and they are not distinguishable by status.**
 * `app/main.py`'s `AppError` handler returns a string detail, and FastAPI's own
 * `RequestValidationError` returns an array. A client that assumed one shape
 * would render "[object Object]" to an operator for half of all validation
 * failures. Discriminate on the type of `detail`, never on the status.
 */

export type FieldErrors = Record<string, string>;

export type ApiError = {
  /** HTTP status, or 0 when the request never reached the server. */
  status: number;
  /**
   * The server's own message, verbatim. Never a paraphrase: every screen
   * renders the server's refusal exactly as it arrived (§4.1), because the
   * backend's messages already say what to do about it and this console is not
   * in a position to say it better.
   */
  detail: string;
  /** Per-field messages, when the server sent a RequestValidationError. */
  fields?: FieldErrors;
  kind: "network" | "http";
};

type RawValidationItem = {
  loc?: unknown[];
  msg?: string;
  type?: string;
};

/** `["body", "slug"]` → `slug`; `["body", "items", 0, "code"]` → `items.0.code`. */
function fieldPath(loc: unknown[] | undefined): string {
  const parts = (loc ?? []).filter(
    (p, i) => !(i === 0 && (p === "body" || p === "query" || p === "path")),
  );
  return parts.join(".");
}

export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    "kind" in value &&
    ((value as ApiError).kind === "http" || (value as ApiError).kind === "network")
  );
}

/**
 * Turn a parsed response body into an `ApiError`.
 *
 * Anything unrecognised keeps the status and says so plainly rather than
 * inventing a message — a console that makes up an explanation for a response
 * it did not understand is worse than one that admits it.
 */
export function normaliseError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;

  if (typeof detail === "string") {
    return { status, detail, kind: "http" };
  }

  if (Array.isArray(detail)) {
    const fields: FieldErrors = {};
    const lines: string[] = [];
    for (const raw of detail as RawValidationItem[]) {
      const path = fieldPath(raw?.loc);
      const msg = typeof raw?.msg === "string" ? raw.msg : "Invalid value";
      if (path) fields[path] = msg;
      lines.push(path ? `${path}: ${msg}` : msg);
    }
    return {
      status,
      detail: lines.join("; ") || "The server rejected this request.",
      fields: Object.keys(fields).length ? fields : undefined,
      kind: "http",
    };
  }

  return {
    status,
    detail:
      typeof body === "string" && body.trim()
        ? body
        : `The server returned ${status} with no message.`,
    kind: "http",
  };
}

export function networkError(cause: unknown, baseUrl: string): ApiError {
  const reason = cause instanceof Error ? cause.message : String(cause);
  return {
    status: 0,
    // Names the base URL, because "failed to fetch" with the field set to the
    // wrong port is the single most likely first-run problem (Q19).
    detail: `Could not reach the backend at ${baseUrl} (${reason}). Check the server address and that the API is running.`,
    kind: "network",
  };
}
