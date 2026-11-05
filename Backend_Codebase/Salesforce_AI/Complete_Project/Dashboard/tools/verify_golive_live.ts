/**
 * Drive the go-live check against a real backend — 07_BUILD_PLAN.md Task 23.
 *
 *   npx vite-node tools/verify_golive_live.ts [--base http://127.0.0.1:8000]
 *
 * `golive.test.ts` runs the derivation against committed fixtures, which proves
 * it agrees with payloads a backend once produced. This proves something the
 * unit tests cannot: that the **live** shapes still feed it, and that the case
 * the whole console exists for — a playbook asking for a skill whose only
 * holder has been deactivated — is reported as uncovered against a real
 * organisation rather than against a hand-built object.
 *
 * TypeScript rather than `.mjs` (which `capture_fixtures.mjs` is) because it
 * imports `runGoLive` and the read shapes from `src/`. Running the real
 * function is the entire point: a script that reimplemented the check would
 * verify itself.
 *
 * ⚠ **This writes to the live database**, exactly as `capture_fixtures.mjs`
 * does. It creates a real organisation, seeds a deliberately incomplete one,
 * and deactivates it on the way out. `POST /orgs` has no inverse, so a
 * `t23-<timestamp>` row remains in `GET /orgs` afterwards.
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
  SettingsRead,
  SkillsRead,
  VendorsRead,
} from "../src/api/reads";
import { runGoLive } from "../src/checklist/golive";
import type { ChecklistReads, Read } from "../src/checklist/status";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = dirname(dirname(HERE));

const argBase = process.argv.indexOf("--base");
const BASE =
  (argBase > -1 ? process.argv[argBase + 1] : "http://127.0.0.1:8000") + "/api/v1";

/**
 * `--keep` leaves the organisation ACTIVE so the same data can be driven
 * through `/dashboard/#/go-live` in a browser.
 *
 * The ordering is not a preference: `deps.py · get_org_context` refuses an
 * inactive organisation (`:61`), so an org deactivated before the browser check
 * 403s every read the screen makes. Deactivating must come last, which means
 * skipping it here and doing it by hand afterwards.
 */
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
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : (null as T);
}

const ok = <T>(value: T): Read<T> => ({ state: "ok", value });

const stamp = String(Math.floor(Date.now() / 1000));
const slug = `t23-${stamp}`;
const domain = `t23org${stamp}-example.com`;
const adminEmail = `admin@${domain}`;

const superEmail = fromDotEnv("SUPER_ADMIN_EMAIL");
const superPassword = fromDotEnv("SUPER_ADMIN_PASSWORD");
if (!superEmail || !superPassword) {
  console.error("SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD not found in env or ../.env");
  process.exit(1);
}

// ── The D18 chain, programmatically ─────────────────────────────────────────
token = (await call("POST", "/auth/login", { email: superEmail, password: superPassword }))
  .access_token;
const org = await call("POST", "/orgs", {
  name: `Task 23 ${stamp}`,
  slug,
  email_domain: domain,
  admin_email: adminEmail,
  admin_name: "Task 23 Admin",
});
const superToken: string = token!;
token = (
  await call("POST", "/auth/login", {
    email: adminEmail,
    password: org.admin_temp_password,
  })
).access_token;
await call("POST", "/auth/change-password", {
  current_password: org.admin_temp_password,
  new_password: "task23-password",
});
console.log(`created ${slug} (email_domain ${org.email_domain})\n`);

// ── A deliberately incomplete organisation ─────────────────────────────────
//
// Every gap below is one the plan's Step 7 names, arranged so the six checks
// each have something real to find.

const ravi = await call("POST", "/admin/users", {
  email: `ravi@${domain}`,
  name: "Ravi Menon",
  role: "operations_lead",
  department: "operations",
});
const priya = await call("POST", "/admin/users", {
  email: `priya@${domain}`,
  name: "Priya Nair",
  role: "operations_agent",
  department: "operations",
});

await call("POST", "/skills", { user_id: ravi.id, skill: "rack-and-stack", level: "expert" });
// The gap that matters: Priya is the ONLY holder of cable-management.
await call("POST", "/skills", { user_id: priya.id, skill: "cable-management", level: "good" });

const commission = await call("POST", "/admin/programs", {
  name: "Datacentre commissioning",
  code: "DC-COMMISSION",
  description: "Commissioning and handover of capacity.",
});
// A second offering with no rate card at all — check 2's ○ case.
const audit = await call("POST", "/admin/programs", {
  name: "Datacentre audit",
  code: "DC-AUDIT",
  description: "Independent audit of an existing hall.",
});

await call("POST", `/admin/programs/${commission.id}/pricing`, {
  currency: "INR",
  items: [
    {
      code: "RACK",
      label: "Rack commissioning",
      unit: "per rack",
      unit_price: 45000,
      default_quantity: 4,
    },
  ],
});
await call("POST", `/admin/programs/${commission.id}/proposal-templates`, {
  name: "Commissioning proposal",
  body_md: "# {{client_name}}\n\nScope: {{scope}}\n",
});

await call("POST", "/playbooks", {
  program_id: commission.id,
  phase: "preparation",
  entries: [
    { title: "Confirm site access", required_skill: "rack-and-stack", offset_days: -7, priority: "P1" },
    { title: "Dress and label cabling", required_skill: "cable-management", offset_days: -3, priority: "P2" },
    { title: "Confirm the hall is powered", required_skill: "power-commissioning", offset_days: -5, priority: "P1" },
    { title: "Send the kickoff note", offset_days: 0, priority: "P3" },
  ],
});

// Three of four kind × channel — check 3.
for (const [kind, channel] of [
  ["intro", "email"],
  ["intro", "whatsapp"],
  ["follow_up", "email"],
] as const) {
  await call("POST", "/admin/message-templates", {
    kind,
    channel,
    name: `${kind} ${channel}`,
    subject: channel === "email" ? `About your ${kind}` : null,
    body: "Hello {{contact_name}},\n\n{{body}}\n",
  });
}

// A proposal rule with a condition and NO catch-all — check 4's worst case,
// because proposals.py passes default_approver_role=None.
await call("POST", "/approval-rules", {
  entity_type: "proposal",
  condition: { discount_pct_gt: 10 },
  rank: 10,
  approver_role: "sales_lead",
  fallback_role: "org_admin",
  expires_hours: 48,
  description: "Discounts above 10% go to the sales lead.",
});

// ── The gap, applied last so everything above was created legitimately ──────
await call("PATCH", `/admin/users/${priya.id}`, { is_active: false });
console.log("deactivated Priya Nair — cable-management now has no active holder\n");

// ── Read exactly what the console reads, through the same shapes ────────────
const programs = ProgramsRead.parse(await call("GET", "/admin/programs"));
const activeIds = programs.filter((p) => p.is_active).map((p) => p.id);

const reads: ChecklistReads = {
  me: ok(schemas.MeResponse.parse(await call("GET", "/auth/me"))),
  staff: ok(schemas.UserResponse.array().parse(await call("GET", "/admin/users"))),
  skills: ok(SkillsRead.parse(await call("GET", "/skills"))),
  programs: ok(programs),
  pricing: ok(
    Object.fromEntries(
      await Promise.all(
        activeIds.map(async (id) => [
          id,
          PricingRead.parse(await call("GET", `/admin/programs/${id}/pricing`)),
        ]),
      ),
    ),
  ),
  proposalTemplates: ok(
    Object.fromEntries(
      await Promise.all(
        activeIds.map(async (id) => [
          id,
          ProposalTemplatesRead.parse(
            await call("GET", `/admin/programs/${id}/proposal-templates`),
          ),
        ]),
      ),
    ),
  ),
  messageTemplates: ok(MessageTemplatesRead.parse(await call("GET", "/admin/message-templates"))),
  playbooks: ok(PlaybooksRead.parse(await call("GET", "/playbooks"))),
  approvalRules: ok(ApprovalRulesRead.parse(await call("GET", "/approval-rules"))),
  settings: ok(SettingsRead.parse(await call("GET", "/admin/settings"))),
  demoTeams: ok(DemoTeamsRead.parse(await call("GET", "/admin/demo-teams"))),
  vendors: ok(VendorsRead.parse(await call("GET", "/vendors"))),
};

// ── The real function, over the real payloads ──────────────────────────────
const MARK = { done: "●", partial: "◐", none: "○", blocked: "—", pending: "·" } as const;

// Source 1 of A6: the domain POST /orgs returned to this process, which is
// exactly what the console's session holds after the hand-off.
for (const check of runGoLive(reads, { emailDomain: org.email_domain })) {
  console.log(`${MARK[check.marker]} ${check.n} · ${check.title}`);
  console.log(`    ${check.summary}`);
  for (const row of check.rows) {
    console.log(`    ${MARK[row.marker]} ${row.subject} — ${row.detail}`);
  }
  if (check.source) console.log(`    answered from: ${check.source}`);
  console.log();
}

// ── Assert the one that justifies the console ──────────────────────────────
const skillCheck = runGoLive(reads, { emailDomain: org.email_domain })[0];
const cable = skillCheck.rows.find((r) => r.subject === "cable-management");
const problems: string[] = [];
if (skillCheck.marker !== "none") problems.push(`check 1 marker is ${skillCheck.marker}, want none`);
if (!cable) problems.push("no cable-management row");
else {
  if (cable.marker !== "none") problems.push(`cable-management is ${cable.marker}, want none`);
  if (!cable.detail.includes("Priya Nair")) problems.push("does not name the deactivated holder");
  if (!cable.detail.includes("deactivated")) problems.push("does not say the holder is deactivated");
}
// And the control: the skill an ACTIVE person holds must still be covered, or
// the check is simply reporting everything as broken.
const rack = skillCheck.rows.find((r) => r.subject === "rack-and-stack");
if (rack?.marker !== "done") problems.push(`rack-and-stack is ${rack?.marker}, want done`);
// `GET /skills` returns Priya's row either way — the join is what makes the
// difference, so prove the row is genuinely still there.
const skillRows = reads.skills.state === "ok" ? reads.skills.value : [];
if (!skillRows.some((s) => s.user_id === priya.id && s.skill === "cable-management")) {
  problems.push("GET /skills no longer returns the deactivated holder's row — the case is not being exercised");
}

// ── Deactivate the organisation LAST (deps.py · get_org_context refuses an
//    inactive org, so anything after this 403s) ──────────────────────────────
token = superToken;
if (KEEP) {
  console.log(
    `--keep: ${slug} is still ACTIVE. Sign in as ${adminEmail} / task23-password,
` +
      `   then deactivate with PATCH /orgs/${org.id}/active?active=false as super admin.`,
  );
} else {
  await call("PATCH", `/orgs/${org.id}/active?active=false`);
}

if (problems.length > 0) {
  console.error("FAILED:\n  " + problems.join("\n  "));
  process.exit(1);
}
console.log(
  `OK — a playbook skill whose only holder is deactivated reads UNCOVERED against ${slug},\n` +
    `   while a skill an active person holds reads covered.` +
    (KEEP ? "" : " Organisation deactivated."),
);
