/**
 * Primitives — 06_DESIGN.md §9. Every screen in Tasks 14–24 is built from these.
 *
 * No component library (§2): MUI, Ant or shadcn would each guarantee the
 * generic-admin-panel look the brief rules out, and this surface is small
 * enough to own.
 */
import { useEffect, useRef } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  KeyboardEvent,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

import type { Enforcement } from "./enforcement";
import s from "./primitives.module.css";

/* ── Status markers (§6) ──────────────────────────────────────────────────── */

export type Status = "done" | "partial" | "none" | "blocked";

const MARKER: Record<Status, { glyph: string; className: string }> = {
  done: { glyph: "●", className: s.markerDone },      // ●
  partial: { glyph: "◐", className: s.markerPartial }, // ◐
  none: { glyph: "○", className: s.markerNone },       // ○
  blocked: { glyph: "—", className: s.markerBlocked }, // —
};

/**
 * `label` is required, not optional. A glyph alone is not a status to a screen
 * reader, and three of these four differ only by how much of a circle is
 * filled. The label is the status in words — "partial", "cannot be satisfied
 * here" — and it is what assistive technology reads.
 */
export function StatusMarker({ status, label }: { status: Status; label: string }) {
  const { glyph, className } = MARKER[status];
  return (
    <span className={`${s.marker} ${className}`} role="img" aria-label={label}>
      <span aria-hidden="true">{glyph}</span>
    </span>
  );
}

/* ── Button ───────────────────────────────────────────────────────────────── */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "quiet" | "danger";
};

const BUTTON_VARIANT = {
  default: "",
  primary: s.buttonPrimary,
  quiet: s.buttonQuiet,
  danger: s.buttonDanger,
} as const;

export function Button({ variant = "default", className = "", ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      className={`${s.button} ${BUTTON_VARIANT[variant]} ${className}`.trim()}
    />
  );
}

/* ── The provenance line — this interface's signature ─────────────────────── */

const PROVENANCE_CLASS: Record<Enforcement["kind"], string> = {
  schema: s.provenanceSchema,
  "backend-undeclared": s.provenanceUndeclared,
  "ui-only": s.provenanceUiOnly,
};

/**
 * Renders who enforces a rule, beneath the control it governs.
 *
 * Captions cite file and symbol, never line numbers — those are wrong within a
 * week (§9). A `ui-only` rule additionally carries a stamp, because the operator
 * is entitled to know that this console is the only thing checking it.
 */
export function Provenance({
  enforcement,
  caption,
}: {
  enforcement: Enforcement;
  caption: string;
}) {
  return (
    <p className={`${s.provenance} ${PROVENANCE_CLASS[enforcement.kind]}`}>
      {enforcement.kind === "ui-only" && <span className={s.stamp}>ui only</span>}
      <span className={s.provenanceText}>
        {caption}
        {enforcement.kind === "backend-undeclared" && (
          <>
            {" · "}
            {enforcement.source}
          </>
        )}
        {enforcement.kind === "ui-only" && (
          <>
            {" · "}
            {enforcement.why}
          </>
        )}
      </span>
    </p>
  );
}

/* ── Field ────────────────────────────────────────────────────────────────── */

type FieldProps = {
  label: string;
  htmlFor?: string;
  required?: boolean;
  enforcement?: Enforcement;
  caption?: string;
  error?: string;
  children: ReactNode;
};

export function Field({
  label,
  htmlFor,
  required,
  enforcement,
  caption,
  error,
  children,
}: FieldProps) {
  return (
    <div className={s.field}>
      <label className={s.fieldLabel} htmlFor={htmlFor}>
        {label}
        {required && (
          <span className={s.fieldRequired} aria-hidden="true">
            {" *"}
          </span>
        )}
      </label>
      <div className={s.fieldControl}>{children}</div>
      {enforcement && caption && (
        <Provenance enforcement={enforcement} caption={caption} />
      )}
      {error && (
        <p className={s.fieldMessage} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  mono?: boolean;
  invalid?: boolean;
};

export function TextInput({ mono, invalid, className = "", ...rest }: InputProps) {
  return (
    <input
      {...rest}
      aria-invalid={invalid || undefined}
      className={`${s.input} ${mono ? s.inputMono : ""} ${
        invalid ? s.inputError : ""
      } ${className}`.trim()}
    />
  );
}

export function TextArea({
  mono,
  invalid,
  className = "",
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { mono?: boolean; invalid?: boolean }) {
  return (
    <textarea
      {...rest}
      aria-invalid={invalid || undefined}
      className={`${s.textarea} ${mono ? s.inputMono : ""} ${
        invalid ? s.inputError : ""
      } ${className}`.trim()}
    />
  );
}

/**
 * `options` is usually a plain string list straight from `VOCAB` — the value
 * and the label are the same word, and that is the common case.
 *
 * It also accepts `{value, label}` for the pickers whose value is an opaque id:
 * a person, a programme. Those must send the id and show the name, and a select
 * that could only do one of the two would have every such screen hand-rolling
 * its own `<select>` and losing the shared styling and focus ring.
 */
export type Option = string | { value: string; label: string };

const optionValue = (o: Option) => (typeof o === "string" ? o : o.value);
const optionLabel = (o: Option) => (typeof o === "string" ? o : o.label);

export function Select({
  options,
  placeholder,
  className = "",
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & {
  options: readonly Option[];
  placeholder?: string;
}) {
  return (
    <select {...rest} className={`${s.select} ${className}`.trim()}>
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={optionValue(o)} value={optionValue(o)}>
          {optionLabel(o)}
        </option>
      ))}
    </select>
  );
}

export function Checkbox({
  label,
  id,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <div className={s.checkboxRow}>
      <input {...rest} id={id} type="checkbox" />
      <label htmlFor={id}>{label}</label>
    </div>
  );
}

/**
 * The tri-state quantity control (§3.3). Unchecked sends `null`, meaning "this
 * org did not say how many" — which the value estimate treats differently from
 * a stated one. Never a number pre-filled with 1: flattening this was a real
 * regression, and `admin.py · PricingItem` carries ten lines explaining it.
 */
export function QuantityField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: number | null;
  onChange: (next: number | null) => void;
}) {
  const stated = value !== null;
  return (
    <div className={s.triState}>
      <div className={s.checkboxRow}>
        <input
          id={id}
          type="checkbox"
          checked={stated}
          onChange={(e) => onChange(e.target.checked ? 1 : null)}
        />
        <label htmlFor={id}>This org states a quantity</label>
      </div>
      <TextInput
        className={s.triStateNumber}
        type="number"
        min={0}
        step="any"
        disabled={!stated}
        aria-label="Default quantity"
        value={stated ? value : ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
      />
    </div>
  );
}

/* ── Panel, quote, table, banner, modal ───────────────────────────────────── */

export function Panel({
  title,
  eyebrow,
  actions,
  children,
}: {
  title?: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={s.panel}>
      {(title || actions) && (
        <header className={s.panelHeader}>
          <div>
            {eyebrow && <p className={s.eyebrow}>{eyebrow}</p>}
            {title && <h2 className={s.panelTitle}>{title}</h2>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

/**
 * The manual's own words, verbatim. Set in the serif, because the product's
 * voice is the strongest asset on the page and is what stops this reading as a
 * bootstrapped admin panel (§9). Never paraphrase what goes in here.
 */
export function Quote({ children, source }: { children: ReactNode; source?: string }) {
  return (
    <blockquote className={s.quote}>
      {children}
      {source && <cite className={s.quoteSource}>{source}</cite>}
    </blockquote>
  );
}

export function DataTable({
  columns,
  rows,
  empty = "Nothing here yet.",
}: {
  columns: readonly string[];
  rows: ReactNode[][];
  empty?: string;
}) {
  return (
    <div className={s.tableScroll}>
      <table className={s.table}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className={s.tableEmpty} colSpan={columns.length}>
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((cells, i) => (
              <tr key={i}>
                {cells.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export type BannerTone = "note" | "warn" | "blocked";

const BANNER_TONE: Record<BannerTone, string> = {
  note: s.bannerNote,
  warn: s.bannerWarn,
  blocked: s.bannerBlocked,
};

export function Banner({
  tone = "note",
  title,
  children,
  serverMessage,
}: {
  tone?: BannerTone;
  title?: string;
  children?: ReactNode;
  /** The server's own refusal, verbatim. Rendered as a quotation, not reworded. */
  serverMessage?: string;
}) {
  return (
    <div className={`${s.banner} ${BANNER_TONE[tone]}`} role={tone === "note" ? undefined : "alert"}>
      <div className={s.bannerBody}>
        {title && <p className={s.bannerTitle}>{title}</p>}
        {children && <div className={s.bannerText}>{children}</div>}
        {serverMessage && <p className={s.serverMessage}>{serverMessage}</p>}
      </div>
    </div>
  );
}

/**
 * A modal with no dismiss control by design.
 *
 * D18's hand-off modal must have no dismiss, no overlay click-out and no escape
 * key in either state, because the chain it runs is unrecoverable if abandoned
 * halfway. Rather than offer a `dismissible` flag that Task 14 must remember to
 * turn off, this primitive has no dismiss behaviour at all — nothing here
 * listens for Escape and the scrim has no click handler. A modal that can be
 * dismissed is a different component, and none is needed yet.
 */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({ title, children }: { title: string; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);

  // Focus moves into the dialog and stays there. "No dismiss control" has to
  // mean the whole surface, not just the absent close X.
  // The panel itself, not its first control. Focusing the button scrolled the
  // recovery dialog past its own heading — "the organisation exists" is the
  // sentence that explains why a password is on screen at all, and the operator
  // landed below it. Focusing the container starts at the top and still gives
  // screen readers the title first; Tab reaches the control immediately.
  useEffect(() => {
    panel.current?.focus();
  }, []);

  // The Tab handler below only fires while focus is ALREADY inside the panel,
  // which is not enough — verified in a browser: clicking the scrim moves focus
  // to <body>, and Tab from there walks the page behind, landing on the rail.
  // The modal stayed open the whole time, so it looked contained and was not.
  // This pulls any focus outside the panel straight back in, which also covers
  // Shift+Tab off the first element and a focus() call from anywhere else.
  useEffect(() => {
    function onFocusIn(event: FocusEvent) {
      const el = panel.current;
      if (!el || !(event.target instanceof Node) || el.contains(event.target)) return;
      el.focus();
    }
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return;
    const items = [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === panel.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className={s.modalScrim} role="dialog" aria-modal="true" aria-label={title}>
      {/* No onClick on the scrim, and no Escape listener anywhere: this
          primitive has no dismiss behaviour to forget to turn off. */}
      <div className={s.modal} ref={panel} tabIndex={-1} onKeyDown={onKeyDown}>
        <h2 className={s.modalTitle}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

/* ── Shell ────────────────────────────────────────────────────────────────── */

export function Shell({ rail, children }: { rail: ReactNode; children: ReactNode }) {
  return (
    <div className={s.shell}>
      <aside className={s.rail}>{rail}</aside>
      <main className={s.content}>
        <div className={s.contentInner}>{children}</div>
      </main>
    </div>
  );
}

export function Masthead() {
  return (
    <h1 className={s.masthead}>
      <span className={s.mastheadName} />
      <span className={s.mastheadSuffix}>Setup Console</span>
    </h1>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className={s.eyebrow}>{children}</p>;
}

export const styles = s;
