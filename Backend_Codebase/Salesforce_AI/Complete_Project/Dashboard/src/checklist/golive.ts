/**
 * The go-live check — 06_DESIGN.md §5.6, 07_BUILD_PLAN.md Task 23.
 *
 * **The single screen that justifies this console existing rather than a pile
 * of forms.** Sixteen forms let an operator enter a catalogue; this file is the
 * only thing in the product that reads what they entered and says whether it
 * will work — the manual's own p.7 acceptance test, made computable.
 *
 * Pure, like `status.ts`, and for the same reason: it takes the reads the rail
 * has already fetched as an argument, so its tests run against payloads a real
 * backend produced rather than against payloads written to agree with it.
 *
 * ## The vocabulary is `status.ts`'s, deliberately
 *
 * Four markers, not a score: `●` satisfied · `◐` partial · `○` not started ·
 * `—` this console cannot answer, plus `pending` as a rendering state. A
 * go-live *percentage* would average "no rate card" against "one playbook phase
 * missing" and hide both. Every check rolls up to the worst marker among its
 * rows, and every row says which subject it is about.
 *
 * ## Where each check's authority comes from
 *
 * Not one of the six is a judgement this console invented. Each names the
 * backend behaviour it is asserting, and three of them are derived rather than
 * transcribed:
 *
 * | Check | Authority |
 * |---|---|
 * | 1 · skill coverage | `ops.py · delete_skill` — active holders only, stated in its own comment |
 * | 2 · programme completeness | `planner_engine · phase_shift` falls back to an LLM-derived wave; phases from `VOCAB.phase` |
 * | 3 · message templates | `status.ts · STILL_USED_OLD_TEMPLATES`, and at least one Word email template (28 Oct 2026) |
 * | 4 · approval ordering | `approval_engine · find_rule` (rank, then created_at; first match wins) and `APPROVAL_NO_RULE` |
 * | 5 · delivery honesty | `status.ts · compound`, the same function the rail uses |
 * | 6 · domain | `admin.py · register_staff`'s own `endswith` test, with A6's fallback chain |
 */
import { APPROVAL_NO_RULE, VOCAB } from "../api/vocabularies.generated";
import {
  compound,
  type ChecklistReads,
  type Marker,
  type Read,
  type StaffRow,
  STILL_USED_OLD_TEMPLATES,
} from "./status";

/** One judged fact inside a check. */
export type CheckRow = {
  marker: Marker;
  /** The subject: a skill, a programme code, a `kind/channel`, an entity type. */
  subject: string;
  /** What is true about it. Names values, never adjectives (§9). */
  detail: string;
};

export type Check = {
  /** §5.6's own numbering, 1–6. */
  n: number;
  id: string;
  title: string;
  /** The worst marker among `rows`; `pending`/`blocked` when a read is missing. */
  marker: Marker;
  /** One line, above the rows. */
  summary: string;
  rows: CheckRow[];
  /**
   * Where the answer came from, when that is not obvious from the rows. Only
   * check 6 has one, and A6 requires it to be stated rather than implied.
   */
  source?: string;
};

/**
 * What the console knows about the organisation that no read returns.
 *
 * `runGoLive(reads)` in the plan's interface line takes one argument; it needs
 * two, because check 6 cannot be answered from the reads at all (P7 — no
 * `org_admin`-readable route returns `email_domain`) and A6's first fallback is
 * the value `POST /orgs` handed this tab. It stays pure: this is session data
 * passed in, not read here.
 */
export type GoLiveSession = {
  emailDomain?: string;
};

const ORDER: Record<Marker, number> = {
  blocked: 0,
  none: 1,
  partial: 2,
  pending: 3,
  done: 4,
};

/** The worst marker present. An empty row list is the caller's business. */
function worst(rows: CheckRow[]): Marker {
  return rows.reduce<Marker>(
    (acc, r) => (ORDER[r.marker] < ORDER[acc] ? r.marker : acc),
    "done",
  );
}

/**
 * Returns the check a missing read forces, or null when every read is present.
 * `unreadable` outranks `pending`, exactly as `status.ts · blockedBy` does:
 * once a read has failed, "cannot be read" is the honest answer, not "still
 * trying".
 */
function unavailable(
  base: Omit<Check, "marker" | "summary" | "rows">,
  ...reads: Array<Read<unknown>>
): Check | null {
  for (const r of reads) {
    if (r.state === "unreadable") {
      return { ...base, marker: "blocked", summary: r.why, rows: [] };
    }
  }
  for (const r of reads) {
    if (r.state === "pending") {
      return { ...base, marker: "pending", summary: "reading…", rows: [] };
    }
  }
  return null;
}

/** Only ever called after `unavailable` has cleared the same read. */
function value<T>(read: Read<T>): T {
  if (read.state !== "ok") throw new Error("read is not resolved");
  return read.value;
}

const plural = (n: number, one: string, many = `${one}s`) =>
  `${n} ${n === 1 ? one : many}`;

const listNames = (rows: Array<{ name: string }>) => rows.map((u) => u.name).join(", ");

// ─────────────────────────────────────────────────────────────────────────────
// 1 · Skill coverage — the check that justifies the console
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Every `required_skill` across current playbooks, diffed against every skill
 * held by an **active** user.
 *
 * **Active-only, and that is not a detail.** `ops.py · delete_skill` counts
 * holders with `User.is_active.is_(True)` and says in its own comment that the
 * go-live check has to agree, "because two definitions of 'covered' is how the
 * next divergence starts". So this is a join, not a set difference on
 * `GET /skills` alone: that response carries `user_id`, `skill` and `level` and
 * **no activity flag**, so the staff read is what makes the answer true.
 * Diffing the two lists directly would report a skill as covered when its only
 * holder has left, which is the exact false green F25 exists to prevent.
 *
 * The runtime agrees, by a different route:
 * `assignment_engine · build_candidates` drops `not u.is_active` from every
 * tier, so a deactivated holder can never be assigned the task either.
 *
 * An entry with **no** `required_skill` is counted too. It is a different
 * defect with the same outcome — `_skill_map` returns `{}` for a null skill and
 * the task lands on the phase lead exactly as an uncovered one does — so
 * leaving it out would let a playbook of skill-less entries report full
 * coverage of nothing.
 */
function skillCoverage(reads: ChecklistReads): Check {
  const base = {
    n: 1,
    id: "skill-coverage",
    title: "Every skill your playbooks ask for is held by somebody who is here",
  };
  const stop = unavailable(base, reads.playbooks, reads.skills, reads.staff);
  if (stop) return stop;

  const current = value(reads.playbooks).filter((p) => p.is_current);
  const staff = value(reads.staff);
  const activeIds = new Set(staff.filter((u) => u.is_active).map((u) => u.id));
  const byId = new Map(staff.map((u) => [u.id, u]));

  /** skill → the people holding it, split the way `delete_skill` splits them. */
  const holders = new Map<string, { active: StaffRow[]; inactive: StaffRow[] }>();
  for (const s of value(reads.skills)) {
    const person = byId.get(s.user_id);
    if (!person) continue; // a skill row for somebody `GET /admin/users` omits
    const slot = holders.get(s.skill) ?? { active: [], inactive: [] };
    (activeIds.has(person.id) ? slot.active : slot.inactive).push(person);
    holders.set(s.skill, slot);
  }

  // Which playbooks ask for each skill, so an uncovered row can say where the
  // demand comes from rather than only that it exists.
  const required = new Map<string, Set<string>>();
  let entries = 0;
  let unskilled = 0;
  for (const p of current) {
    for (const e of p.entries) {
      entries += 1;
      const raw = (e as { required_skill?: unknown }).required_skill;
      const skill = typeof raw === "string" ? raw.trim() : "";
      if (!skill) {
        unskilled += 1;
        continue;
      }
      const where = required.get(skill) ?? new Set<string>();
      where.add(`${p.phase}`);
      required.set(skill, where);
    }
  }

  if (current.length === 0) {
    return {
      ...base,
      marker: "none",
      summary: "no current playbook to check — item 8 comes first",
      rows: [],
    };
  }
  if (required.size === 0 && unskilled === 0) {
    return {
      ...base,
      marker: "none",
      summary: `${plural(current.length, "current playbook")} · not one entry names a skill`,
      rows: [],
    };
  }

  const rows: CheckRow[] = [...required.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([skill, phases]) => {
      const held = holders.get(skill) ?? { active: [], inactive: [] };
      const asked = `asked for in ${[...phases].sort().join(", ")}`;
      if (held.active.length > 0) {
        return {
          marker: "done" as Marker,
          subject: skill,
          detail: `${asked} · held by ${listNames(held.active)}`,
        };
      }
      if (held.inactive.length > 0) {
        // The worst of the three, and the one a plain set difference misses:
        // the row exists, so the skill *looks* held.
        return {
          marker: "none" as Marker,
          subject: skill,
          detail:
            `${asked} · the only ${held.inactive.length === 1 ? "holder is" : "holders are"} ` +
            `deactivated (${listNames(held.inactive)}) — a deactivated holder is not ` +
            `coverage, which is how ops.py · delete_skill counts it too`,
        };
      }
      return {
        marker: "none" as Marker,
        subject: skill,
        detail: `${asked} · nobody holds it`,
      };
    });

  if (unskilled > 0) {
    rows.push({
      marker: "none",
      subject: "(no skill named)",
      detail:
        `${plural(unskilled, "playbook entry", "playbook entries")} of ${entries} name no ` +
        `required_skill · those tasks route to the phase lead just as an uncovered one does`,
    });
  }

  const covered = rows.filter((r) => r.marker === "done").length;
  const named = required.size;
  return {
    ...base,
    marker: worst(rows),
    summary:
      covered === named && unskilled === 0
        ? `all ${plural(named, "skill")} your playbooks ask for ${
            named === 1 ? "is" : "are"
          } held by an active person`
        : `${covered} of ${plural(named, "skill")} covered · an uncovered task routes to the ` +
          `phase lead flagged "no skill match"`,
    rows,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 2 · Programme completeness
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Each active programme × {current rate card, current proposal template, a
 * current playbook per phase}.
 *
 * **The six phases come from `VOCAB.phase`, not from a literal list.**
 * `projects.py · trigger_phase_shift` validates its argument against the whole
 * `Phase` enum, so a playbook is loadable for any of the six and a missing one
 * is a real gap. The manual's own words for item 8 name four of them
 * ("preparation … delivery … payment … closure"), which is why a missing phase
 * is `◐` rather than `○`: `planner_engine · phase_shift` falls back to an
 * LLM-derived wave, so the phase still runs — it just stops following the
 * routine the operator wrote down.
 *
 * A missing rate card or proposal template is `○` for that programme:
 * `_estimate_value` returns None with no current `PricingTable`, so the
 * offering is sellable but unpriceable.
 */
function programCompleteness(reads: ChecklistReads): Check {
  const base = {
    n: 2,
    id: "program-completeness",
    title: "Every offering can be priced, proposed and planned",
  };
  const stop = unavailable(
    base,
    reads.programs,
    reads.pricing,
    reads.proposalTemplates,
    reads.playbooks,
  );
  if (stop) return stop;

  const active = value(reads.programs).filter((p) => p.is_active);
  if (active.length === 0) {
    return {
      ...base,
      marker: "none",
      summary: "nothing to sell yet — item 4 comes first",
      rows: [],
    };
  }

  const pricing = value(reads.pricing);
  const templates = value(reads.proposalTemplates);
  const playbooks = value(reads.playbooks).filter((p) => p.is_current);

  const rows: CheckRow[] = active.map((program) => {
    const missing: string[] = [];
    if (!(pricing[program.id] ?? []).some((v) => v.is_current)) missing.push("rate card");
    if (!(templates[program.id] ?? []).some((v) => v.is_current)) {
      missing.push("proposal template");
    }
    const phases = VOCAB.phase.filter(
      (phase) => !playbooks.some((p) => p.program_id === program.id && p.phase === phase),
    );

    if (missing.length > 0) {
      return {
        marker: "none" as Marker,
        subject: program.code,
        detail:
          `no current ${missing.join(", no current ")}` +
          (phases.length > 0
            ? ` · and no playbook for ${phases.join(", ")}`
            : ` · playbooks complete`),
      };
    }
    if (phases.length === VOCAB.phase.length) {
      return {
        marker: "none" as Marker,
        subject: program.code,
        detail:
          "priced and templated · no playbook for any phase, so every wave is derived " +
          "from scratch by the AI",
      };
    }
    if (phases.length > 0) {
      return {
        marker: "partial" as Marker,
        subject: program.code,
        detail:
          `priced and templated · no playbook for ${phases.join(", ")} — those waves are ` +
          `derived from scratch by the AI instead of following your routine`,
      };
    }
    return {
      marker: "done" as Marker,
      subject: program.code,
      detail: `priced, templated, and a playbook for all ${VOCAB.phase.length} phases`,
    };
  });

  const ready = rows.filter((r) => r.marker === "done").length;
  return {
    ...base,
    marker: worst(rows),
    summary:
      ready === rows.length
        ? `all ${plural(rows.length, "active offering")} complete`
        : `${ready} of ${plural(rows.length, "active offering")} complete`,
    rows,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 3 · Message template completeness
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The three old templates still in use, then the Word email templates
 * (28 Oct 2026). See `STILL_USED_OLD_TEMPLATES` for why it is these three.
 */
function messageTemplates(reads: ChecklistReads): Check {
  const base = {
    n: 3,
    id: "message-templates",
    title: "Card scan and WhatsApp templates, and the Word email templates",
  };
  const stop = unavailable(base, reads.messageTemplates, reads.emailTemplates);
  if (stop) return stop;

  const current = value(reads.messageTemplates).filter((t) => t.is_current);
  const rows: CheckRow[] = STILL_USED_OLD_TEMPLATES.map(({ kind, channel }) => {
    const row = current.find((t) => t.kind === kind && t.channel === channel);
    return {
      marker: (row ? "done" : "none") as Marker,
      subject: `${kind}/${channel}`,
      detail: row ? `"${row.name}" v${row.version}` : "no current template",
    };
  });
  const emails = value(reads.emailTemplates).filter((t) => t.is_current);
  rows.push({
    marker: (emails.length ? "done" : "none") as Marker,
    subject: "Word email templates",
    detail: emails.length ? `${emails.length} published` : "none published",
  });

  const have = rows.filter((r) => r.marker === "done").length;
  return {
    ...base,
    marker: worst(rows),
    summary: `${have} of ${rows.length} needed templates are in place`,
    rows,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 4 · Approval rule ordering
// ─────────────────────────────────────────────────────────────────────────────

/**
 * `approval_engine · find_rule` orders by `rank`, then `created_at`, and the
 * **first** rule whose condition matches wins. An empty condition matches
 * everything (`_condition_matches` returns True on a falsy condition), so three
 * things are checkable and all three are silent failures in the running product:
 *
 *  1. **No catch-all**, whose cost is *not* the same for every entity type. It
 *     is `APPROVAL_NO_RULE`, generated from every `request_approval` call site:
 *     a role means somebody is still asked, `null` means the caller applies it
 *     unreviewed. `proposals.py` passes `None`, so a proposal matching no rule
 *     is set `APPROVED_INTERNALLY` with nobody looking at it.
 *  2. **Rules ranked after a catch-all**, which can never fire.
 *  3. **`auto_approve`**, which is a legitimate choice and is listed rather than
 *     assumed to be a mistake — but as `◐`, because "who signs off" having the
 *     answer "nobody" is a partial state of this check whether or not it was
 *     deliberate. The summary says so, so an operator who meant it can move on.
 *
 * A **rank tie** is reported and not resolved: the tie-break is `created_at`,
 * which `list_approval_rules` does not return, so which of two equally ranked
 * rules fires is genuinely not knowable from this session.
 */
function approvalOrdering(reads: ChecklistReads): Check {
  const base = {
    n: 4,
    id: "approval-ordering",
    title: "Every approval request reaches a person",
  };
  const stop = unavailable(base, reads.approvalRules);
  if (stop) return stop;

  const rules = value(reads.approvalRules);
  const withRules = [...new Set(rules.map((r) => r.entity_type))];
  const requested = Object.entries(APPROVAL_NO_RULE)
    .filter(([, v]) => v.callSites > 0)
    .map(([k]) => k);
  const subjects = [...new Set([...requested, ...withRules])].sort();

  const consequence = (entityType: string): string => {
    const known = APPROVAL_NO_RULE[entityType as keyof typeof APPROVAL_NO_RULE];
    if (!known || known.callSites === 0) {
      return "nothing in the backend requests an approval of this type, so these rules never fire";
    }
    const falls = known.fallsTo as readonly (string | null)[];
    const roles = falls.filter((r): r is string => r !== null);
    if (falls.includes(null)) {
      return roles.length > 0
        ? `a matching request is applied unreviewed on some paths, and falls to ${roles.join(
            " / ",
          )} on the rest`
        : "a matching request is applied unreviewed — nobody is asked at all";
    }
    return `a matching request falls to ${roles.join(" / ")}`;
  };

  const rows: CheckRow[] = [];
  for (const entityType of subjects) {
    const mine = rules
      .filter((r) => r.entity_type === entityType)
      .sort((a, b) => a.rank - b.rank);

    if (mine.length === 0) {
      const known = APPROVAL_NO_RULE[entityType as keyof typeof APPROVAL_NO_RULE];
      const unreviewed = (known.fallsTo as readonly (string | null)[]).includes(null);
      rows.push({
        marker: unreviewed ? "none" : "partial",
        subject: entityType,
        detail: `no rule at all · ${consequence(entityType)}`,
      });
      continue;
    }

    const requestedByBackend =
      (APPROVAL_NO_RULE[entityType as keyof typeof APPROVAL_NO_RULE]?.callSites ?? 0) > 0;
    if (!requestedByBackend) {
      // Dead configuration, and it looks like the healthiest row on the sheet:
      // well-ranked rules with a catch-all, for a type no code path ever asks
      // about. Reported before the ordering is examined, because the ordering
      // of rules that never run is not the fact worth reading.
      rows.push({
        marker: "partial",
        subject: entityType,
        detail: `${plural(mine.length, "rule")} · ${consequence(entityType)}`,
      });
      continue;
    }

    // "10 when discount_pct_gt → sales_lead" was two different tens on one line
    // — the rank and the threshold — with the threshold's value dropped. Found
    // by reading the rendered row, not by reading the code. Both are labelled
    // now and the condition carries its value, since a rule's rank and its
    // threshold are exactly the two numbers an operator is comparing.
    const order = mine
      .map((r) => {
        const keys = Object.keys(r.condition ?? {});
        const when =
          keys.length === 0
            ? "{} (matches everything)"
            : "when " +
              keys.map((k) => `${k}=${JSON.stringify(r.condition[k])}`).join(" and ");
        const to = r.fallback_role
          ? `${r.approver_role} (else ${r.fallback_role})`
          : r.approver_role;
        return `rank ${r.rank} · ${when} → ${to}`;
      })
      .join(" · ");

    const catchAllAt = mine.findIndex((r) => Object.keys(r.condition ?? {}).length === 0);
    if (catchAllAt === -1) {
      rows.push({
        marker: (APPROVAL_NO_RULE[entityType as keyof typeof APPROVAL_NO_RULE]?.fallsTo as
          | readonly (string | null)[]
          | undefined)?.includes(null)
          ? "none"
          : "partial",
        subject: entityType,
        detail: `${order} · no catch-all {} rule, so ${consequence(entityType)}`,
      });
    } else {
      const shadowed = mine.slice(catchAllAt + 1);
      rows.push({
        marker: shadowed.length > 0 ? "partial" : "done",
        subject: entityType,
        detail:
          shadowed.length > 0
            ? `${order} · the catch-all at rank ${mine[catchAllAt].rank} matches everything, so ` +
              `${plural(shadowed.length, "rule")} ranked after it can never fire`
            : order,
      });
    }

    const ties = mine.filter((r, i) => i > 0 && r.rank === mine[i - 1].rank);
    if (ties.length > 0) {
      rows.push({
        marker: "partial",
        subject: `${entityType} · rank tie`,
        detail:
          `${plural(ties.length + 1, "rule")} share a rank · find_rule breaks the tie on ` +
          `created_at, which list_approval_rules does not return — which one fires is not ` +
          `readable from here`,
      });
    }

    for (const r of mine.filter((x) => x.auto_approve)) {
      rows.push({
        marker: "partial",
        subject: `${entityType} · rank ${r.rank}`,
        detail: `auto_approve — a matching ${entityType} is approved with no human involved`,
      });
    }
  }

  if (rows.length === 0) {
    return { ...base, marker: "none", summary: "no approval rules", rows: [] };
  }
  const autoApproved = rules.filter((r) => r.auto_approve).length;
  return {
    ...base,
    marker: worst(rows),
    summary:
      // "N rules across M entity types" was wrong: `subjects` includes the
      // types the backend requests an approval for and has NO rule, which is
      // the point of listing them. Counted separately, so neither number
      // borrows the other's meaning.
      `${plural(subjects.length, "entity type")} checked · ${plural(rules.length, "rule")}` +
      (autoApproved > 0
        ? ` · ${plural(autoApproved, "rule")} approve${autoApproved === 1 ? "s" : ""} itself, ` +
          `listed here for sign-off rather than as a fault`
        : ""),
    rows,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 5 · Delivery honesty
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The compound email and calendar statuses, from `status.ts · compound` — the
 * same function items 11 and 14 use. Sharing it is the point: the rail and this
 * sheet cannot come to different conclusions about whether mail actually leaves.
 */
function deliveryHonesty(reads: ChecklistReads): Check {
  const base = {
    n: 5,
    id: "delivery-honesty",
    title: "What this server will and will not actually send",
  };
  const stop = unavailable(base, reads.settings);
  if (stop) return stop;

  const s = value(reads.settings);
  const email = compound({
    credentialsStored: s.email_credentials_stored,
    mode: s.email_mode,
    liveMode: "smtp",
    envVar: "EMAIL_MODE",
    noun: "approved messages",
    instead: "are written to a file",
  });
  const calendar = compound({
    credentialsStored: s.calendar_credentials_stored,
    mode: s.calendar_mode,
    liveMode: "google",
    envVar: "CALENDAR_MODE",
    noun: "confirmed demos",
    instead: "are not mirrored into your calendar",
  });

  const rows: CheckRow[] = [
    { marker: email.marker, subject: "email", detail: email.caption },
    { marker: calendar.marker, subject: "calendar", detail: calendar.caption },
  ];
  const live = rows.filter((r) => r.marker === "done").length;
  return {
    ...base,
    marker: worst(rows),
    summary:
      live === 2
        ? "email and calendar are both live on this server"
        : `${live} of 2 channels live · the modes are process-wide environment variables, ` +
          `so they are the server's setting and not this organisation's`,
    rows,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 6 · Domain check, with A6's fallback chain
// ─────────────────────────────────────────────────────────────────────────────

/** `admin.py · register_staff`: `body.email.lower().endswith("@" + org.email_domain)`. */
const domainOf = (email: string) => email.toLowerCase().split("@").pop() ?? "";

/**
 * Every staff email against the organisation's domain — run against the domain
 * this console can actually know (P7/A6), **naming which source it used**.
 *
 *  1. the value `POST /orgs` returned earlier in this same tab;
 *  2. otherwise the distinct domains across the staff emails themselves — the
 *     server enforces the rule on every staff create, so more than one distinct
 *     domain is itself the defect worth reporting;
 *  3. neither ⇒ `—` with the reason. Not a pass.
 *
 * Source 2 can never be `●`. It compares the addresses against each other, and
 * "they all agree" is not "they agree with the organisation's own domain" —
 * which no read from this session returns.
 *
 * One address is legitimately allowed to differ and the check says so:
 * `POST /orgs` writes the org admin's account **without** the `endswith` test
 * that `register_staff` applies — grepped, not assumed — so the administrator
 * is the one account that can sit outside the domain.
 */
function domainCheck(reads: ChecklistReads, session: GoLiveSession): Check {
  const base = {
    n: 6,
    id: "domain",
    title: "Every staff address is inside your organisation's domain",
  };
  const stop = unavailable(base, reads.staff, reads.me);
  if (stop) return stop;

  const staff = value(reads.staff);
  const me = value(reads.me);
  if (staff.length === 0) {
    return { ...base, marker: "none", summary: "no accounts to check", rows: [] };
  }

  // The stored column is `lstrip("@").lower()`, so match it rather than the
  // operator's typing (F34 — a stored "@domain" once built "@@domain").
  const stated = session.emailDomain?.replace(/^@+/, "").toLowerCase();

  if (stated) {
    const rows: CheckRow[] = staff
      .filter((u) => domainOf(u.email) !== stated)
      .map((u) => ({
        marker: "none" as Marker,
        subject: u.email,
        detail:
          u.id === me.user_id || u.role === "org_admin"
            ? `outside @${stated} · this is the administrator account, which POST /orgs ` +
              `creates without the domain test register_staff applies`
            : `outside @${stated}`,
      }));
    return {
      ...base,
      marker: rows.length === 0 ? "done" : worst(rows),
      summary:
        rows.length === 0
          ? `all ${plural(staff.length, "account")} are inside @${stated}`
          : `${rows.length} of ${plural(staff.length, "account")} outside @${stated}`,
      rows,
      source: "the domain POST /orgs returned when this tab created the organisation",
    };
  }

  const domains = [...new Set(staff.map((u) => domainOf(u.email)))].sort();
  if (domains.length === 1) {
    return {
      ...base,
      // Never `●`: this compares the addresses against each other.
      marker: "partial",
      summary:
        `all ${plural(staff.length, "account")} share @${domains[0]} · whether that is the ` +
        `organisation's own domain is not readable from this session`,
      rows: [{ marker: "partial", subject: `@${domains[0]}`, detail: plural(staff.length, "account") }],
      source:
        "the staff addresses themselves — no org_admin-readable route returns email_domain (P7), " +
        "and this tab did not create the organisation",
    };
  }
  return {
    ...base,
    marker: "none",
    summary:
      `${plural(domains.length, "distinct domain")} across ${plural(staff.length, "account")} · ` +
      `register_staff enforces one domain per organisation, so more than one means somebody ` +
      `was created another way`,
    rows: domains.map((d) => ({
      marker: "none" as Marker,
      subject: `@${d}`,
      detail: listNames(staff.filter((u) => domainOf(u.email) === d)),
    })),
    source: "the staff addresses themselves — this tab did not create the organisation",
  };
}

/**
 * The six checks, in §5.6's order. Pure: same reads and session in, same
 * `Check[]` out.
 */
export function runGoLive(reads: ChecklistReads, session: GoLiveSession = {}): Check[] {
  return [
    skillCoverage(reads),
    programCompleteness(reads),
    messageTemplates(reads),
    approvalOrdering(reads),
    deliveryHonesty(reads),
    domainCheck(reads, session),
  ];
}

/** Whether anything is still arriving — the screen says so rather than judging. */
export const isPending = (checks: Check[]) => checks.some((c) => c.marker === "pending");
