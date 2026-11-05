/**
 * How `request` puts a body on the wire.
 *
 * **The multipart case is why this file exists.** `request` JSON-stringified
 * *every* body and stamped `Content-Type: application/json` on it. A
 * `FormData` — the only way to send a file — serialises to `{}` under
 * `JSON.stringify`, so the document upload at checklist item 6 sent an empty
 * JSON object and the backend answered, correctly,
 * `name: Field required; file: Field required`.
 *
 * Nothing caught it. This suite has no component tests by design (D11), the
 * screen was never rendered in a browser, and every other caller in the
 * console sends JSON — so the one code path that does not was the one nobody
 * exercised until an administrator tried to upload a Word document.
 *
 * The rule the fix encodes: **a `FormData` body is passed to `fetch`
 * untouched, and no `Content-Type` is set for it.** The header must carry a
 * `multipart/form-data` boundary that only the browser can generate; setting
 * it by hand produces a request the server cannot parse either.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { request } from "./client";
import { endpoints } from "./endpoints";
import { session } from "../session/store";

function stubFetch(status = 200, body: unknown = { ok: true }) {
  // Declared with fetch's own parameters: without them the mock's call tuple
  // is typed `[]` and reading `calls[0][1]` is a compile error, not a test.
  const spy = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

const initOf = (spy: ReturnType<typeof stubFetch>) =>
  spy.mock.calls[0]?.[1] as RequestInit | undefined;

const headersOf = (spy: ReturnType<typeof stubFetch>) =>
  (initOf(spy)?.headers ?? {}) as Record<string, string>;

const contentType = (spy: ReturnType<typeof stubFetch>) =>
  Object.entries(headersOf(spy)).find(
    ([k]) => k.toLowerCase() === "content-type",
  )?.[1];

describe("request bodies", () => {
  beforeEach(() => {
    session.setOrg({
      token: "t",
      userId: "u",
      name: "A",
      role: "org_admin",
      orgId: "o",
      orgName: "Org",
    });
  });

  it("hands a FormData body to fetch untouched", async () => {
    // Identity, not equality: anything that copies or serialises it loses the
    // file. This is the assertion that would have failed before the fix.
    const form = new FormData();
    form.append("name", "Essential Lab IBC");
    form.append("make_current", "true");
    form.append("file", new Blob([new Uint8Array([80, 75, 3, 4])]), "t.docx");

    const spy = stubFetch();
    await request(endpoints.proposalTemplatesDocx("prog-1"), {
      as: "org",
      method: "POST",
      body: form,
    });

    expect(initOf(spy)?.body).toBe(form);
    expect(typeof initOf(spy)?.body).not.toBe("string");
  });

  it("sets no Content-Type for a FormData body, so the boundary survives", async () => {
    // A multipart request is unparseable without the boundary parameter, and
    // only the browser can generate one. Naming it by hand breaks the request
    // just as thoroughly as calling it application/json did.
    const form = new FormData();
    form.append("name", "x");
    const spy = stubFetch();
    await request(endpoints.proposalTemplatesDocx("prog-1"), {
      as: "org",
      method: "POST",
      body: form,
    });

    expect(contentType(spy)).toBeUndefined();
    expect(headersOf(spy).Authorization).toBe("Bearer t");
  });

  it("still sends every other body as JSON", async () => {
    // The regression this must not cause: one FormData caller must not change
    // how the twenty JSON callers behave.
    const spy = stubFetch();
    await request(endpoints.programs, {
      as: "org",
      method: "POST",
      body: { name: "Thermal audit", code: "TAA" },
    });

    expect(contentType(spy)).toBe("application/json");
    expect(initOf(spy)?.body).toBe('{"name":"Thermal audit","code":"TAA"}');
  });

  it("sends no body and names no content type when there is none", async () => {
    const spy = stubFetch(200, []);
    await request(endpoints.programs, { as: "org" });

    expect(initOf(spy)?.body).toBeUndefined();
    expect(contentType(spy)).toBeUndefined();
  });
});
