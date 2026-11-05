/**
 * Status derivation — 06_DESIGN.md §5.2. **Pure functions over real API reads.**
 *
 * ## The one rule
 *
 * **No local "I did that" flags.** A status this console cannot verify against
 * the API is never shown as done. Every marker below is a statement about what
 * a read actually returned a moment ago, which is why this file takes the reads
 * as an argument instead of fetching them.
 *
 * ## Four markers, and the two that must never be confused (§6)
 *
 * - `●` satisfied · `○` not started · `◐` partial, or true but unverifiable
 * - `—` **this console cannot answer**, which is a different fact from `○`.
 *
 * `—` is used for exactly two things: item 16, which no API can satisfy, and a
 * read that failed to parse or failed outright. A drifted read rendering as
 * `○` would tell an operator their organisation is empty when in fact the
 * console has gone blind, so `unreadable` never collapses into `none` (A1).
 *
 * `pending` is a fifth value and is deliberately not one of §6's markers: it is
 * a rendering state, not a status. It exists because the alternative — showing
 * `○` while a read is in flight — is the optimism this file is written to
 * prevent. The rail mutes those rows and says "reading".
 *
 * ## Three cases carry the whole honesty model
 *
 * - **Item 1 derives from `GET /auth/me` alone** (P6/A5). §5.2 originally said
 *   `GET /orgs`, which is super-admin-only and unreachable from the session
 *   that runs this console.
 * - **Item 10 is `◐` when every dial still equals its model default**, because
 *   the API cannot distinguish "deliberately left alone" from "never looked at".
 * - **Item 11 is compound and never `●` on `dry_run`** — the failure the manual
 *   warns about twice, and the reason backend change #2 exists.
 */
import type { z } from "zod";

import type { schemas } from "../api/generated";
import type {
  ApprovalRules,
  DemoTeams,
  EmailTemplates,
  MessageTemplates,
  Playbooks,
  Pricing,
  Programs,
  ProposalTemplates,
  Settings,
  Skills,
  Vendors,
} from "../api/reads";
import { SETTINGS_DEFAULTS } from "../api/vocabularies.generated";
import type { ChecklistItem } from "./items";

export type Me = z.infer<typeof schemas.MeResponse>;
export type StaffRow = z.infer<typeof schemas.UserResponse>;

export type Marker = "done" | "partial" | "none" | "blocked" | "pending";

export type ItemStatus = {
  marker: Marker;
  /** One line, rendered next to the row. Names values, never adjectives. */
  caption: string;
};

/**
 * What one read is currently worth. `unreadable` covers both a shape that no
 * longer parses (drift) and a request that failed — from the operator's side
 * they are the same fact: this console cannot answer for that item right now.
 */
export type Read<T> =
  | { state: "pending" }
  | { state: "ok"; value: T }
  | { state: "unreadable"; why: string };

export type ChecklistReads = {
  me: Read<Me>;
  staff: Read<StaffRow[]>;
  skills: Read<Skills>;
  programs: Read<Programs>;
  /** Per program id — items 5 and 6 are the only per-program reads. */
  pricing: Read<Record<string, Pricing>>;
  proposalTemplates: Read<Record<string, ProposalTemplates>>;
  messageTemplates: Read<MessageTemplates>;
  /** Word email templates (28 Oct 2026), item 7. */
  emailTemplates: Read<EmailTemplates>;
  playbooks: Read<Playbooks>;
  approvalRules: Read<ApprovalRules>;
  settings: Read<Settings>;
  demoTeams: Read<DemoTeams>;
  vendors: Read<Vendors>;
};

export const PENDING_READS: ChecklistReads = {
  me: { state: "pending" },
  staff: { state: "pending" },
  skills: { state: "pending" },
  programs: { state: "pending" },
  pricing: { state: "pending" },
  proposalTemplates: { state: "pending" },
  messageTemplates: { state: "pending" },
  emailTemplates: { state: "pending" },
  playbooks: { state: "pending" },
  approvalRules: { state: "pending" },
  settings: { state: "pending" },
  demoTeams: { state: "pending" },
  vendors: { state: "pending" },
};

/**
 * The old message templates item 7 still needs (28 Oct 2026). The card scan
 * drafts its intro from intro/email and intro/whatsapp, and a WhatsApp
 * follow-up still starts from follow_up/whatsapp. Email follow-ups moved to
 * the Word email templates, so follow_up/email is no longer one of them. A
 * literal list on purpose: which old templates are still in use is a fact
 * about the code, not a vocabulary the backend enforces.
 */
export const STILL_USED_OLD_TEMPLATES = [
  { kind: "intro", channel: "email" },
  { kind: "intro", channel: "whatsapp" },
  { kind: "follow_up", channel: "whatsapp" },
] as const;

/** What item 7 is missing, in words: "intro/whatsapp", "a Word email template". */
export function templatesMissing(
  messageTemplates: MessageTemplates,
  emailTemplates: EmailTemplates,
): string[] {
  const current = messageTemplates.filter((t) => t.is_current);
  const missing: string[] = STILL_USED_OLD_TEMPLATES.filter(
    (w) => !current.some((r) => r.kind === w.kind && r.channel === w.channel),
  ).map((w) => `${w.kind}/${w.channel}`);
  if (!emailTemplates.some((t) => t.is_current)) missing.push("a Word email template");
  return missing;
}

const done = (caption: string): ItemStatus => ({ marker: "done", caption });
const partial = (caption: string): ItemStatus => ({ marker: "partial", caption });
const none = (caption: string): ItemStatus => ({ marker: "none", caption });
const blocked = (caption: string): ItemStatus => ({ marker: "blocked", caption });
const PENDING: ItemStatus = { marker: "pending", caption: "reading…" };

/**
 * Returns a blocking status when any read this item needs is missing, or null
 * when they are all present. `unreadable` outranks `pending`: once a read has
 * failed, the honest answer is "cannot be read", not "still trying".
 */
function blockedBy(...reads: Array<Read<unknown>>): ItemStatus | null {
  for (const r of reads) {
    if (r.state === "unreadable") return blocked(r.why);
  }
  for (const r of reads) {
    if (r.state === "pending") return PENDING;
  }
  return null;
}

/** Only ever called after `blockedBy` has cleared the same read. */
function value<T>(read: Read<T>): T {
  if (read.state !== "ok") throw new Error("read is not resolved");
  return read.value;
}

const plural = (n: number, one: string, many = `${one}s`) =>
  `${n} ${n === 1 ? one : many}`;

/**
 * Deep equality with key order ignored — item 10 compares `nudge_gap_days`,
 * `working_days` and `payment_reminder_schedule` against the model defaults,
 * and a JSON round trip through SQLite gives no guarantee about the order keys
 * come back in. Comparing serialised strings would report a dial as "changed"
 * because a dict was re-serialised.
 */
function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => deepEqual(x, b[i]));
  }
  if (typeof a !== "object") return false;
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  const ak = Object.keys(ao);
  const bk = Object.keys(bo);
  if (ak.length !== bk.length) return false;
  return ak.every((k) => k in bo && deepEqual(ao[k], bo[k]));
}

/**
 * The three dials `POST /orgs` writes from the **server's** environment rather
 * than from any model default — `organisations.py`'s `OrgSettings(...)` call,
 * fed by `default_audio_retention_days`, `default_transcript_retention_days`
 * and `llm_default_org_monthly_budget_usd`.
 *
 * They matter to item 10 because they break its comparison in the one direction
 * §5.2 did not anticipate. On a server whose `.env` sets a budget of 3.0 against
 * the model's 50.0, a brand-new organisation reads as "a dial was changed" and
 * ticks green, with nobody having opened the settings screen. That is the same
 * lie as showing untouched defaults as done, so a difference confined to these
 * three is `◐` and says which they are. **Verified in a browser against a
 * freshly created organisation**, which is how it was found at all.
 *
 * **This is a pattern, not a one-off (P12).** Any status claiming "the operator
 * chose this" from a column `POST /orgs` seeds is making a claim the API cannot
 * support. The full audit of what org creation writes:
 *
 * | Seeded | Read by | Treatment |
 * |---|---|---|
 * | these three `org_settings` columns | item 10 | carved out here |
 * | `audio_retention_days`, `transcript_retention_days` again | **item 12** | can *never* be verified — see case 12 |
 * | one `users` row, the org admin | item 2 | excluded from "staff besides the admin" |
 * | `organisations.name` / `slug` / `email_domain` | item 1 | fine: the operator supplied them to `POST /orgs`, and item 1 asserts only that an org exists and the session is live |
 *
 * Nothing else in the checklist reads a column org creation touches.
 */
const ENV_SEEDED = new Set<keyof typeof SETTINGS_DEFAULTS>([
  "audio_retention_days",
  "transcript_retention_days",
  "llm_monthly_budget_usd",
]);

/**
 * Items 11 and 14 are the same shape of fact and the same trap: stored
 * credentials plus a process-wide mode. `email_service.py` returns a
 * `dry_run:<path>` file unless **both** hold, and `calendar_service.py` does
 * the same against `calendar_mode != "google"`.
 *
 * Derived from the two halves rather than from `email_integration_configured`
 * — which change #2 made honest — because the caption has to say *which* half
 * is missing, and one boolean cannot.
 *
 * **Exported for the go-live check** (§5.6 check 5, "the compound email and
 * calendar statuses from §5.2"). Two derivations of the same fact is how the
 * rail and the go-live sheet would come to disagree about whether mail leaves
 * the building, which is the one thing this console exists to be right about.
 */
export function compound(opts: {
  credentialsStored: boolean;
  mode: string;
  liveMode: string;
  envVar: string;
  /** What does not leave when the mode is off. */
  noun: string;
  /** Where it goes instead. */
  instead: string;
}): ItemStatus {
  const { credentialsStored, mode, liveMode, envVar, noun, instead } = opts;
  const sending = mode === liveMode;
  const modeSuffix = `(${envVar}=${mode})`;

  if (credentialsStored && sending) {
    return done(`credentials stored · sending is ON ${modeSuffix}`);
  }
  if (credentialsStored) {
    return partial(
      `credentials stored · sending is OFF on this server ${modeSuffix} — ${noun} ${instead}`,
    );
  }
  if (sending) {
    return partial(
      `sending is ON ${modeSuffix} · no credentials stored, so ${noun} ${instead} anyway`,
    );
  }
  return none(
    `no credentials stored · sending is OFF on this server ${modeSuffix}`,
  );
}

/** Which programmes a per-program item still has nothing for. */
function coverage(
  programs: Programs,
  has: (programId: string) => boolean,
): { active: Programs; missing: Programs } {
  const active = programs.filter((p) => p.is_active);
  return { active, missing: active.filter((p) => !has(p.id)) };
}

function perProgram(
  reads: ChecklistReads,
  has: (programId: string) => boolean,
  words: { nothing: string; some: string; all: string },
): ItemStatus {
  const { active, missing } = coverage(value(reads.programs), has);
  if (active.length === 0) {
    // Vacuously true is not done. Zero programmes means zero rate cards, and
    // reporting that as satisfied would tick an item the operator has not
    // reached — this row is waiting on item 4, and says so.
    return none(words.nothing);
  }
  if (missing.length === active.length) {
    return none(`${words.some} · none of ${plural(active.length, "offering")} has one`);
  }
  if (missing.length > 0) {
    return partial(
      `${active.length - missing.length} of ${plural(active.length, "offering")} covered · missing: ${missing
        .map((p) => p.code)
        .join(", ")}`,
    );
  }
  return done(`${words.all} for all ${plural(active.length, "offering")}`);
}

/**
 * One row's status. Pure: same reads in, same `{marker, caption}` out.
 */
export function deriveStatus(item: ChecklistItem, reads: ChecklistReads): ItemStatus {
  switch (item.n) {
    // ── 1 · Organisation and its first administrator ──────────────────────
    case 1: {
      const stop = blockedBy(reads.me);
      if (stop) return stop;
      const me = value(reads.me);
      if (!me.org_id) {
        // A super-admin session reaches this console with no organisation.
        return none("signed in, but no organisation is selected");
      }
      return done(`${me.org_name ?? me.org_id} · signed in as ${me.name} (${me.role})`);
    }

    // ── 2 · Staff accounts, with the right role ───────────────────────────
    case 2: {
      const stop = blockedBy(reads.staff, reads.me);
      if (stop) return stop;
      const me = value(reads.me);
      const active = value(reads.staff).filter((u) => u.is_active);
      const others = active.filter((u) => u.id !== me.user_id);
      if (others.length === 0) {
        return none("nobody but the administrator");
      }
      // The department check covers the administrator too: they are a person
      // whose escalations have to reach somewhere, and the manual asks for it
      // per person, not per non-admin.
      const noDepartment = active.filter((u) => !u.department);
      if (noDepartment.length > 0) {
        return partial(
          `${plural(active.length, "active account")} · ${noDepartment.length} with no department (${noDepartment
            .map((u) => u.name)
            .join(", ")}) — their escalations have nowhere to go`,
        );
      }
      return done(`${plural(active.length, "active account")}, each with a department`);
    }

    // ── 3 · A skill on every person's record ──────────────────────────────
    case 3: {
      const stop = blockedBy(reads.skills, reads.staff);
      if (stop) return stop;
      const active = value(reads.staff).filter((u) => u.is_active);
      const held = new Set(value(reads.skills).map((s) => s.user_id));
      const covered = active.filter((u) => held.has(u.id));
      if (active.length === 0) return none("no active people to give a skill to");
      if (covered.length === 0) {
        return none(
          "nobody holds a skill — every task routes to the phase lead at low confidence",
        );
      }
      if (covered.length < active.length) {
        return partial(
          `${covered.length} of ${plural(active.length, "person", "people")} hold a skill · the other ${
            active.length - covered.length
          } route to the phase lead`,
        );
      }
      return done(
        `all ${plural(active.length, "person", "people")} hold at least one skill · ${plural(
          value(reads.skills).length,
          "skill row",
        )}`,
      );
    }

    // ── 4 · What you sell ─────────────────────────────────────────────────
    case 4: {
      const stop = blockedBy(reads.programs);
      if (stop) return stop;
      const active = value(reads.programs).filter((p) => p.is_active);
      if (active.length === 0) return none("nothing to sell yet");
      const noDescription = active.filter((p) => !p.description?.trim());
      if (noDescription.length > 0) {
        // The description is what the AI reads to match a conversation to an
        // offering (`02` §4). An offering with none is created but unmatchable,
        // which is a partial, not a tick.
        return partial(
          `${plural(active.length, "active offering")} · ${noDescription.length} with no description, which is what the AI matches a conversation against`,
        );
      }
      return done(`${plural(active.length, "active offering")}, all described`);
    }

    // ── 5 · A rate card for each offering ─────────────────────────────────
    case 5: {
      const stop = blockedBy(reads.programs, reads.pricing);
      if (stop) return stop;
      const byProgram = value(reads.pricing);
      return perProgram(
        reads,
        (id) => (byProgram[id] ?? []).some((t) => t.is_current),
        {
          nothing: "no offering to price yet — item 4 comes first",
          some: "no rate card",
          all: "a current rate card",
        },
      );
    }

    // ── 6 · A proposal template for each offering ─────────────────────────
    case 6: {
      const stop = blockedBy(reads.programs, reads.proposalTemplates);
      if (stop) return stop;
      const byProgram = value(reads.proposalTemplates);
      return perProgram(
        reads,
        (id) => (byProgram[id] ?? []).some((t) => t.is_current),
        {
          nothing: "no offering to write a template for yet — item 4 comes first",
          some: "no proposal template",
          all: "a current proposal template",
        },
      );
    }

    // ── 7 · Message templates: introduction and follow-up ─────────────────
    case 7: {
      const stop = blockedBy(reads.messageTemplates, reads.emailTemplates);
      if (stop) return stop;
      const missing = templatesMissing(
        value(reads.messageTemplates),
        value(reads.emailTemplates),
      );
      const wanted = STILL_USED_OLD_TEMPLATES.length + 1;
      if (missing.length === wanted) {
        return none(`none of the ${wanted} templates item 7 needs`);
      }
      if (missing.length > 0) {
        return partial(`${wanted - missing.length} of ${wanted} · missing: ${missing.join(", ")}`);
      }
      const count = value(reads.emailTemplates).filter((t) => t.is_current).length;
      return done(
        `all ${wanted} in place: the card scan and WhatsApp templates, and ` +
          `${count} Word email template${count === 1 ? "" : "s"}`,
      );
    }

    // ── 8 · Standard task waves (playbooks) ───────────────────────────────
    case 8: {
      const stop = blockedBy(reads.programs, reads.playbooks);
      if (stop) return stop;
      const current = value(reads.playbooks).filter((p) => p.is_current);
      return perProgram(reads, (id) => current.some((p) => p.program_id === id), {
        nothing: "no offering to write task waves for yet — item 4 comes first",
        some: "no playbook",
        all: "at least one current playbook",
      });
    }

    // ── 9 · Approval rules ────────────────────────────────────────────────
    case 9: {
      const stop = blockedBy(reads.approvalRules);
      if (stop) return stop;
      const rules = value(reads.approvalRules);
      if (rules.length === 0) {
        return none("no rules — everything falls to one default approver");
      }
      // An empty condition is the catch-all (`02` §9). An entity type with
      // rules but no catch-all has requests that match nothing.
      //
      // **What that costs is not the same for every entity type** — P15, found
      // while building the go-live check. `find_rule` returning None hands the
      // decision to the *caller's* `default_approver_role`, and the nine call
      // sites disagree: seven name `sales_lead`, but `proposals.py` and one
      // `planner_engine` path pass `None`, which applies the thing unreviewed.
      // This caption used to say "has no approver", which is wrong in both
      // directions at once. It now says the part that is true for every type,
      // and check 4 of the go-live sheet says the rest, per entity type, from
      // the generated `APPROVAL_NO_RULE` table.
      const inUse = [...new Set(rules.map((r) => r.entity_type))];
      const uncovered = inUse.filter(
        (t) =>
          !rules.some(
            (r) => r.entity_type === t && Object.keys(r.condition ?? {}).length === 0,
          ),
      );
      if (uncovered.length > 0) {
        return partial(
          `${plural(rules.length, "rule")} · no catch-all for ${uncovered.join(
            ", ",
          )}, so a request matching none of them never reaches these rules at all — the go-live check says what each type falls back to`,
        );
      }
      return done(
        `${plural(rules.length, "rule")} across ${plural(
          inUse.length,
          "entity type",
        )}, each with a catch-all`,
      );
    }

    // ── 10 · The behaviour dials ──────────────────────────────────────────
    case 10: {
      const stop = blockedBy(reads.settings);
      if (stop) return stop;
      const live = value(reads.settings) as unknown as Record<string, unknown>;
      const dials = Object.keys(SETTINGS_DEFAULTS) as Array<keyof typeof SETTINGS_DEFAULTS>;
      const changed = dials.filter((k) => !deepEqual(live[k], SETTINGS_DEFAULTS[k]));
      const chosen = changed.filter((k) => !ENV_SEEDED.has(k));
      if (changed.length === 0) {
        // §5.2: the API cannot tell "deliberately left at the default" from
        // "never opened". Neither can this console, so it does not pretend to.
        return partial("defaults apply — the API cannot tell whether you chose them");
      }
      if (chosen.length === 0) {
        // Found by looking at a freshly created organisation in a browser, not
        // by reading the spec: this row came up ● with nobody having opened it.
        return partial(
          `only ${plural(changed.length, "dial")} org creation seeds from the server's ` +
            `environment (${changed.join(", ")}) — the API cannot tell whether you chose them`,
        );
      }
      return done(
        `${chosen.length} of ${dials.length} dials differ from the model default`,
      );
    }

    // ── 11 · Email sending ────────────────────────────────────────────────
    case 11: {
      const stop = blockedBy(reads.settings);
      if (stop) return stop;
      const s = value(reads.settings);
      return compound({
        credentialsStored: s.email_credentials_stored,
        mode: s.email_mode,
        liveMode: "smtp",
        envVar: "EMAIL_MODE",
        noun: "approved messages",
        instead: "are written to a file",
      });
    }

    // ── 12 · Retention windows ────────────────────────────────────────────
    case 12: {
      const stop = blockedBy(reads.settings);
      if (stop) return stop;
      const s = value(reads.settings);
      // §5.2 says "always satisfied", and P12 says that cannot be shown as `●`.
      //
      // Both columns are seeded by `POST /orgs` from `DEFAULT_AUDIO_RETENTION_DAYS`
      // and `DEFAULT_TRANSCRIPT_RETENTION_DAYS`, and **no route returns those env
      // values** — grepped across `app/`: `config.py` declares them and
      // `organisations.py` reads them, and that is the whole of it. So there is
      // no response, and no combination of responses, that separates "the
      // operator chose 90 days" from "the server's environment said 90 days".
      // Unlike item 10 this cannot be rescued by carving out a few columns:
      // the item has only these two, and both are unknowable.
      //
      // `◐` is exactly what this console means by "true, but unverifiable"
      // (see the header). The windows are real and are shown; the claim that
      // somebody set them is the part being withheld.
      return partial(
        `recordings ${plural(s.audio_retention_days, "day")} · transcripts ${plural(
          s.transcript_retention_days,
          "day",
        )} · in force, but seeded from the server's environment — the API cannot tell whether you chose them`,
      );
    }

    // ── 13 · Demo teams ───────────────────────────────────────────────────
    case 13: {
      const stop = blockedBy(reads.demoTeams);
      if (stop) return stop;
      const teams = value(reads.demoTeams);
      if (teams.length === 0) return none("no teams — demos are still bookable");
      return done(plural(teams.length, "team"));
    }

    // ── 14 · Calendar ─────────────────────────────────────────────────────
    case 14: {
      const stop = blockedBy(reads.settings);
      if (stop) return stop;
      const s = value(reads.settings);
      return compound({
        credentialsStored: s.calendar_credentials_stored,
        mode: s.calendar_mode,
        liveMode: "google",
        envVar: "CALENDAR_MODE",
        noun: "confirmed demos",
        instead: "are not mirrored into your calendar",
      });
    }

    // ── 15 · Vendors ──────────────────────────────────────────────────────
    case 15: {
      const stop = blockedBy(reads.vendors);
      if (stop) return stop;
      const vendors = value(reads.vendors);
      if (vendors.length === 0) {
        return none("no vendors — promises can still be typed as free text");
      }
      return done(plural(vendors.length, "vendor"));
    }

    // ── 16 · Suppliers of inbound mail ────────────────────────────────────
    case 16:
      // Takes no read, on purpose. "Permanently unavailable" is a fact about
      // the API, not about this organisation's data, so no response can move
      // it and the argument is deliberately unused.
      return blocked(
        "no column, no endpoint and no per-org storage — INBOUND_EMAIL_MODE is a " +
          "process-wide environment variable, and open finding F35 says keep it off",
      );

    default:
      throw new Error(`no derivation for checklist item ${item.n}`);
  }
}
