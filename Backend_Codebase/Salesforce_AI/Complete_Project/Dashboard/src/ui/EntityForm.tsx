/**
 * One form, driven entirely by a descriptor — 07_BUILD_PLAN.md Task 17 Step 1.
 *
 * Every item screen in Tasks 17–20 renders this rather than hand-building
 * controls, so a field added to a descriptor appears in the form, in the format
 * panel, in the CSV template and in the import validator at once (§3.4).
 *
 * **Not `react-hook-form`.** The plan named it, and it was not used: the whole
 * validation surface is `validate(descriptor, values)` — a pure function over a
 * plain object, already tested without a DOM — and a form library's value here
 * would be the resolver plumbing that function replaces. Adding a dependency to
 * wrap seven `useState` calls would spend §2's dependency budget on nothing.
 * The deviation is recorded in `07`'s Task 17 rather than left to be noticed.
 *
 * Two behaviours worth stating, because both are deliberate:
 *
 *  - **Errors appear on submit, not on keystroke.** A message that arrives
 *    while the operator is still mid-word is noise; §9 allows no motion, and a
 *    caption that flickers is motion. Once a field has been marked, it
 *    re-validates as it is corrected, so the mark clears as soon as it is true.
 *  - **The server's refusal is rendered verbatim** and never merged into the
 *    field errors. Its wording is the backend's, it already says what to do,
 *    and this console is not in a position to say it better (§4.1).
 */
import { useState } from "react";
import type { ReactNode } from "react";

import type { Descriptor, FieldRule } from "../descriptors/types";
import type { ApiError } from "../api/errors";
import { bodyFor, emptyRow, validate } from "./entityValidation";
import {
  Banner,
  Button,
  Checkbox,
  Field,
  QuantityField,
  Select,
  TextArea,
  TextInput,
  styles as s,
} from "./primitives";

export type Row = Record<string, unknown>;

/**
 * A control the descriptor cannot describe — the pricing line editor, the
 * person picker fed from `GET /admin/users`. Keyed by field name so a screen
 * overrides one control without taking over the form.
 */
export type Slots = Record<
  string,
  (props: { value: unknown; onChange: (next: unknown) => void; id: string; invalid: boolean }) => ReactNode
>;

function Control({
  rule,
  id,
  value,
  invalid,
  onChange,
}: {
  rule: FieldRule;
  id: string;
  value: unknown;
  invalid: boolean;
  onChange: (next: unknown) => void;
}) {
  switch (rule.control) {
    case "select":
      return (
        <Select
          id={id}
          options={rule.options ?? []}
          placeholder="Not set"
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "checkbox":
      return (
        <Checkbox
          id={id}
          label={rule.caption}
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
      );
    case "textarea":
    case "json":
      return (
        <TextArea
          id={id}
          mono={rule.control === "json"}
          invalid={invalid}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "number":
      return (
        <TextInput
          id={id}
          type="number"
          invalid={invalid}
          value={value === null || value === undefined ? "" : String(value)}
          // "" rather than 0: an empty number box means "not supplied", and
          // sending 0 for `max_open_tasks` would assign nobody any work.
          onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        />
      );
    case "quantity":
      return (
        <QuantityField
          id={id}
          value={typeof value === "number" ? value : null}
          onChange={onChange}
        />
      );
    default:
      return (
        <TextInput
          id={id}
          invalid={invalid}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}

export function EntityForm({
  descriptor,
  submitLabel,
  onSubmit,
  busy,
  serverError,
  initial,
  slots,
  only,
  resetSignal,
  children,
}: {
  descriptor: Descriptor;
  submitLabel: string;
  /**
   * Receives the **body**, not the raw form state: blanks dropped, unknown keys
   * gone, `writeOnly` directives kept. Handing back the raw values was a real
   * defect — the form validated `bodyFor(values)` and then posted `values`, so
   * an untouched `working_days` box went out as `""` and the server answered
   * *"Input should be a valid list"* for a field the operator never saw. What
   * was checked and what is sent must be the same object.
   */
  onSubmit: (body: Row) => void;
  busy?: boolean;
  serverError?: ApiError | null;
  initial?: Row;
  slots?: Slots;
  /** Render only these fields, in this order. Defaults to all of them. */
  only?: readonly string[];
  /**
   * Bump this after a successful create to clear the form back to blank.
   *
   * Not the default, because the two families want opposite things. On the
   * create-many screens — staff, offerings, message templates — a form still
   * holding the last person's details after "Create account" is a trap: the
   * operator reads it as empty, edits one field and creates a near-duplicate.
   * On the **versioned** families it is the opposite: publishing v2 of a rate
   * card starts from v1's lines and changes one price, so clearing would make
   * every new version a retype.
   */
  resetSignal?: number;
  children?: ReactNode;
}) {
  const blank = () => ({ ...emptyRow(descriptor), ...initial });
  const [values, setValues] = useState<Row>(blank);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);

  const [seenSignal, setSeenSignal] = useState(resetSignal);
  if (resetSignal !== seenSignal) {
    // Render-phase reset rather than an effect: this is derived state, and an
    // effect would paint the stale values for one frame first.
    setSeenSignal(resetSignal);
    setValues(blank());
    setErrors({});
    setSubmitted(false);
  }

  const fields = only
    ? only.map((f) => descriptor.fields.find((r) => r.field === f)!).filter(Boolean)
    : descriptor.fields;

  function set(field: string, next: unknown) {
    const updated = { ...values, [field]: next };
    setValues(updated);
    // Only after a first submit: re-validating from the first keystroke marks
    // every required field red before the operator has reached it.
    if (submitted) setErrors(validate(descriptor, updated));
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    const found = validate(descriptor, values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    onSubmit(bodyFor(descriptor, values));
  }

  return (
    <form onSubmit={submit} noValidate>
      {serverError && (
        <div style={{ marginBlockEnd: "var(--s4)" }}>
          <Banner
            tone="blocked"
            title="The server refused this"
            serverMessage={serverError.detail}
          >
            <p style={{ margin: 0 }}>
              Nothing was created. The message below is the server's own, word for
              word.
            </p>
          </Banner>
        </div>
      )}

      {fields.map((rule) => {
        const id = `${descriptor.key}-${rule.field}`;
        // A nested error — `items.0.unit_price` — belongs to the control that
        // owns `items`, or it is reported against no field at all and the
        // operator sees "1 field needs attention" with nothing marked.
        const nested = Object.entries(errors).find(([path]) =>
          path.startsWith(`${rule.field}.`),
        );
        const message =
          errors[rule.field] ??
          (nested ? `${nested[0].replace(`${rule.field}.`, "line ")}: ${nested[1]}` : undefined);
        const invalid = Boolean(message);
        const slot = slots?.[rule.field];
        return (
          <Field
            key={rule.field}
            label={rule.label}
            htmlFor={id}
            enforcement={rule.enforcement}
            caption={rule.caption}
            error={message}
          >
            {slot
              ? slot({ value: values[rule.field], onChange: (n) => set(rule.field, n), id, invalid })
              : (
                <Control
                  rule={rule}
                  id={id}
                  value={values[rule.field]}
                  invalid={invalid}
                  onChange={(next) => set(rule.field, next)}
                />
              )}
          </Field>
        );
      })}

      {children}

      <div style={{ display: "flex", gap: "var(--s3)", marginBlockStart: "var(--s5)" }}>
        <Button variant="primary" type="submit" disabled={busy}>
          {busy ? "Working…" : submitLabel}
        </Button>
        {submitted && Object.keys(errors).length > 0 && (
          <p className={s.muted} style={{ fontSize: "var(--text-sm)", alignSelf: "center", margin: 0 }}>
            {Object.keys(errors).length === 1
              ? "One field needs attention."
              : `${Object.keys(errors).length} fields need attention.`}
          </p>
        )}
      </div>
    </form>
  );
}
