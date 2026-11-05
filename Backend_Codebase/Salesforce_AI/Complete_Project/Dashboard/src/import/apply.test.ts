/**
 * Applying an import — Task 22 Steps 1–2.
 *
 * The load-bearing test is **continue-on-error with the failure in the middle**.
 * A suite that only ever fails the last row passes against an applier that
 * halts, which is the exact bug D21 exists to prevent — so row 3 of 5 is
 * refused here, and the assertion is that rows 4 and 5 were *attempted*, not
 * merely that the counts add up.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { DESCRIPTORS } from "../descriptors";
import type { ApiError } from "../api/errors";
import { applyFile, writeTargetFor } from "./apply";
import { parseFile } from "./parse";
import { validateFile } from "./validate";

/** Every path the applier asked for, in order — the record the tests read. */
let sent: Array<{ path: string; method: string; body: unknown }> = [];

vi.mock("../api/client", () => ({
  request: (path: string, options: { method?: string; body?: unknown }) => {
    sent.push({ path, method: options.method ?? "GET", body: options.body });
    const decision = (globalThis as { __decide?: (b: unknown) => void }).__decide;
    decision?.(options.body);
    return Promise.resolve({ ok: true });
  },
}));

/** Refuse rows whose body satisfies `predicate`, with the server's own wording. */
function refuseWhen(predicate: (body: Record<string, unknown>) => boolean, detail: string) {
  (globalThis as { __decide?: (b: unknown) => void }).__decide = (body) => {
    if (predicate(body as Record<string, unknown>)) {
      const error: ApiError = { status: 409, kind: "http", detail };
      throw error;
    }
  };
}

afterEach(() => {
  sent = [];
  delete (globalThis as { __decide?: unknown }).__decide;
});

const vendorsFile = (names: string[]) =>
  "name,category\n" + names.map((n) => `${n},transport`).join("\n") + "\n";

function verdictFor(key: keyof typeof DESCRIPTORS, text: string, format: "csv" | "json" = "csv") {
  const descriptor = DESCRIPTORS[key];
  const parsed = parseFile(descriptor, text, format);
  return { descriptor, parsed, verdict: validateFile(descriptor, parsed.rows, format) };
}

describe("D21 — every row is attempted", () => {
  it("continues past a failure in the MIDDLE of the file", async () => {
    const { descriptor, verdict } = verdictFor(
      "vendors",
      vendorsFile(["Northgate", "Ashcroft", "Bad Vendor", "Dorset", "Ely"]),
    );
    refuseWhen((b) => b.name === "Bad Vendor", "A vendor with that name already exists");

    const report = await applyFile({ descriptor, verdict, context: {} });

    // Not just the counts: the applier must have SENT rows 4 and 5, which is
    // what an applier that halted would not have done.
    expect(sent.map((s) => (s.body as { name: string }).name)).toEqual([
      "Northgate",
      "Ashcroft",
      "Bad Vendor",
      "Dorset",
      "Ely",
    ]);
    expect(report.applied).toBe(4);
    expect(report.refused).toBe(1);
    expect(report.outcomes.map((o) => o.status)).toEqual([
      "applied",
      "applied",
      "refused",
      "applied",
      "applied",
    ]);
  });

  it("continues past SEVERAL failures, and reports each separately", async () => {
    const { descriptor, verdict } = verdictFor(
      "vendors",
      vendorsFile(["A", "B", "C", "D", "E", "F"]),
    );
    refuseWhen(
      (b) => ["B", "D", "E"].includes(String(b.name)),
      "A vendor with that name already exists",
    );

    const report = await applyFile({ descriptor, verdict, context: {} });
    expect(sent).toHaveLength(6);
    expect(report.applied).toBe(3);
    expect(report.refused).toBe(3);
    expect(report.outcomes.filter((o) => o.status === "refused").map((o) => o.line)).toEqual([
      2, 4, 5,
    ]);
  });

  it("attempts every row even when the FIRST one fails", async () => {
    // The other end of the same mistake: an applier that gave up on a bad start.
    const { descriptor, verdict } = verdictFor("vendors", vendorsFile(["Bad", "B", "C"]));
    refuseWhen((b) => b.name === "Bad", "no");
    const report = await applyFile({ descriptor, verdict, context: {} });
    expect(sent).toHaveLength(3);
    expect(report.applied).toBe(2);
  });

  it("reports progress as it goes, so a long run is visible", async () => {
    const { descriptor, verdict } = verdictFor("vendors", vendorsFile(["A", "B", "C"]));
    const seen: Array<[number, string]> = [];
    await applyFile({
      descriptor,
      verdict,
      context: {},
      onProgress: (_outcome, index, total) => seen.push([index, `${index + 1}/${total}`]),
    });
    expect(seen.map(([, label]) => label)).toEqual(["1/3", "2/3", "3/3"]);
  });
});

describe("the server's refusal is carried verbatim", () => {
  it("keeps the message exactly, including the detail a paraphrase would lose", async () => {
    const message = "Staff email must use your organisation's domain @meridian.example.com";
    const { descriptor, verdict } = verdictFor(
      "staff",
      "email,name,role\nx@wrong.com,Ravi Menon,sales_agent\n",
    );
    refuseWhen(() => true, message);
    const report = await applyFile({ descriptor, verdict, context: {} });
    expect(report.outcomes[0].message).toBe(message);
  });
});

describe("the outcome carries the row the operator wrote", () => {
  it("puts the SOURCE row on each outcome, not the coerced body", async () => {
    // The link between apply.ts and failures.ts, and nothing else asserted it:
    // swapping `source: row.source` for `row.body` passed every other test in
    // this file and every test in failures.test.ts, because those build their
    // own outcomes. It would have silently rewritten the operator's file — a
    // blank cell coming back absent, `mon|tue` coming back as an array.
    const { descriptor, verdict } = verdictFor(
      "pricing",
      "code,label,unit,unit_price,default_quantity,notes\nRACK,Rack,per rack,45000,,\n",
    );
    refuseWhen(() => true, "Program not found");
    const report = await applyFile({ descriptor, verdict, context: { programId: "p1" } });

    // The body dropped the blank; the outcome must not have.
    expect("default_quantity" in verdict.rows[0].body).toBe(false);
    expect(report.outcomes[0].source.default_quantity).toBe("");
    expect(report.outcomes[0].source.unit_price).toBe("45000");
  });

  it("does the same on the row-per-call path", async () => {
    const { descriptor, verdict } = verdictFor(
      "staff",
      "email,name,role,working_days\nx@y.com,Ravi Menon,sales_agent,mon|tue\n",
    );
    refuseWhen(() => true, "nope");
    const report = await applyFile({ descriptor, verdict, context: {} });
    // Coerced to an array on the wire, still a pipe string in the file.
    expect(verdict.rows[0].body.working_days).toEqual(["mon", "tue"]);
    expect(report.outcomes[0].source.working_days).toBe("mon|tue");
  });
});

describe("write targets", () => {
  it("sends each entity to its own route", () => {
    expect(writeTargetFor(DESCRIPTORS.vendors, {})).toEqual({
      path: "/api/v1/vendors",
      method: "POST",
    });
    // Settings is an update of one row, not a create.
    expect(writeTargetFor(DESCRIPTORS.settings, {})).toEqual({
      path: "/api/v1/admin/settings",
      method: "PATCH",
    });
  });

  it("refuses to guess a programme for the two entities that need one", () => {
    for (const key of ["pricing", "proposalTemplates"] as const) {
      const target = writeTargetFor(DESCRIPTORS[key], {});
      expect(target, key).toHaveProperty("error");
    }
    expect(writeTargetFor(DESCRIPTORS.pricing, { programId: "p1" })).toEqual({
      path: "/api/v1/admin/programs/p1/pricing",
      method: "POST",
    });
  });

  it("takes a playbook's programme from the file, not the screen", () => {
    // The one per-programme entity whose programme is a body field, so its
    // files are self-contained and no picker is needed.
    expect(writeTargetFor(DESCRIPTORS.playbooks, {})).toEqual({
      path: "/api/v1/playbooks",
      method: "POST",
    });
  });
});

describe("a pricing CSV is one call for the whole file", () => {
  it("sends one request and reports every line", async () => {
    const { descriptor, verdict } = verdictFor(
      "pricing",
      "code,label,unit,unit_price,default_quantity,notes\n" +
        "RACK,Rack,per rack,45000,4,\n" +
        "AUDIT,Audit,per site,120000,,\n",
    );
    const report = await applyFile({ descriptor, verdict, context: { programId: "p1" } });
    expect(sent).toHaveLength(1);
    expect(sent[0].path).toBe("/api/v1/admin/programs/p1/pricing");
    expect((sent[0].body as { items: unknown[] }).items).toHaveLength(2);
    expect(report.applied).toBe(2);
  });

  it("marks every line refused when the single call is refused", async () => {
    const { descriptor, verdict } = verdictFor(
      "pricing",
      "code,label,unit,unit_price,default_quantity,notes\nRACK,Rack,per rack,45000,4,\nX,X,per x,1,,\n",
    );
    refuseWhen(() => true, "Program not found");
    const report = await applyFile({ descriptor, verdict, context: { programId: "nope" } });
    expect(report.refused).toBe(2);
    expect(report.outcomes.every((o) => o.message === "Program not found")).toBe(true);
  });
});
