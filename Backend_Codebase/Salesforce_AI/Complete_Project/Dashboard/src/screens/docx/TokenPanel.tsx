/**
 * Which phrase in the document stands in for which field — Task 21 Step 1.
 *
 * The occurrence count is the point of this panel, not decoration. Binding
 * "School Name" in `Essential Lab.docx` rewrites **seven** places, in the body,
 * the tables, the headers and the footers, and the administrator is entitled to
 * know that before they save rather than after a client has the document.
 *
 * A field can be held by only one phrase. The entry's key *is* the field and
 * keys are unique per plan, so binding a field a second phrase already holds
 * moves it — see `plan.ts::bindToken`. Doing anything else would offer a state
 * `validate_plan` refuses.
 */
import { useState } from "react";

import type { Block } from "../../api/reads";
import { Banner, Button, DataTable, Field, Select, TextInput, styles as s } from "../../ui/primitives";
import c from "./docx.module.css";
import {
  BINDABLE_FIELDS,
  MIN_LITERAL_CHARS,
  bindToken,
  checkLiteral,
  fieldForLiteral,
  literalForField,
  type LiteralCheck,
  type Plan,
  type Suggestion,
} from "./plan";

type DetectedToken = {
  literal: string;
  occurrences: number;
  sample_block_ids: string[];
};

const FIELD_OPTIONS = BINDABLE_FIELDS.map((f) => ({ value: f, label: f }));

export function TokenPanel({
  tokens,
  blocks,
  plan,
  suggestions,
  onChange,
}: {
  tokens: readonly DetectedToken[];
  blocks: readonly Block[];
  plan: Plan;
  /** Token suggestions not yet in the plan, so the model's proposal appears
   *  on its own row rather than as a chip with nowhere to sit. */
  suggestions: readonly Suggestion[];
  onChange: (next: Plan) => void;
}) {
  const [draft, setDraft] = useState("");
  const [check, setCheck] = useState<LiteralCheck | null>(null);

  const suggested = new Map<string, string>();
  for (const sg of suggestions) {
    if (sg.kind === "token" && sg.literal) suggested.set(sg.literal, sg.key);
  }

  // The detector is narrow by design (two to five Title-Case words), so a
  // literal bound by hand or proposed by the model may not be in `tokens` at
  // all. It still belongs on this list, or it would be invisible once bound.
  const extra = new Set<string>();
  for (const e of plan.entries) {
    if (e.kind === "token" && e.literal && !tokens.some((t) => t.literal === e.literal)) {
      extra.add(e.literal);
    }
  }
  for (const literal of suggested.keys()) {
    if (!tokens.some((t) => t.literal === literal)) extra.add(literal);
  }

  const rows: DetectedToken[] = [
    ...tokens,
    ...[...extra].map((literal) => ({
      literal,
      occurrences: checkLiteral(literal, blocks).occurrences,
      sample_block_ids: [],
    })),
  ];

  function bind(literal: string, field: string) {
    onChange(bindToken(plan, literal, field));
  }

  function addDraft(field: string) {
    bind(draft.trim(), field);
    setDraft("");
    setCheck(null);
  }

  return (
    <>
      <p className={c.caption}>
        A phrase is replaced everywhere it appears — the body, the tables, the
        headers and the footers. The count beside each one is what will change.
      </p>

      <DataTable
        columns={["Phrase in the document", "Times it appears", "Filled with"]}
        empty="No stand-in phrases were detected. Add one below if the document uses something the detector does not recognise."
        rows={rows.map((t) => {
          const bound = fieldForLiteral(plan, t.literal);
          const proposal = suggested.get(t.literal);
          const heldBy = proposal ? literalForField(plan, proposal) : null;
          return [
            <span className={c.literalCell}>{t.literal}</span>,
            <span className={c.count}>{t.occurrences || "—"}</span>,
            <div className={c.actions}>
              <Select
                aria-label={`Field for ${t.literal}`}
                placeholder="Not a placeholder"
                options={FIELD_OPTIONS}
                value={bound ?? ""}
                onChange={(e) => bind(t.literal, e.target.value)}
              />
              {proposal && bound !== proposal && (
                <Button variant="quiet" onClick={() => bind(t.literal, proposal)}>
                  {heldBy
                    ? `Use ${proposal} (moves it off “${heldBy}”)`
                    : `Use ${proposal}, suggested`}
                </Button>
              )}
            </div>,
          ];
        })}
      />

      <div className={c.stack}>
        <Field
          label="A phrase the detector missed"
          htmlFor="docx-literal"
          caption="the detector only looks for two to five Title-Case words, so it does not see things like <Client> or XXX"
        >
          <TextInput
            id="docx-literal"
            value={draft}
            placeholder="<Client>"
            onChange={(e) => {
              setDraft(e.target.value);
              setCheck(null);
            }}
          />
        </Field>
        <div className={c.actions}>
          <Button
            disabled={draft.trim().length === 0}
            onClick={() => setCheck(checkLiteral(draft, blocks))}
          >
            Check this phrase
          </Button>
        </div>
      </div>

      {check?.verdict === "too-slight" && (
        <div className={c.stack}>
          <Banner tone="blocked" title="That is too short to stand in for anything">
            <p style={{ margin: 0 }}>
              {`A phrase needs at least ${MIN_LITERAL_CHARS} characters and at ` +
                "least one letter. Replacement is a plain text substitution over " +
                "the whole file, so a shorter one is matched inside other words " +
                "too — a single space would put the client's name between every " +
                "word in the document."}
            </p>
          </Banner>
        </div>
      )}

      {(check?.verdict === "found" || check?.verdict === "not-found") && (
        <div className={c.stack}>
          <Banner
            tone={check.verdict === "found" ? "note" : "warn"}
            title={
              check.verdict === "found"
                ? `Found at least ${check.occurrences} times`
                : "This console cannot see that phrase"
            }
          >
            <p style={{ margin: "0 0 var(--s2)" }}>
              {check.verdict === "found"
                ? "The real count may be higher: this reading covers the document's " +
                  "paragraphs, its table headers and its first few table rows, while " +
                  "the substitution reaches every cell, text box, header and footer."
                : "It is not in the text this console can read, which covers the " +
                  "paragraphs, the table headers and the first few table rows only. " +
                  "That is not the same as it not being in the document — check the " +
                  "spelling, and bind it anyway if you are sure."}
            </p>
            <Field label="Fill it with" htmlFor="docx-literal-field">
              <Select
                id="docx-literal-field"
                placeholder="Choose a field"
                options={FIELD_OPTIONS}
                value=""
                onChange={(e) => e.target.value && addDraft(e.target.value)}
              />
            </Field>
          </Banner>
        </div>
      )}

      <p className={`${s.muted} ${c.caption}`}>
        Each field can come from one phrase only, so choosing a field that is
        already taken moves it.
      </p>
    </>
  );
}
