/**
 * The read shapes, against payloads a real backend actually produced.
 *
 * `reads.ts` is the only layer with no generated source behind it (P1), so the
 * fixtures are its evidence. They were captured by `tools/capture_fixtures.mjs`
 * from a throwaway organisation seeded with **one row in every entity** — an
 * empty array validates under any shape and would make every assertion here
 * vacuous.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { READS, READ_SOURCE, type ReadKey } from "./reads";

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), "__fixtures__");

const load = (name: string): unknown =>
  JSON.parse(readFileSync(join(FIXTURES, `${name}.json`), "utf-8"));

const keys = Object.keys(READS) as ReadKey[];

describe("every read shape parses a real payload", () => {
  it.each(keys)("%s", (key) => {
    const result = READS[key].safeParse(load(key));
    if (!result.success) {
      throw new Error(
        `${key} (${READ_SOURCE[key]}) does not match its fixture:\n` +
          result.error.issues
            .map((i) => `  ${i.path.join(".") || "(root)"}: ${i.message}`)
            .join("\n"),
      );
    }
    expect(result.success).toBe(true);
  });

  it("has a fixture for every shape and a shape for every fixture", () => {
    const onDisk = readdirSync(FIXTURES)
      .filter((f) => f.endsWith(".json"))
      .map((f) => f.replace(/\.json$/, ""));
    for (const key of keys) expect(onDisk, key).toContain(key);
    // staff and me are captured too: they are typed by the spec, so they are
    // not in READS, but the status derivation reads them and a fixture is free.
    const typedElsewhere = new Set(["staff", "me"]);
    const orphans = onDisk.filter(
      (f) => !keys.includes(f as ReadKey) && !typedElsewhere.has(f),
    );
    expect(orphans, "a fixture with no shape to check it").toEqual([]);
  });
});

describe("the fixtures are worth having", () => {
  it("every list fixture has at least one row", () => {
    // The failure this prevents: a capture run against an empty organisation,
    // producing [] everywhere and a suite that proves nothing.
    for (const key of keys) {
      const payload = load(key);
      if (Array.isArray(payload)) {
        expect(payload.length, `${key} fixture is empty`).toBeGreaterThan(0);
      }
    }
  });

  it("captures the two fields change #9 added", () => {
    const rules = load("approvalRules") as Array<Record<string, unknown>>;
    const configured = rules.find((r) => r.fallback_role !== null);
    expect(configured, "seed a rule WITH a fallback_role or this proves nothing")
      .toBeDefined();
    expect(configured).toHaveProperty("auto_approve");
  });

  it("captures the three ids change #10 added, alongside the names", () => {
    const [team] = load("demoTeams") as Array<Record<string, unknown>>;
    expect(team.lead_user_id).toEqual(expect.any(String));
    expect(team.media_rep_id).toEqual(expect.any(String));
    expect(team.sales_rep_id).toEqual(expect.any(String));
    expect(team.lead).toEqual(expect.any(String));
  });

  it("captures both halves of the default_quantity tri-state", () => {
    // §3.3: null means "this org did not say how many", which is not 1. If the
    // fixture only ever had numbers, the nullable in the shape would be untested
    // and a backend that started coercing to 1 would pass.
    const [card] = load("pricing") as Array<{
      items: Array<{ default_quantity: number | null }>;
    }>;
    const quantities = card.items.map((i) => i.default_quantity);
    expect(quantities).toContain(null);
    expect(quantities.some((q) => typeof q === "number")).toBe(true);
  });

  it("captures all four message-template kind × channel combinations", () => {
    const rows = load("messageTemplates") as Array<{ kind: string; channel: string }>;
    const combos = new Set(rows.map((r) => `${r.kind}/${r.channel}`));
    expect([...combos].sort()).toEqual([
      "follow_up/email",
      "follow_up/whatsapp",
      "intro/email",
      "intro/whatsapp",
    ]);
  });

  it("captures both delivery halves settings needs for item 11", () => {
    const s = load("settings") as Record<string, unknown>;
    expect(s).toHaveProperty("email_mode");
    expect(s).toHaveProperty("email_credentials_stored");
    expect(s).toHaveProperty("email_integration_configured");
    // The compound status needs both facts; a single boolean cannot say which
    // half is missing (§5.2 item 11).
    // 35, plus the seven WhatsApp provider fields of 4 Nov 2026.
    expect(Object.keys(s)).toHaveLength(42);
  });
});

describe("the shapes reject what they should", () => {
  it("fails when a required field is removed — the drift that matters", () => {
    const rows = load("vendors") as Array<Record<string, unknown>>;
    const withoutId = rows.map(({ id: _id, ...rest }) => rest);
    expect(READS.vendors.safeParse(withoutId).success).toBe(false);
  });

  it("fails when a field is renamed", () => {
    const rows = load("approvalRules") as Array<Record<string, unknown>>;
    const renamed = rows.map(({ auto_approve, ...rest }) => ({
      ...rest,
      autoApprove: auto_approve,
    }));
    const result = READS.approvalRules.safeParse(renamed);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path.join(".")).toContain("auto_approve");
    }
  });

  it("tolerates a field the backend ADDS, which must not break a live console", () => {
    // Deliberately asymmetric: removal breaks, addition does not.
    const rows = (load("vendors") as Array<Record<string, unknown>>).map((r) => ({
      ...r,
      newly_added_by_the_backend: "hello",
    }));
    expect(READS.vendors.safeParse(rows).success).toBe(true);
  });
});
