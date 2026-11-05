/**
 * The checklist rail — 06_DESIGN.md §5.1. **This is the product.**
 *
 * Permanently visible, never collapsed, and not a navigation sidebar that
 * happens to list screens: it is the go-live checklist itself, with a live
 * status against every row and the manual's own words for what breaks where a
 * row is not satisfied.
 *
 * Three things it deliberately is not (§9):
 *
 *  - **Not cards.** The tiers are labelled groups separated by a hairline rule.
 *    A card per item would turn a sign-off sheet into a dashboard.
 *  - **Not a progress bar.** "11 of 16" averages an Essential item together
 *    with an Optional one and a row this console cannot answer for at all.
 *    The counts below are stated per tier and per marker instead.
 *  - **Not optimistic.** A row whose read has not arrived is muted and says
 *    "reading"; a row whose read failed is `—` with the reason. Neither is `○`.
 */
import { ITEMS, TIER_LABEL, itemsByTier, type ChecklistItem } from "../checklist/items";
import { deriveStatus, type ChecklistReads, type ItemStatus } from "../checklist/status";
import { StatusMarker, styles as s, type Status } from "./primitives";
import r from "./Rail.module.css";

/** §6's four markers, plus the rendering state that is not one of them. */
const SPOKEN: Record<Status, string> = {
  done: "satisfied",
  partial: "partial",
  none: "not started",
  blocked: "cannot be satisfied here",
};

function Row({
  item,
  status,
  selected,
  onSelect,
}: {
  item: ChecklistItem;
  status: ItemStatus;
  selected: boolean;
  onSelect: (n: number) => void;
}) {
  const marker = status.marker;
  // §5.1: the manual's words for what breaks appear only where the row is not
  // satisfied. On a satisfied row they would be a warning about nothing.
  const showConsequence = marker === "none" || marker === "blocked";
  const pending = marker === "pending";

  return (
    <li>
      <button
        type="button"
        aria-current={selected ? "true" : undefined}
        className={`${r.row} ${selected ? r.rowSelected : ""} ${pending ? r.rowPending : ""}`.trim()}
        onClick={() => onSelect(item.n)}
      >
        <span className={r.gutter}>
          {marker === "pending" ? (
            // Not a spinner: nothing else in this interface moves (§9), and a
            // spinner in the status gutter would read as a fifth marker.
            <span className={r.pendingMark} role="img" aria-label="reading">
              <span aria-hidden="true">·</span>
            </span>
          ) : (
            <StatusMarker status={marker} label={SPOKEN[marker]} />
          )}
        </span>
        <span className={r.body}>
          <span className={r.title}>
            <span className={r.number}>{item.n}</span>
            {item.title}
          </span>
          <span className={r.caption}>{status.caption}</span>
          {showConsequence && <span className={r.consequence}>{item.ifSkipped}</span>}
        </span>
      </button>
    </li>
  );
}

/**
 * A per-marker tally rather than a percentage. The four numbers are four
 * different facts and averaging them would hide the two that matter.
 */
function Tally({ statuses }: { statuses: ItemStatus[] }) {
  const count = (m: ItemStatus["marker"]) => statuses.filter((x) => x.marker === m).length;
  const parts: Array<[Status, number]> = [
    ["done", count("done")],
    ["partial", count("partial")],
    ["none", count("none")],
    ["blocked", count("blocked")],
  ];
  const reading = count("pending");

  return (
    <p className={r.tally}>
      {parts.map(([marker, n]) => (
        <span key={marker} className={r.tallyPart}>
          <StatusMarker status={marker} label={SPOKEN[marker]} />
          <span className={r.tallyCount}>{n}</span>
        </span>
      ))}
      {reading > 0 && <span className={s.muted}>{`${reading} reading`}</span>}
    </p>
  );
}

export function Rail({
  reads,
  selected,
  onSelect,
}: {
  reads: ChecklistReads;
  selected: number | null;
  onSelect: (n: number) => void;
}) {
  const status = new Map(ITEMS.map((i) => [i.n, deriveStatus(i, reads)]));

  return (
    <nav className={r.rail} aria-label="Go-live checklist">
      <Tally statuses={[...status.values()]} />
      {itemsByTier().map(({ tier, items }, index) => (
        <section key={tier} className={r.tier}>
          {index > 0 && <hr className={s.ruleBreak} />}
          <h2 className={r.tierLabel}>{TIER_LABEL[tier]}</h2>
          <ul className={r.rows}>
            {items.map((item) => (
              <Row
                key={item.n}
                item={item}
                status={status.get(item.n)!}
                selected={selected === item.n}
                onSelect={onSelect}
              />
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}
