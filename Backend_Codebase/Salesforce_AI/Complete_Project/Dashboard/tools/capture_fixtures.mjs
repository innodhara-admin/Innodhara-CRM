/**
 * Capture real response payloads for the eleven untyped reads (P1 / A1).
 *
 *   node tools/capture_fixtures.mjs [--base http://127.0.0.1:8000]
 *
 * Eleven of the fifteen reads this console makes return `"schema": {}` in the
 * spec, so `src/api/reads.ts` is hand-written and there is no generated source
 * to check it against. These fixtures are the substitute: recorded from a real
 * backend, committed, and parsed by every read shape in `reads.test.ts`.
 *
 * It seeds a throwaway organisation with **one row in every entity** first.
 * An empty array validates under any shape and would prove nothing — the whole
 * point is to see the keys the handlers actually emit.
 *
 * Credentials come from the repo's own `.env` (or the environment). Nothing is
 * written to the fixtures but catalogue rows from an organisation this script
 * created and then deactivates.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DASHBOARD = dirname(HERE);
const REPO = dirname(DASHBOARD);
const OUT = join(DASHBOARD, "src", "api", "__fixtures__");

const argBase = process.argv.indexOf("--base");
const BASE = (argBase > -1 ? process.argv[argBase + 1] : "http://127.0.0.1:8000") + "/api/v1";

function fromDotEnv(key) {
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

let token = null;

async function call(method, path, body, { raw = false } = {}) {
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
  const parsed = text ? JSON.parse(text) : null;
  if (!res.ok && !raw) {
    throw new Error(`${method} ${path} → ${res.status} ${text.slice(0, 300)}`);
  }
  return parsed;
}

const stamp = String(Math.floor(Date.now() / 1000));
const slug = `fixtures-${stamp}`;
const domain = `fixtures${stamp}-example.com`;
const adminEmail = `admin@${domain}`;
const captured = {};

function save(name, payload) {
  captured[name] = payload;
  writeFileSync(join(OUT, `${name}.json`), JSON.stringify(payload, null, 2) + "\n", "utf-8");
  const shape = Array.isArray(payload)
    ? `${payload.length} row(s), keys: ${Object.keys(payload[0] ?? {}).join(", ")}`
    : `keys: ${Object.keys(payload ?? {}).length}`;
  console.log(`  ${name.padEnd(20)} ${shape}`);
}

mkdirSync(OUT, { recursive: true });

// ── Platform: create the throwaway org, then run the D18 chain ─────────────
const superEmail = fromDotEnv("SUPER_ADMIN_EMAIL");
const superPassword = fromDotEnv("SUPER_ADMIN_PASSWORD");
if (!superEmail || !superPassword) {
  console.error("SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD not found in env or ../.env");
  process.exit(1);
}

token = (await call("POST", "/auth/login", { email: superEmail, password: superPassword }))
  .access_token;
const org = await call("POST", "/orgs", {
  name: `Fixtures ${stamp}`,
  slug,
  email_domain: domain,
  admin_email: adminEmail,
  admin_name: "Fixture Admin",
});
const superToken = token;
token = (await call("POST", "/auth/login", {
  email: adminEmail,
  password: org.admin_temp_password,
})).access_token;
await call("POST", "/auth/change-password", {
  current_password: org.admin_temp_password,
  new_password: "fixtures-password",
});
console.log(`seeded org ${slug}\n`);

// ── Seed one row in every entity ───────────────────────────────────────────
const staff = await call("POST", "/admin/users", {
  email: `lead@${domain}`,
  name: "Ravi Menon",
  role: "operations_lead",
  department: "operations",
  designation: "Commissioning lead",
  whatsapp_number: "+919000000001",
  max_open_tasks: 12,
  working_days: ["mon", "tue", "wed", "thu", "fri"],
});
await call("POST", "/skills", { user_id: staff.id, skill: "rack-and-stack", level: "expert" });

const program = await call("POST", "/admin/programs", {
  name: "Datacentre commissioning",
  code: "DC-COMMISSION",
  description: "Commissioning and handover of capacity.",
});
await call("POST", `/admin/programs/${program.id}/pricing`, {
  currency: "INR",
  items: [
    { code: "RACK", label: "Rack commissioning", unit: "per rack", unit_price: 45000, default_quantity: 4 },
    // default_quantity omitted: the tri-state's "this org did not say" case
    // must appear in the fixture, or the read shape is never tested against it.
    { code: "AUDIT", label: "Capacity audit", unit: "per site", unit_price: 120000, notes: "Two-day survey" },
  ],
});
await call("POST", `/admin/programs/${program.id}/proposal-templates`, {
  name: "Standard commissioning",
  body_md: "## Scope\n\nCommissioning and handover for {{client_name}}.\n",
  make_current: true,
});
for (const [kind, channel, subject] of [
  ["intro", "email", "Introduction from our team"],
  ["intro", "whatsapp", null],
  ["follow_up", "email", "Following up"],
  ["follow_up", "whatsapp", null],
]) {
  await call("POST", "/admin/message-templates", {
    kind, channel, name: `${kind} ${channel}`,
    ...(subject ? { subject } : {}),
    body: "Hello {{contact_name}}, thank you for your time today.",
    make_current: true,
  });
}
await call("POST", "/playbooks", {
  program_id: program.id,
  phase: "preparation",
  entries: [
    { title: "Confirm site access", required_skill: "rack-and-stack", offset_days: -7, priority: "P1", visible_to_client: false },
  ],
});
await call("POST", "/approval-rules", {
  entity_type: "proposal",
  condition: { discount_pct_gt: 10 },
  rank: 10,
  approver_role: "sales_lead",
  fallback_role: "org_admin",     // change #9 — unreadable before it
  auto_approve: false,            // change #9
  recommender_role: "sales_agent",
  expires_hours: 48,
  description: "Discounts above 10% go to the sales lead.",
});
await call("POST", "/approval-rules", {
  entity_type: "proposal", condition: {}, rank: 100, approver_role: "org_admin",
  description: "Catch-all.",
});
await call("POST", "/admin/demo-teams", {
  name: "Commissioning crew",
  lead_user_id: staff.id,      // change #10 — ids unreadable before it
  media_rep_id: staff.id,
  sales_rep_id: staff.id,
  member_ids: [staff.id],
});
await call("POST", "/vendors", {
  name: "Northgate Logistics", contact_name: "Asha Rao",
  phone: "+919000000010", email: "asha@northgate-example.com",
  category: "transport", notes: "Two-day lead time.",
});
await call("PATCH", "/admin/settings", {
  timezone: "Asia/Kolkata",
  assignment_mode: "lead_confirm",
  working_days: ["mon", "tue", "wed", "thu", "fri"],
  nudge_gap_days: { first: 3, second: 7 },
  payment_reminder_schedule: [{ offset_days: 3, channel: "email" }],
});

// ── Capture ────────────────────────────────────────────────────────────────
console.log("captured:");
save("skills", await call("GET", "/skills"));
save("programs", await call("GET", "/admin/programs"));
save("pricing", await call("GET", `/admin/programs/${program.id}/pricing`));
save("proposalTemplates", await call("GET", `/admin/programs/${program.id}/proposal-templates`));
save("messageTemplates", await call("GET", "/admin/message-templates"));
save("playbooks", await call("GET", "/playbooks"));
save("approvalRules", await call("GET", "/approval-rules"));
save("settings", await call("GET", "/admin/settings"));
save("demoTeams", await call("GET", "/admin/demo-teams"));
save("vendors", await call("GET", "/vendors"));
save("resetDryRun", await call("POST", "/admin/reset", {
  dry_run: true, wipe_transactional: true, wipe_catalogue: true, wipe_org_config: true,
}));
// Typed, but the status derivation reads them too, and a fixture costs nothing.
save("staff", await call("GET", "/admin/users"));
save("me", await call("GET", "/auth/me"));

token = superToken;
await call("PATCH", `/orgs/${org.id}/active?active=false`, undefined, { raw: true });
console.log(`\ndeactivated ${slug}`);
