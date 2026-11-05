/**
 * Drive the reset and the reseed bundle against a real backend — Task 24 Step 6.
 *
 *   npx vite-node tools/verify_reset_bundle_live.ts -- --base http://127.0.0.1:9010
 *
 * `roundtrip.test.ts` proves the bundle round-trips over fixtures. This proves
 * the three things a fixture cannot:
 *
 *  1. the dry-run counts arrive under **all four buckets**, including the one
 *     no reset response mentions;
 *  2. **D22's conditional refusal actually fires** — on an organisation with
 *     real proposals, a catalogue-only apply is refused with the server's own
 *     message, and nothing is deleted;
 *  3. the **export → reset → re-import** loop completes, with an
 *     `auto_approve` rule still auto-approving and a demo team's three role ids
 *     still assigned — the two that changes #9 and #10 exist for.
 *
 * It imports `buildBundle`, `parseBundle` and the reset derivation themselves.
 * A script that reimplemented them would verify itself.
 *
 * ⚠ **Writes to the live database.** Creates a real organisation, seeds it,
 * destroys the seed, restores it, and deactivates the organisation on the way
 * out. `POST /orgs` has no inverse, so a `t24-<timestamp>` row remains.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { schemas } from "../src/api/generated";
import {
  ApprovalRulesRead,
  DemoTeamsRead,
  MessageTemplatesRead,
  PlaybooksRead,
  PricingRead,
  ProgramsRead,
  ProposalTemplatesRead,
  ResetRead,
  SkillsRead,
  VendorsRead,
} from "../src/api/reads";
import { RESET_TAXONOMY } from "../src/api/vocabularies.generated";
import {
  buildBundle,
  bundleTally,
  rowsFromReads,
  serialiseBundle,
} from "../src/bundle/export";
import { applyBundle, parseBundle } from "../src/bundle/import";
import { ALL_FLAGS, CATALOGUE_ONLY, bucketsFor, selectedTotal } from "../src/bundle/reset";
import { BUNDLE_ENTITIES, DESCRIPTORS } from "../src/descriptors";
import type { EntityKey } from "../src/descriptors/types";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = dirname(dirname(HERE));

const argBase = process.argv.indexOf("--base");
const BASE = (argBase > -1 ? process.argv[argBase + 1] : "http://127.0.0.1:8000") + "/api/v1";
const KEEP = process.argv.includes("--keep");

function fromDotEnv(key: string): string | undefined {
  if (process.env[key]) return process.env[key];
  try {
    const line = readFileSync(join(REPO, ".env"), "utf-8")
      .split(/\r?\n/)
      .find((l) => l.startsWith(`${key}=`));
    return line?.slice(key.length + 1).trim();
  } catch {
    return undefined;
  }
}

let token: string | null = null;

async function call<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${text.slice(0, 400)}`);
  return text ? JSON.parse(text) : (null as T);
}

/** Expects a refusal, and returns the server's message verbatim. */
async function expectRefusal(method: string, path: string, body: unknown): Promise<string> {
  const res = await fetch(BASE + path, {
    method,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (res.ok) throw new Error(`${method} ${path} was ACCEPTED and should have been refused`);
  const parsed = JSON.parse(text);
  return typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
}

/**
 * `request()` in `src/api/client.ts` reads its token and base URL from
 * `sessionStorage`, which does not exist here. The bundle applier calls it, so
 * the session module is primed with the same shape the browser holds.
 */
async function primeSession(baseUrl: string, org: {
  token: string; userId: string; name: string; role: string; orgId: string; orgName: string;
}) {
  const store: Record<string, string> = {};
  (globalThis as { sessionStorage?: unknown }).sessionStorage = {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v; },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
    key: () => null,
    length: 0,
  };
  const { session } = await import("../src/session/store");
  session.setBaseUrl(baseUrl);
  session.setOrg(org);
}

const MARK = { ok: "✓", no: "✗" };
const problems: string[] = [];
const check = (condition: boolean, what: string) => {
  console.log(`   ${condition ? MARK.ok : MARK.no} ${what}`);
  if (!condition) problems.push(what);
};

const stamp = String(Math.floor(Date.now() / 1000));
const slug = `t24-${stamp}`;
const domain = `t24org${stamp}-example.com`;
const adminEmail = `admin@${domain}`;

const superEmail = fromDotEnv("SUPER_ADMIN_EMAIL");
const superPassword = fromDotEnv("SUPER_ADMIN_PASSWORD");
if (!superEmail || !superPassword) {
  console.error("SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD not found");
  process.exit(1);
}

// ── The org, and its admin session ──────────────────────────────────────────
token = (await call("POST", "/auth/login", { email: superEmail, password: superPassword })).access_token;
const org = await call("POST", "/orgs", {
  name: `Task 24 ${stamp}`, slug, email_domain: domain,
  admin_email: adminEmail, admin_name: "Task 24 Admin",
});
const superToken: string = token!;
const login = await call("POST", "/auth/login", { email: adminEmail, password: org.admin_temp_password });
token = login.access_token;
await call("POST", "/auth/change-password", {
  current_password: org.admin_temp_password, new_password: "task24-password",
});
const me = schemas.MeResponse.parse(await call("GET", "/auth/me"));
console.log(`created ${slug}\n`);

await primeSession(BASE.replace("/api/v1", ""), {
  token: token!, userId: me.user_id, name: me.name, role: me.role,
  orgId: me.org_id!, orgName: me.org_name!,
});

// ── Seed a real organisation ────────────────────────────────────────────────
const ravi = await call("POST", "/admin/users", {
  email: `ravi@${domain}`, name: "Ravi Menon", role: "operations_lead", department: "operations",
});
const priya = await call("POST", "/admin/users", {
  email: `priya@${domain}`, name: "Priya Nair", role: "sales_lead", department: "sales",
});
await call("POST", "/skills", { user_id: ravi.id, skill: "rack-and-stack", level: "expert" });
await call("POST", "/skills", { user_id: priya.id, skill: "negotiation", level: "good" });

const commission = await call("POST", "/admin/programs", {
  name: "Datacentre commissioning", code: "DC-COMMISSION",
  description: "Commissioning and handover of capacity.",
});
await call("POST", "/admin/programs", {
  name: "Datacentre audit", code: "DC-AUDIT", description: "Independent audit of a hall.",
});
await call("POST", `/admin/programs/${commission.id}/pricing`, {
  currency: "INR",
  items: [{ code: "RACK", label: "Rack commissioning", unit: "per rack", unit_price: 45000, default_quantity: 4 }],
});
await call("POST", `/admin/programs/${commission.id}/proposal-templates`, {
  name: "Commissioning proposal", body_md: "# {{client_name}}\n\nScope of works and commercials.\n",
});
for (const [kind, channel] of [["intro", "email"], ["follow_up", "email"]] as const) {
  await call("POST", "/admin/message-templates", {
    kind, channel, name: `${kind} ${channel}`, subject: `About your ${kind}`,
    body: "Hello {{contact_name}},\n\nA note about the work.\n",
  });
}
await call("POST", "/playbooks", {
  program_id: commission.id, phase: "preparation",
  entries: [{ title: "Confirm site access", required_skill: "rack-and-stack", offset_days: -7, priority: "P1" }],
});
// An AUTO-APPROVING rule — change #9's whole point.
await call("POST", "/approval-rules", {
  entity_type: "proposal", condition: {}, rank: 100, approver_role: "sales_lead",
  fallback_role: "org_admin", auto_approve: true, expires_hours: 48,
  description: "Catch-all, auto-approved.",
});
// A demo team with all three roles by id — change #10's whole point.
await call("POST", "/admin/demo-teams", {
  name: "Commissioning squad", lead_user_id: ravi.id, media_rep_id: priya.id,
  sales_rep_id: ravi.id, member_ids: [ravi.id, priya.id],
});
await call("POST", "/vendors", {
  name: "Coolant Co", contact_name: "Meera", phone: "+919000000009",
  email: `meera@vendor-${stamp}.example`, category: "hvac", notes: "Chiller maintenance.",
});

// A REAL proposal, so `proposals.program_id -> programs` is a live edge.
const lead = await call("POST", "/leads", { name: "Meridian Datacentres", city: "Chennai", source: "referral" });
const proposal = await call("POST", "/proposals", { lead_id: lead.id, program_id: commission.id });
console.log(`seeded · proposal ${proposal.id} references ${commission.id}\n`);

// ── 1 · The dry run, under all four buckets ────────────────────────────────
console.log("1 · Dry run — counts under all four buckets");
const previewAll = ResetRead.parse(await call("POST", "/admin/reset", { dry_run: true, ...ALL_FLAGS }));
const views = bucketsFor(previewAll, ALL_FLAGS);
for (const v of views) {
  const shown = v.total === null ? "no counts reported" : `${v.total} rows`;
  console.log(`   ${v.bucket.padEnd(8)} ${String(v.tables.length).padStart(2)} tables · ${shown}`);
  for (const t of v.nonEmpty) console.log(`      ${t.table} ${t.count}`);
}
check(views.length === 4, "all four buckets are rendered");
check(views.map((v) => v.bucket).includes("KEEP"), "KEEP appears, though no response mentions it");
check(views.find((v) => v.bucket === "KEEP")!.total === null, "KEEP carries no counts rather than zeros");
check(
  views.flatMap((v) => v.tables).length === 55,
  "the four buckets cover all 55 tables",
);
check(selectedTotal(previewAll, ALL_FLAGS) === previewAll.total,
  "the selected total agrees with the server's own total when all three are ticked");
check(previewAll.applied === false, "a dry run reports applied: false");

// ── 2 · D22's conditional refusal ──────────────────────────────────────────
console.log("\n2 · D22 — catalogue-only, on an organisation with proposals");
const catalogueOnly = ResetRead.parse(await call("POST", "/admin/reset", { dry_run: true, ...CATALOGUE_ONLY }));
console.log(`   blocking_edges: ${JSON.stringify(catalogueOnly.blocking_edges)}`);
check(catalogueOnly.blocking_edges.length > 0, "the dry run REPORTS the edges");
check(
  catalogueOnly.blocking_edges.some((e) => e.table === "proposals" && e.references === "programs"),
  "proposals.program_id -> programs is among them",
);
check(previewAll.blocking_edges.length === 0,
  "the all-three dry run reports none — the check is skipped when transactional is also wiped");

const refusal = await expectRefusal("POST", "/admin/reset", {
  dry_run: false, ...CATALOGUE_ONLY, confirm_org_name: org.name,
});
console.log(`   refusal: ${refusal}`);
check(refusal.includes("Catalogue reset refused"), "the APPLY is refused");
check(refusal.includes("proposals.program_id"), "the refusal names the edge");
const afterRefusal = ProgramsRead.parse(await call("GET", "/admin/programs"));
check(afterRefusal.length === 2, "nothing was deleted by the refused apply");

// ── 3 · Export ─────────────────────────────────────────────────────────────
console.log("\n3 · Export the bundle");
const WRITE_FIELDS = Object.fromEntries(
  BUNDLE_ENTITIES.map((key) => {
    const shape = (schemas[DESCRIPTORS[key].writeSchema] as { shape?: object }).shape;
    return [key, shape ? Object.keys(shape) : []];
  }),
) as Partial<Record<EntityKey, readonly string[]>>;

async function readEverything() {
  const programs = ProgramsRead.parse(await call("GET", "/admin/programs"));
  const activeIds = programs.filter((p) => p.is_active).map((p) => p.id);
  const pricingByProgram: Record<string, any[]> = {};
  const templatesByProgram: Record<string, any[]> = {};
  for (const id of activeIds) {
    pricingByProgram[id] = PricingRead.parse(await call("GET", `/admin/programs/${id}/pricing`));
    templatesByProgram[id] = ProposalTemplatesRead.parse(
      await call("GET", `/admin/programs/${id}/proposal-templates`),
    );
  }
  return {
    programs,
    programRows: programs as unknown as Record<string, unknown>[],
    skills: SkillsRead.parse(await call("GET", "/skills")) as unknown as Record<string, unknown>[],
    pricingByProgram,
    templatesByProgram,
    messageTemplates: MessageTemplatesRead.parse(await call("GET", "/admin/message-templates")) as unknown as Record<string, unknown>[],
    playbooks: PlaybooksRead.parse(await call("GET", "/playbooks")) as unknown as Record<string, unknown>[],
    approvalRules: ApprovalRulesRead.parse(await call("GET", "/approval-rules")) as unknown as Record<string, unknown>[],
    demoTeams: DemoTeamsRead.parse(await call("GET", "/admin/demo-teams")) as unknown as Record<string, unknown>[],
    vendors: VendorsRead.parse(await call("GET", "/vendors")) as unknown as Record<string, unknown>[],
  };
}

const before = await readEverything();
const bundle = buildBundle({
  org: { id: me.org_id!, name: me.org_name! },
  rows: rowsFromReads(before),
  writeFields: WRITE_FIELDS,
});
for (const t of bundleTally(bundle)) console.log(`   ${t.key.padEnd(20)} ${t.rows}`);
check(Object.keys(bundle.entities).length === 9, "the bundle carries nine entity types");
check(BUNDLE_ENTITIES.length === 9, "BUNDLE_ENTITIES.length is nine, derived from the descriptors");
const ruleBefore = bundle.entities.approvalRules[0] as Record<string, unknown>;
const teamBefore = bundle.entities.demoTeams[0] as Record<string, unknown>;
check(ruleBefore.auto_approve === true, "the exported rule is auto-approving");
check(teamBefore.lead_user_id === ravi.id, "the exported team carries lead_user_id");

// ── 4 · Reset, all three flags ─────────────────────────────────────────────
console.log("\n4 · Reset — all three flags");
const applied = ResetRead.parse(await call("POST", "/admin/reset", {
  dry_run: false, ...ALL_FLAGS, confirm_org_name: org.name,
}));
console.log(`   removed ${applied.total} rows`);
check(applied.applied === true, "the reset reports applied: true");
const emptied = await readEverything();
check(emptied.programs.length === 0, "programmes are gone");
check(emptied.approvalRules.length === 0, "approval rules are gone");
check(emptied.demoTeams.length === 0, "demo teams are gone");
check(emptied.skills.length === 0, "skills are gone");
const staffAfterReset = schemas.UserResponse.array().parse(await call("GET", "/admin/users"));
check(staffAfterReset.length === 3, "staff accounts survived, all three of them");

// ── 5 · Re-import ──────────────────────────────────────────────────────────
console.log("\n5 · Re-import the bundle");
const parsed = parseBundle(serialiseBundle(bundle), { orgId: me.org_id!, orgName: me.org_name! });
if ("fatal" in parsed) {
  console.error(`   the bundle was refused: ${parsed.why}`);
  process.exit(1);
}
const report = await applyBundle({ parsed });
for (const o of report.outcomes) {
  if (o.status === "refused") console.log(`   ${MARK.no} ${o.key} ${o.label} — ${o.message}`);
}
console.log(`   ${report.applied} restored · ${report.refused} refused`);
check(report.refused === 0, "every row was restored");

const after = await readEverything();
check(after.programs.length === before.programs.length, "the programmes are back");
check(after.skills.length === before.skills.length, "the skills are back");
check(after.vendors.length === before.vendors.length, "the vendors are back");
check(after.playbooks.length === before.playbooks.length, "the playbooks are back");

// The two the changes were made for, checked by hand as Step 6 demands.
const ruleAfter = after.approvalRules[0] as Record<string, unknown>;
check(ruleAfter?.auto_approve === true, "the restored rule is STILL auto-approving (change #9)");
check(ruleAfter?.fallback_role === "org_admin", "the restored rule kept its fallback approver (change #9)");
const teamAfter = after.demoTeams[0] as Record<string, unknown>;
check(teamAfter?.lead_user_id === ravi.id, "the restored team's lead is still assigned, by id (change #10)");
check(teamAfter?.media_rep_id === priya.id, "the restored team's media rep is still assigned (change #10)");
check(teamAfter?.sales_rep_id === ravi.id, "the restored team's sales rep is still assigned (change #10)");

// Programme ids changed, and everything that hangs off one followed.
const newCommission = after.programs.find((p) => p.code === "DC-COMMISSION")!;
check(newCommission.id !== commission.id, "the restored programme has a NEW id, as expected");
check(
  (after.playbooks[0] as Record<string, unknown>)?.program_id === newCommission.id,
  "the restored playbook points at the new programme id, not the old one",
);
check(
  (after.pricingByProgram[newCommission.id] ?? []).some((v: any) => v.is_current),
  "the restored rate card is attached to the new programme and is current",
);

// ── Cleanup ────────────────────────────────────────────────────────────────
token = superToken;
if (KEEP) {
  console.log(`\n--keep: ${slug} still ACTIVE · ${adminEmail} / task24-password · org ${org.id}`);
} else {
  await call("PATCH", `/orgs/${org.id}/active?active=false`);
}

console.log(
  problems.length === 0
    ? `\nOK — four buckets, D22 refused a real catalogue-only reset, and the ` +
      `export/reset/re-import loop closed against ${slug}.`
    : `\nFAILED:\n  ${problems.join("\n  ")}`,
);
process.exit(problems.length === 0 ? 0 : 1);
