/**
 * A textarea for the fields the API stores as a raw blob — Task 19 Step 1.
 *
 * Five write fields have no sub-model at all: `PlaybookRequest.entries`,
 * `ApprovalRuleRequest.condition` and `.joint_condition`,
 * `SettingsRequest.nudge_gap_days`, `.reply_nudge_after_days` and
 * `.payment_reminder_schedule`. Pydantic types them `dict` / `list[dict]` and
 * the handler stores whatever arrives. **A typo in a key name is accepted,
 * written, and then never read** — the rule silently never matches, the nudge
 * ladder silently never fires.
 *
 * So this control does the only two things it honestly can:
 *
 *  1. **Refuse malformed JSON before it is sent.** That much is checkable.
 *  2. **Show the keys that are actually read**, from the one place they are
 *     known — model comments and the working seed data — and label them as
 *     suggestions, because they are not a schema and the server will take
 *     anything.
 *
 * It does **not** reject an unknown key. Doing so would be this console
 * inventing a schema the backend does not have, and the operator has no way to
 * tell whose rule they are fighting. `06_DESIGN.md` §6: say who enforces what,
 * and never imply a validation that does not exist.
 */
import { useState } from "react";

import { Button, TextArea, styles as s } from "./primitives";

export type JsonFieldProps = {
  id: string;
  value: unknown;
  onChange: (next: unknown) => void;
  invalid?: boolean;
  /** Pretty-printed and dropped in when the operator asks for it. */
  example: unknown;
  /** Keys the engines actually read. Suggestions, never a schema. */
  knownKeys?: readonly string[];
  /** What reading these keys does, so the list is not just nouns. */
  keysNote?: string;
};

/** JSON text ⇄ value, keeping the operator's own formatting while they type. */
export function JsonField({
  id,
  value,
  onChange,
  invalid,
  example,
  knownKeys,
  keysNote,
}: JsonFieldProps) {
  const [text, setText] = useState(() =>
    value === undefined || value === "" ? "" : JSON.stringify(value, null, 2),
  );
  const [parseError, setParseError] = useState<string | null>(null);

  function edit(next: string) {
    setText(next);
    if (next.trim() === "") {
      setParseError(null);
      onChange("");
      return;
    }
    try {
      onChange(JSON.parse(next));
      setParseError(null);
    } catch (cause) {
      // The value is deliberately NOT updated: half-typed JSON must not reach
      // the form state, or a submit mid-edit would send the last valid version
      // while the box shows something else.
      setParseError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--s2)" }}>
      <TextArea
        id={id}
        mono
        rows={8}
        invalid={invalid || Boolean(parseError)}
        value={text}
        spellCheck={false}
        onChange={(e) => edit(e.target.value)}
      />

      {parseError && (
        <p className={s.mono} style={{ fontSize: "var(--text-xs)", color: "var(--status-blocked)", margin: 0 }}>
          {`Not valid JSON — ${parseError}`}
        </p>
      )}

      <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>
        <Button
          onClick={() => {
            const pretty = JSON.stringify(example, null, 2);
            setText(pretty);
            setParseError(null);
            onChange(example);
          }}
        >
          Use the example
        </Button>
        {text.trim() !== "" && !parseError && (
          <Button
            variant="quiet"
            onClick={() => {
              const pretty = JSON.stringify(JSON.parse(text), null, 2);
              setText(pretty);
            }}
          >
            Tidy
          </Button>
        )}
      </div>

      {knownKeys && knownKeys.length > 0 && (
        <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: 0 }}>
          <strong>Keys the engines read: </strong>
          <span className={s.mono}>{knownKeys.join(", ")}</span>
          {". "}
          {keysNote}{" "}
          <strong>
            These are suggestions, not a schema — the server stores any key you
            send, and one it does not recognise is written and never read.
          </strong>
        </p>
      )}
    </div>
  );
}
