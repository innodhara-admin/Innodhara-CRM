/**
 * The two responses in this console that are not JSON: a template image, and
 * the preview PDF.
 *
 * `api/client.ts` reads every response as text, which is right for every other
 * route and wrong for these two. It is not extended to cover them because the
 * interesting part is not the parsing — it is that **neither can be fetched by
 * URL alone**. Both routes depend on `get_org_context`, so both need the
 * bearer token, and a browser sends no Authorization header for an `<img src>`
 * or a `window.open`. So the bytes are fetched here with the token and handed
 * on as an object URL.
 *
 * Same rules as the JSON client: one attempt, never a retry (D17), and the
 * server's own refusal is passed through verbatim.
 */
import { networkError, normaliseError, type ApiError } from "../../api/errors";
import { session } from "../../session/store";

export async function fetchBinary(
  path: string,
  method: "GET" | "POST" = "GET",
  signal?: AbortSignal,
): Promise<Blob> {
  const { baseUrl } = session.get();
  const token = session.tokenFor("org");
  if (!token) {
    throw {
      status: 0,
      kind: "http",
      detail: `No org session is active, so ${method} ${path} was not sent.`,
    } satisfies ApiError;
  }

  let response: Response;
  try {
    response = await fetch(new URL(path.replace(/^\//, ""), `${baseUrl}/`).toString(), {
      method,
      headers: { Authorization: `Bearer ${token}` },
      signal,
    });
  } catch (cause) {
    throw networkError(cause, baseUrl);
  }

  if (!response.ok) {
    // The error body IS json — only the success body is bytes.
    const text = await response.text();
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      /* the server's plain words, which normaliseError handles too */
    }
    throw normaliseError(response.status, parsed);
  }
  return response.blob();
}

/**
 * Open a blob in a new tab, and say whether that worked.
 *
 * It often does not: the fetch has already awaited by the time this runs, so
 * the call is no longer inside the click that started it and a popup blocker
 * is entitled to refuse. Returning the URL rather than swallowing the failure
 * lets the caller offer a link the operator can click themselves — which *is*
 * inside a gesture, and always works.
 */
export function openInNewTab(blob: Blob): { url: string; opened: boolean } {
  const url = URL.createObjectURL(blob);
  const win = window.open(url, "_blank", "noopener");
  return { url, opened: Boolean(win) };
}
