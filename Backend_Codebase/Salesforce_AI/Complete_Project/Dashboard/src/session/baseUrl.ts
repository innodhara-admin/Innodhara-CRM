/**
 * Where the API is, before anybody types an address.
 *
 * `app/main.py` mounts this bundle at `/dashboard`, so whenever the console is
 * running from the backend the answer is already on the page: its own origin.
 * The console previously shipped `127.0.0.1:8000` as the answer in every case,
 * which is right only on the machine that built it — anywhere else the operator
 * met "Could not reach the backend at http://127.0.0.1:8000" on a page the
 * backend had just served them, and had to know to correct it by hand. Worse
 * than a plain failure: if something unrelated is listening on 8000 (which is
 * the case on this project's own development machine), the console reaches
 * *that* and reports whatever it says.
 *
 * The field in the session bar (Q19) stays exactly as it was — this only
 * changes what it starts out holding, and a stored session still wins over it.
 */

/** `config.py`'s own default, and the answer when nothing better is known. */
export const CONFIG_DEFAULT_BASE_URL = "http://127.0.0.1:8000";

/** The path `app/main.py` mounts the bundle at. */
export const MOUNT_PATH = "/dashboard";

export type PageLocation = { origin: string; pathname: string };

/**
 * `true` when `pathname` is the mount or something inside it.
 *
 * A **path-segment** test, not a string prefix: `/dashboardish` starts with the
 * same letters and is a different application. This is the same distinction
 * `storage.resolve` turns on, and for the same reason — a prefix comparison
 * over a structured path answers a question nobody asked.
 */
function servedFromMount(pathname: string): boolean {
  return pathname === MOUNT_PATH || pathname.startsWith(`${MOUNT_PATH}/`);
}

/**
 * The address to start from, given where the page is.
 *
 * Takes the location rather than reading `window` so it can be tested: the
 * suite runs in node (D11 rules out a DOM), and a function that reached for a
 * global would be untestable in exactly the environment its own tests run in.
 */
export function defaultBaseUrl(location?: PageLocation | null): string {
  if (!location) return CONFIG_DEFAULT_BASE_URL;
  // `file://` gives the string "null" — an opaque origin is not an address.
  if (!location.origin || location.origin === "null") return CONFIG_DEFAULT_BASE_URL;
  if (!servedFromMount(location.pathname)) return CONFIG_DEFAULT_BASE_URL;
  return location.origin.replace(/\/+$/, "");
}

/** The same answer for the running page, or the config default off-browser. */
export function defaultBaseUrlForThisPage(): string {
  if (typeof window === "undefined" || !window.location) return CONFIG_DEFAULT_BASE_URL;
  const { origin, pathname } = window.location;
  return defaultBaseUrl({ origin, pathname });
}
