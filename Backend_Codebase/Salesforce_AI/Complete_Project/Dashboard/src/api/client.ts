/**
 * The HTTP client — 06_DESIGN.md §4.1.
 *
 * Hand-written rather than generated: the generated layer is schemas only
 * (`schemas-only.hbs`), because this client needs a settable base URL, a token
 * chosen per call from one of two sessions, and no retries — none of which a
 * generated Zodios client would give.
 *
 * **No `Idempotency-Key` is minted** (D17). Verified across all of `app/`: the
 * only middleware is CORS, no route reads any header, and
 * `outbound_messages.idempotency_key` is minted server-side. Sending one would
 * be theatre, and — because there is no server-side dedupe on admin writes — a
 * retried POST genuinely creates a second program, vendor or approval rule.
 */
import type { ZodType } from "zod";

import { driftLog } from "./drift";
import { networkError, normaliseError, type ApiError } from "./errors";
import { session, type Identity } from "../session/store";

export type RequestOptions<T> = {
  /** Which session to authenticate as. `none` for login and health. */
  as: Identity | "none";
  /**
   * An explicit token, used instead of a stored session. Exists for exactly one
   * caller: D18's hand-off, whose step-3 token is minted from a temporary
   * password and must never be written anywhere readable — putting it in the
   * session store would defeat the point of holding the temp password in a
   * local variable. Requires `as: "none"`.
   */
  bearer?: string;
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  /**
   * Read shape for an untyped response (A1). When given, the body is parsed and
   * a failure is reported as drift instead of being handed to the caller.
   */
  shape?: ZodType<T>;
  signal?: AbortSignal;
};

function buildUrl(baseUrl: string, path: string, query?: RequestOptions<unknown>["query"]): string {
  const url = new URL(path.replace(/^\//, ""), `${baseUrl}/`);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined) url.searchParams.set(k, String(v));
  }
  return url.toString();
}

export class DriftError extends Error {
  constructor(readonly route: string) {
    super(`The server's reply for ${route} no longer matches what this console expects.`);
    this.name = "DriftError";
  }
}

/**
 * Perform one request. Throws `ApiError` on any non-2xx, `DriftError` when a
 * read shape does not match. Never retries.
 */
export async function request<T = unknown>(
  path: string,
  options: RequestOptions<T>,
): Promise<T> {
  const { baseUrl } = session.get();
  const method = options.method ?? "GET";
  const route = `${method} ${path}`;
  const headers: Record<string, string> = { Accept: "application/json" };

  if (options.bearer) {
    headers.Authorization = `Bearer ${options.bearer}`;
  } else if (options.as !== "none") {
    const token = session.tokenFor(options.as);
    if (!token) {
      // Better than a 401 round trip: this is a bug in the caller, and saying
      // which identity was missing is what makes it a five-second fix.
      throw {
        status: 0,
        kind: "http",
        detail: `No ${options.as} session is active, so ${route} was not sent.`,
      } satisfies ApiError;
    }
    headers.Authorization = `Bearer ${token}`;
  }
  /**
   * A `FormData` body is the one thing that must not be serialised.
   *
   * It carries a file, and `JSON.stringify(new FormData())` is `"{}"` — which
   * is what the document upload at checklist item 6 was sending, and why the
   * backend answered `name: Field required; file: Field required`. Nor may a
   * `Content-Type` be named for it: a multipart request is unparseable without
   * the boundary parameter, and only the browser can generate one, so the
   * header is left off and `fetch` fills it in.
   */
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(baseUrl, path, options.query), {
      method,
      headers,
      body:
        options.body === undefined
          ? undefined
          : isForm
            ? (options.body as FormData)
            : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (cause) {
    throw networkError(cause, baseUrl);
  }

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!response.ok) throw normaliseError(response.status, parsed);

  if (!options.shape) return parsed as T;

  const result = options.shape.safeParse(parsed);
  if (result.success) return result.data;

  const first = result.error.issues[0];
  driftLog.report({
    route,
    path: first?.path.join(".") || "(root)",
    message: first?.message ?? "unexpected shape",
    receivedKeys:
      parsed && typeof parsed === "object"
        ? Object.keys(Array.isArray(parsed) ? (parsed[0] ?? {}) : parsed)
        : [],
  });
  throw new DriftError(route);
}
