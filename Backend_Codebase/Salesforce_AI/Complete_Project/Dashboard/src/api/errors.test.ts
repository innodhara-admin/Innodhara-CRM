/**
 * Error normalisation and client behaviour — Task 13.
 *
 * Every payload below was captured from the running backend, not invented:
 * a super-admin token on `GET /admin/users`, a short `name` on `POST /orgs`, a
 * bad `slug` pattern, and a wrong password. The two 422 shapes in particular
 * are the reason this file exists — they share a status and differ in the type
 * of `detail`, so a client that discriminated on status would render
 * "[object Object]" to an operator for half of all validation failures.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { DriftError, request } from "./client";
import { driftLog } from "./drift";
import { endpoints, identityFor, SUPER_ONLY } from "./endpoints";
import { isApiError, networkError, normaliseError, type ApiError } from "./errors";
import { session } from "../session/store";

afterEach(() => {
  vi.unstubAllGlobals();
  driftLog.clear();
  session.clear();
});

describe("normaliseError", () => {
  const cases: Array<[string, number, unknown, Partial<ApiError>]> = [
    [
      "401 missing token",
      401,
      { detail: "Missing bearer token" },
      { status: 401, detail: "Missing bearer token", kind: "http" },
    ],
    [
      "403 the super-admin fence, verbatim",
      403,
      {
        detail:
          "This endpoint is organisation-scoped; the Super Admin has no access to organisation data.",
      },
      {
        detail:
          "This endpoint is organisation-scoped; the Super Admin has no access to organisation data.",
      },
    ],
    [
      "409 a delete guard's refusal, verbatim",
      409,
      {
        detail:
          "3 open task(s) need 'rack-and-stack' and nobody else holds it. Give the skill to someone else first, or close that work.",
      },
      {
        detail:
          "3 open task(s) need 'rack-and-stack' and nobody else holds it. Give the skill to someone else first, or close that work.",
      },
    ],
    [
      "422 from AppError — detail is a STRING",
      422,
      { detail: "To apply this reset, send confirm_org_name exactly as 'Acme'" },
      { detail: "To apply this reset, send confirm_org_name exactly as 'Acme'" },
    ],
  ];

  it.each(cases)("%s", (_label, status, body, expected) => {
    expect(normaliseError(status, body)).toMatchObject(expected);
  });

  it("attaches no field errors to a string detail, whatever the status", () => {
    // Asserted separately rather than as `fields: undefined` in the table:
    // toMatchObject treats an explicitly-undefined key as one that must be
    // present, so that spelling tests the opposite of what it looks like.
    for (const status of [400, 403, 409, 422]) {
      expect(normaliseError(status, { detail: "no" }).fields).toBeUndefined();
    }
  });

  it("422 from RequestValidationError — detail is an ARRAY, mapped per field", () => {
    const captured = {
      detail: [
        {
          type: "string_too_short",
          loc: ["body", "name"],
          msg: "String should have at least 2 characters",
          input: "x",
          ctx: { min_length: 2 },
        },
        { type: "missing", loc: ["body", "slug"], msg: "Field required", input: {} },
      ],
    };
    const err = normaliseError(422, captured);
    expect(err.fields).toEqual({
      name: "String should have at least 2 characters",
      slug: "Field required",
    });
    // The flat message still says everything, for a screen with no field to
    // attach it to.
    expect(err.detail).toContain("name: String should have at least 2 characters");
    expect(err.detail).toContain("slug: Field required");
  });

  it("strips the body/query/path prefix but keeps nested paths", () => {
    const err = normaliseError(422, {
      detail: [
        { loc: ["body", "items", 0, "unit_price"], msg: "Input should be greater than or equal to 0" },
        { loc: ["query", "user_id"], msg: "Field required" },
      ],
    });
    expect(Object.keys(err.fields ?? {})).toEqual(["items.0.unit_price", "user_id"]);
  });

  it("does not invent a message for a shape it does not understand", () => {
    const err = normaliseError(500, { unexpected: true });
    expect(err.detail).toBe("The server returned 500 with no message.");
    expect(err.status).toBe(500);
  });

  it("distinguishes a network failure from any HTTP status", () => {
    const err = networkError(new TypeError("Failed to fetch"), "http://127.0.0.1:9010");
    expect(err.kind).toBe("network");
    expect(err.status).toBe(0);
    // Names the address, because a wrong port in the base-URL field is the most
    // likely first-run problem (Q19).
    expect(err.detail).toContain("http://127.0.0.1:9010");
    expect(isApiError(err)).toBe(true);
  });
});

describe("endpoints", () => {
  it("marks only the platform route as needing the super-admin session", () => {
    // D1/Q14: every other route refuses that token. Verified live — a
    // super-admin token on GET /admin/users returns 403.
    expect([...SUPER_ONLY]).toEqual([endpoints.orgs]);
    expect(identityFor(endpoints.orgs)).toBe("super");
    expect(identityFor(endpoints.staff)).toBe("org");
    expect(identityFor(endpoints.settings)).toBe("org");
    // P6/A5: item 1 reads /auth/me, which the org session CAN call.
    expect(identityFor(endpoints.me)).toBe("org");
  });
});

describe("request", () => {
  function stubFetch(status: number, body: unknown) {
    // Typed args, so `calls[0][1]` is a RequestInit rather than an empty tuple
    // — `tsc --noEmit` runs over tests too, and prebuild would fail the build.
    const spy = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(typeof body === "string" ? body : JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", spy);
    return spy;
  }

  const headersOf = (init: RequestInit | undefined): Record<string, string> =>
    (init?.headers ?? {}) as Record<string, string>;

  it("never sends an Idempotency-Key (D17)", async () => {
    // The server reads no headers at all — verified across app/. Sending one
    // would be theatre, and would suggest a retry is safe when it is not.
    session.setOrg({
      token: "t", userId: "u", name: "A", role: "org_admin",
      orgId: "o", orgName: "Org",
    });
    const spy = stubFetch(200, { ok: true });
    await request(endpoints.programs, { as: "org", method: "POST", body: { name: "x" } });

    const headers = headersOf(spy.mock.calls[0]?.[1]);
    expect(Object.keys(headers).map((h) => h.toLowerCase())).not.toContain("idempotency-key");
    expect(headers.Authorization).toBe("Bearer t");
  });

  it("refuses to send a call whose session is missing, naming the identity", async () => {
    const spy = stubFetch(200, {});
    await expect(request(endpoints.orgs, { as: "super" })).rejects.toMatchObject({
      detail: expect.stringContaining("No super session is active"),
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("throws the server's message verbatim on a refusal", async () => {
    session.setSuperToken("s");
    stubFetch(409, { detail: "Program code 'DC' already exists" });
    await expect(request(endpoints.orgs, { as: "super", method: "POST", body: {} }))
      .rejects.toMatchObject({ status: 409, detail: "Program code 'DC' already exists" });
  });

  it("reports drift and withholds the body when a read shape does not match", async () => {
    // A1: hand-written read shapes can drift, and a drifted read must never
    // reach a status function — it would render as "not started".
    session.setOrg({
      token: "t", userId: "u", name: "A", role: "org_admin",
      orgId: "o", orgName: "Org",
    });
    stubFetch(200, [{ id: "1", entity_type: "outbound_message" }]);
    const shape = z.array(z.object({ id: z.string(), rank: z.number() }));

    await expect(
      request(endpoints.approvalRules, { as: "org", shape }),
    ).rejects.toBeInstanceOf(DriftError);

    const drifts = driftLog.get();
    expect(drifts).toHaveLength(1);
    expect(drifts[0].route).toBe(`GET ${endpoints.approvalRules}`);
    expect(drifts[0].path).toBe("0.rank");
    // The keys that did arrive are usually enough to spot a rename.
    expect(drifts[0].receivedKeys).toEqual(["id", "entity_type"]);
    expect(driftLog.has(`GET ${endpoints.approvalRules}`)).toBe(true);
  });

  it("returns parsed data when the shape matches, and records no drift", async () => {
    session.setOrg({
      token: "t", userId: "u", name: "A", role: "org_admin",
      orgId: "o", orgName: "Org",
    });
    stubFetch(200, [{ id: "1", rank: 100 }]);
    const shape = z.array(z.object({ id: z.string(), rank: z.number() }));
    await expect(request(endpoints.approvalRules, { as: "org", shape })).resolves.toEqual([
      { id: "1", rank: 100 },
    ]);
    expect(driftLog.get()).toEqual([]);
  });

  it("keeps one drift entry per route rather than one per poll", async () => {
    session.setOrg({
      token: "t", userId: "u", name: "A", role: "org_admin",
      orgId: "o", orgName: "Org",
    });
    stubFetch(200, [{ id: "1" }]);
    const shape = z.array(z.object({ id: z.string(), rank: z.number() }));
    for (let i = 0; i < 3; i += 1) {
      await request(endpoints.approvalRules, { as: "org", shape }).catch(() => {});
    }
    expect(driftLog.get()).toHaveLength(1);
  });
});

describe("session store", () => {
  it("keeps the two identities separate", () => {
    session.setSuperToken("super-token");
    session.setOrg({
      token: "org-token", userId: "u", name: "A", role: "org_admin",
      orgId: "o", orgName: "Org",
    });
    expect(session.tokenFor("super")).toBe("super-token");
    expect(session.tokenFor("org")).toBe("org-token");
  });

  it("releases the super-admin token without ending the org session", () => {
    // §1.1: the console holds super_admin for exactly one call. Keeping the
    // most privileged token in the tab after that has no upside.
    session.setSuperToken("super-token");
    session.setOrg({
      token: "org-token", userId: "u", name: "A", role: "org_admin",
      orgId: "o", orgName: "Org",
    });
    session.releaseSuper();
    expect(session.tokenFor("super")).toBeNull();
    expect(session.tokenFor("org")).toBe("org-token");
  });

  it("keeps the base URL through a sign-out", () => {
    // Signing out should not send the operator back to hunting for the port.
    session.setBaseUrl("http://127.0.0.1:9010/");
    session.setSuperToken("s");
    session.clear();
    expect(session.get().baseUrl).toBe("http://127.0.0.1:9010");
    expect(session.get().superToken).toBeNull();
  });
});
