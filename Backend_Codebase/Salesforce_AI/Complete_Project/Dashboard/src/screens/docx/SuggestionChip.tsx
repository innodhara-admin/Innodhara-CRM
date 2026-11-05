/**
 * One placeholder, set into the document flow — Task 20 Step 3.
 *
 * An accepted placeholder **stays where it is** and changes from "suggested" to
 * "placed" rather than moving to a list of decisions. The administrator is
 * judging the finished shape of a document, and a list of things they have
 * already agreed to tells them nothing about that.
 *
 * The green is a token (`--suggest`), never a hex here — the design spec asks
 * for green chips by name (§11) and `tokens.test.ts` enforces where the value
 * may live.
 */
import { useState } from "react";

import { Button, TextArea, styles as s } from "../../ui/primitives";
import c from "./docx.module.css";
import { anchorOf, type PlanEntry, type Suggestion } from "./plan";

export type ChipState = "suggested" | "placed";

/** What each kind is, in the words an administrator would use. */
const KIND_NOUN: Record<PlanEntry["kind"], string> = {
  token: "a phrase replaced everywhere it appears",
  insert: "a new paragraph the AI writes",
  replace: "a paragraph the AI rewrites",
  table: "the price list, filled from the rate card",
};

function meta(entry: PlanEntry, occurrences?: number): string {
  const parts = [KIND_NOUN[entry.kind]];
  if (entry.kind === "token" && entry.literal) {
    parts.push(
      occurrences === undefined
        ? `“${entry.literal}”`
        : `“${entry.literal}” · ${occurrences} in this document`,
    );
  }
  const anchor = anchorOf(entry);
  if (anchor) parts.push(entry.before ? `before ${anchor}` : `at ${anchor}`);
  if (entry.kind === "insert" || entry.kind === "replace") {
    parts.push(`up to ${entry.max_words ?? 90} words`);
    parts.push(entry.required ? "required" : "optional");
  }
  if (entry.kind === "table" && entry.columns) {
    parts.push(`${entry.columns.length} columns mapped`);
  }
  return parts.join(" · ");
}

export function SuggestionChip({
  entry,
  state,
  confidence,
  why,
  occurrences,
  canMoveUp,
  canMoveDown,
  onAccept,
  onReject,
  onBrief,
  onMove,
}: {
  entry: PlanEntry;
  state: ChipState;
  /** The model's own confidence, shown only while the chip is a suggestion. */
  confidence?: number;
  why?: string;
  /** How many times a token's literal really occurs (`docx_text.count_token`). */
  occurrences?: number;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onAccept: (next: Suggestion) => void;
  onReject: (key: string) => void;
  onBrief: (key: string, brief: string) => void;
  onMove: (key: string, direction: "up" | "down") => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.brief ?? "");
  const placed = state === "placed";
  const briefable = entry.kind === "insert" || entry.kind === "replace";

  function saveBrief() {
    if (placed) onBrief(entry.key, draft);
    else onAccept({ ...entry, brief: draft });
    setEditing(false);
  }

  return (
    <div className={`${c.chip} ${placed ? c.chipPlaced : c.chipSuggested}`}>
      <div className={c.chipHead}>
        <span className={c.chipState}>{placed ? "Placed" : "Suggested"}</span>
        <span className={c.chipKey}>{entry.key}</span>
        <span className={c.chipMeta}>{meta(entry, occurrences)}</span>
      </div>

      {briefable &&
        (editing ? (
          <TextArea
            rows={3}
            aria-label={`What the AI should write for ${entry.key}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        ) : (
          <p className={c.chipWhy}>
            {entry.brief || "No brief yet — say what belongs here before saving."}
          </p>
        ))}

      {!placed && why && (
        <p className={c.chipWhy}>
          {confidence === undefined
            ? why
            : `${why} · the model's confidence: ${Math.round(confidence * 100)}%`}
        </p>
      )}

      <div className={c.chipActions}>
        {editing ? (
          <>
            <Button variant="primary" onClick={saveBrief}>
              Save brief
            </Button>
            <Button
              variant="quiet"
              onClick={() => {
                setDraft(entry.brief ?? "");
                setEditing(false);
              }}
            >
              Cancel
            </Button>
          </>
        ) : (
          <>
            {!placed && (
              <Button variant="primary" onClick={() => onAccept(entry)}>
                Accept
              </Button>
            )}
            {briefable && (
              <Button variant="quiet" onClick={() => setEditing(true)}>
                Edit brief
              </Button>
            )}
            <Button variant="quiet" disabled={!canMoveUp} onClick={() => onMove(entry.key, "up")}>
              Move up
            </Button>
            <Button
              variant="quiet"
              disabled={!canMoveDown}
              onClick={() => onMove(entry.key, "down")}
            >
              Move down
            </Button>
            <Button variant="danger" onClick={() => onReject(entry.key)}>
              {placed ? "Remove" : "Reject"}
            </Button>
          </>
        )}
      </div>

      {placed && entry.kind === "table" && (
        <p className={`${s.muted} ${c.chipWhy}`}>
          The column mapping is edited from the table itself.
        </p>
      )}
    </div>
  );
}
