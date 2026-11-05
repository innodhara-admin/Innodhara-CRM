/**
 * The sixteen checklist rows — 06_DESIGN.md §5.1.
 *
 * The rail **is** the product: permanently visible, tiered as the manual tiers
 * it, with each row carrying the manual's own words for what breaks if it is
 * skipped. There is no widget-grid home screen.
 *
 * ## Where the words come from
 *
 * Eleven of the sixteen items are edited through an entity descriptor, and the
 * descriptor already carries the manual's quote, its "if you skip it" line and
 * its page reference. Those eleven rows **name the descriptor rather than
 * repeating its text** — a second copy is a second thing to keep true, and the
 * conformance test in Task 15 already pins the descriptor's version.
 *
 * The other five (1, 11, 12, 14, 16) have no entity to write: item 1 is
 * `POST /orgs`, items 11 and 14 are integration `PUT`s plus a process-wide env
 * var, item 12 is two columns of the settings row, and item 16 has no storage
 * of any kind. Their words are quoted here, from
 * `02_SEEDING_PREREQUISITES.md` §§1, 11, 12, 14, 16, which extracted them
 * verbatim from the product manual pp. 6–7. **Quote, never paraphrase** (§9).
 *
 * ## The tiers, and a document that disagrees with itself
 *
 * The manual groups the list as **Essential (7) · Strongly recommended (4) ·
 * Optional (4)** — fifteen tiered items — with item 1 sitting outside them at
 * platform level ("done once by the platform operator"). Fifteen items over
 * 2–16 with those three counts admits exactly one split: **2–8, 9–12, 13–16**,
 * which is what `06` §5.1 and `07` Task 16 both state.
 *
 * `02` contradicts this in two places and agrees with it in a third: its §8
 * sits under a `TIER 3 — Governance & behaviour ("strongly recommended")`
 * heading and its summary table marks item 8 "Recommended", but its own §0
 * dependency diagram puts item 8 in `TIER 2 — the catalogue`, hanging off
 * item 4's `program_id`. The §0 diagram is the one that matches the arithmetic,
 * so playbooks are Essential here. `02`'s tier *headings* are dependency tiers
 * wearing the manual's tier names, which is where the collision came from.
 */
import { DESCRIPTORS, type EntityKey } from "../descriptors";

export type Tier = "platform" | "essential" | "recommended" | "optional";

export const TIER_LABEL: Record<Tier, string> = {
  platform: "Platform",
  essential: "Essential",
  recommended: "Strongly recommended",
  optional: "Optional",
};

/** Rail order. Also the order the tiers are declared in the manual. */
export const TIER_ORDER: readonly Tier[] = [
  "platform",
  "essential",
  "recommended",
  "optional",
];

export type ChecklistItem = {
  /** 1–16, the manual's own numbering. */
  n: number;
  tier: Tier;
  title: string;
  /** The manual, verbatim. */
  quote: string;
  /** What the manual says happens if it is skipped. Also verbatim. */
  ifSkipped: string;
  manualRef: string;
  /**
   * Hard predecessors as item numbers, from `02` §0 — the arrows that document
   * names, not "everything needs an organisation". Each one is a foreign key, a
   * unique constraint or a handler check, never an editorial preference.
   */
  dependsOn: number[];
  /** The entity this item is edited through, where one exists. */
  entity: EntityKey | null;
};

type Row =
  | { n: number; tier: Tier; dependsOn: number[]; entity: EntityKey }
  | {
      n: number;
      tier: Tier;
      dependsOn: number[];
      entity: null;
      title: string;
      quote: string;
      ifSkipped: string;
      manualRef: string;
    };

const ROWS: Row[] = [
  {
    n: 1,
    tier: "platform",
    dependsOn: [],
    entity: null,
    title: "Organisation and its first administrator",
    quote:
      "Creates the tenant every other record belongs to, and the one account " +
      "that can configure it. Done once by the platform operator.",
    ifSkipped: "There is nothing to sign in to.",
    manualRef: "Product manual, p. 6 · item 1",
  },

  // Essential — the manual's first tier. Item 2 depends on item 1 for a reason
  // the manual does not state and `admin.py · register_staff` does: a staff
  // address must end with the organisation's own domain, so the organisation
  // has to exist before anybody can be added to it.
  { n: 2, tier: "essential", dependsOn: [1], entity: "staff" },
  { n: 3, tier: "essential", dependsOn: [2], entity: "skills" },
  { n: 4, tier: "essential", dependsOn: [], entity: "programs" },
  { n: 5, tier: "essential", dependsOn: [4], entity: "pricing" },
  { n: 6, tier: "essential", dependsOn: [4], entity: "proposalTemplates" },
  { n: 7, tier: "essential", dependsOn: [], entity: "messageTemplates" },
  { n: 8, tier: "essential", dependsOn: [4], entity: "playbooks" },

  // Strongly recommended.
  { n: 9, tier: "recommended", dependsOn: [], entity: "approvalRules" },
  { n: 10, tier: "recommended", dependsOn: [], entity: "settings" },
  {
    n: 11,
    tier: "recommended",
    dependsOn: [],
    entity: null,
    title: "Email sending",
    quote:
      "Either an organisation-wide sending account, or — better — each " +
      "salesperson's own, so the client always sees a real person's address.",
    ifSkipped:
      "Messages are drafted, approved and written to an outbox file instead " +
      "of being delivered.",
    manualRef: "Product manual, p. 7 · item 11",
  },
  {
    n: 12,
    tier: "recommended",
    dependsOn: [],
    entity: null,
    title: "Retention windows",
    quote:
      "How long recordings and transcripts are kept before they are " +
      "automatically deleted and scrubbed.",
    ifSkipped: "Defaults apply: recordings 90 days, transcripts one year.",
    manualRef: "Product manual, p. 7 · item 12",
  },

  // Optional.
  { n: 13, tier: "optional", dependsOn: [2], entity: "demoTeams" },
  {
    n: 14,
    tier: "optional",
    dependsOn: [],
    entity: null,
    title: "Calendar",
    quote:
      "Connect a calendar and confirmed demos are mirrored into it. The " +
      "system's own calendar remains the source of truth either way.",
    ifSkipped:
      "Invitations still reach clients by email; nothing appears in your own " +
      "calendar.",
    manualRef: "Product manual, p. 7 · item 14",
  },
  { n: 15, tier: "optional", dependsOn: [], entity: "vendors" },
  {
    n: 16,
    tier: "optional",
    dependsOn: [],
    entity: null,
    title: "Suppliers of inbound mail",
    quote:
      "Connect a mailbox and client replies are read and classified " +
      "automatically.",
    ifSkipped:
      "Replies are captured by hand with Log a reply, which works fully and " +
      "takes seconds.",
    manualRef: "Product manual, p. 7 · item 16",
  },
];

function expand(row: Row): ChecklistItem {
  if (row.entity === null) {
    const { title, quote, ifSkipped, manualRef, ...rest } = row;
    return { ...rest, title, quote, ifSkipped, manualRef };
  }
  const d = DESCRIPTORS[row.entity];
  return {
    n: row.n,
    tier: row.tier,
    dependsOn: row.dependsOn,
    entity: row.entity,
    title: d.title,
    quote: d.quote,
    ifSkipped: d.ifSkipped,
    manualRef: d.manualRef,
  };
}

export const ITEMS: readonly ChecklistItem[] = ROWS.map(expand);

export const ITEM_BY_NUMBER: ReadonlyMap<number, ChecklistItem> = new Map(
  ITEMS.map((i) => [i.n, i]),
);

/** The rail's grouping: tiers in order, each with its rows in order. */
export function itemsByTier(): Array<{ tier: Tier; items: ChecklistItem[] }> {
  return TIER_ORDER.map((tier) => ({
    tier,
    items: ITEMS.filter((i) => i.tier === tier),
  }));
}
