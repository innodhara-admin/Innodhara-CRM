/**
 * Every primitive in every state — Task 12 Step 4.
 *
 * This is how Task 12 is verifiable before any real screen exists. It is not a
 * decorative gallery: the vocabularies, the constraint patterns and the
 * citations below are read from the generated artefacts, so the page also
 * proves Task 11's pipeline reaches the UI layer rather than illustrating it
 * with invented values.
 */
import { useState } from "react";

import { CONSTRAINTS } from "../api/constraints.generated";
import { VOCAB } from "../api/vocabularies.generated";
import type { Enforcement } from "../ui/enforcement";
import {
  Banner,
  Button,
  Checkbox,
  DataTable,
  Eyebrow,
  Field,
  Masthead,
  Modal,
  Panel,
  Provenance,
  QuantityField,
  Quote,
  Select,
  Shell,
  StatusMarker,
  TextArea,
  TextInput,
  styles as s,
} from "../ui/primitives";
import { HandoffModal } from "../ui/HandoffModal";
import type { HandoffState } from "../session/handoff";
import { DriftBanner, SessionBar } from "../ui/SessionBar";
import { useTheme, type Theme } from "../ui/theme";

const THEMES: Theme[] = ["system", "light", "dark"];

/**
 * D18's three modal states, rendered here so they can be reviewed in a browser
 * without creating an organisation. The recovery state in particular is the one
 * an operator sees on the worst day this console has, and it should not first
 * be looked at during that day.
 */
const HANDOFF_STATES: Array<{ label: string; state: HandoffState }> = [
  { label: "running", state: { phase: "running", step: "login" } },
  {
    label: "step 1 failed",
    state: {
      phase: "failed",
      step: "create",
      error: {
        status: 409,
        kind: "http",
        detail: "Organisation slug 'meridian-data' already exists",
      },
      recovery: null,
    },
  },
  {
    label: "recovery",
    state: {
      phase: "failed",
      step: "password",
      error: {
        status: 422,
        kind: "http",
        detail: "New password must be at least 8 characters",
      },
      recovery: {
        orgId: "org-1",
        orgName: "Meridian Data",
        adminEmail: "ops@meridian.example.com",
        tempPassword: "Qx7-tmp-4kR2wZ",
        intendedPassword: "(the one you chose)",
      },
    },
  },
];

/** Real values from the lift, so the caption cannot drift from the server. */
const ASSIGNMENT_MODE = CONSTRAINTS.SettingsRequest.assignment_mode.pattern;
const RETENTION = CONSTRAINTS.SettingsRequest.audio_retention_days;

const ENFORCEMENTS: Array<{ enforcement: Enforcement; caption: string }> = [
  {
    enforcement: { kind: "schema" },
    caption: "1–50 characters, upper-cased on write",
  },
  {
    enforcement: {
      kind: "backend-undeclared",
      source: "admin.py · _validated_department",
    },
    caption: `one of ${VOCAB.department.join(", ")}`,
  },
  {
    enforcement: {
      kind: "backend-undeclared",
      source: "admin.py · SettingsRequest",
    },
    caption: `matches ${ASSIGNMENT_MODE} — dropped by the generator, recovered by the lift`,
  },
  {
    enforcement: {
      kind: "ui-only",
      why: "ops.py · upsert_playbook stores any string; a phase outside this list produces a playbook no plan will ever fire",
    },
    caption: `one of ${VOCAB.phase.join(", ")}`,
  },
];

export function Styleguide() {
  const [theme, setTheme] = useTheme();
  const [quantity, setQuantity] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [handoff, setHandoff] = useState<HandoffState | null>(null);

  return (
    <Shell
      rail={
        <>
          <Masthead />
          <Eyebrow>Task 12 · design tokens</Eyebrow>
          <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
            The rail is the checklist and is built in Task 16. Until then it holds
            the theme control, so both palettes can be reviewed here.
          </p>
          <hr className={s.ruleBreak} />
          <Eyebrow>Theme</Eyebrow>
          <div style={{ display: "flex", gap: "var(--s2)", marginBlockStart: "var(--s2)" }}>
            {THEMES.map((t) => (
              <Button
                key={t}
                variant={t === theme ? "primary" : "default"}
                aria-pressed={t === theme}
                onClick={() => setTheme(t)}
              >
                {t}
              </Button>
            ))}
          </div>
          <hr className={s.ruleBreak} />
          <SessionBar />
          <hr className={s.ruleBreak} />
          <Eyebrow>Status markers</Eyebrow>
          <ul style={{ listStyle: "none", padding: 0, margin: "var(--s3) 0 0" }}>
            {(
              [
                ["done", "satisfied", "Programs"],
                ["partial", "partial", "Email sending"],
                ["none", "not started", "Vendors"],
                ["blocked", "cannot be satisfied here", "Inbound mail"],
              ] as const
            ).map(([status, label, item]) => (
              <li
                key={status}
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: "var(--s2)",
                  padding: "var(--s2) 0",
                  borderBlockEnd: "1px solid var(--rule)",
                  fontSize: "var(--text-sm)",
                }}
              >
                <StatusMarker status={status} label={label} />
                <span>{item}</span>
                <span className={s.muted} style={{ marginInlineStart: "auto", fontSize: "var(--text-xs)" }}>
                  {label}
                </span>
              </li>
            ))}
          </ul>
        </>
      }
    >
      <DriftBanner />

      <Panel eyebrow="Type" title="Three roles, one voice">
        {/* The cite names the document, not the product: the masthead already
            carries the name, and repeating it here would be a second place to
            edit if D15 is ever reversed. */}
        <Quote source="Product manual, p. 6 — the go-live checklist">
          Work down this list before your first real client. The right-hand column
          is what actually happens if an item is skipped — these are the product's
          own refusal messages, not warnings invented here.
        </Quote>
        <hr className={s.ruleBreak} />
        <p style={{ maxInlineSize: "var(--measure)", margin: 0 }}>
          Interface text is set in the grotesque. It carries labels, help and
          controls, and it stays out of the way.
        </p>
        <p className={s.mono} style={{ marginBlockEnd: 0 }}>
          admin.py · CreateUserRequest — codes, keys, paths and JSON are mono.
        </p>
      </Panel>

      <Panel
        eyebrow="Forms"
        title="Every rule says who enforces it"
        actions={<Button variant="quiet">Reset</Button>}
      >
        <Banner tone="note" title="This is the signature of the interface">
          Under every control, in small mono, is who actually checks the rule.
          Three states: enforced and declared, enforced but not in the generated
          schema, and checked here only. The third is the one the operator is
          entitled to know about.
        </Banner>
        <div style={{ marginBlockStart: "var(--s4)" }}>
          {ENFORCEMENTS.map(({ enforcement, caption }) => (
            <div key={caption} style={{ paddingBlock: "var(--s3)" }}>
              <Provenance enforcement={enforcement} caption={caption} />
            </div>
          ))}
        </div>
      </Panel>

      <Panel eyebrow="Controls" title="Field states">
        <Field
          label="Programme code"
          htmlFor="sg-code"
          required
          enforcement={{ kind: "schema" }}
          caption="1–50 characters · upper-cased on write, so what you type comes back changed"
        >
          <TextInput id="sg-code" mono defaultValue="DC-COMMISSION" />
        </Field>

        <Field
          label="Department"
          htmlFor="sg-dept"
          enforcement={{
            kind: "backend-undeclared",
            source: "admin.py · _validated_department",
          }}
          caption="accounts is a department but not a role"
        >
          <Select
            id="sg-dept"
            options={VOCAB.department}
            placeholder="Not recorded"
            defaultValue="operations"
          />
        </Field>

        <Field
          label="Audio retention"
          htmlFor="sg-retention"
          enforcement={{
            kind: "backend-undeclared",
            source: "admin.py · SettingsRequest",
          }}
          caption={`${RETENTION.minimum}–${RETENTION.maximum} days`}
          error={`Enter a whole number between ${RETENTION.minimum} and ${RETENTION.maximum}.`}
        >
          <TextInput id="sg-retention" type="number" defaultValue={99999} invalid />
        </Field>

        <Field
          label="Default quantity"
          htmlFor="sg-qty"
          enforcement={{
            kind: "ui-only",
            why: "null means this org did not say how many, which the value estimate treats differently from a stated one",
          }}
          caption="leave unchecked when the quantity is not decided"
        >
          <QuantityField id="sg-qty" value={quantity} onChange={setQuantity} />
        </Field>

        <Field
          label="Proposal body"
          htmlFor="sg-body"
          required
          enforcement={{ kind: "schema" }}
          caption="at least 20 characters · Markdown"
        >
          <TextArea id="sg-body" mono defaultValue={"## Scope\n\nCommissioning and handover."} />
        </Field>

        <Field label="Send a copy" htmlFor="sg-copy">
          <Checkbox id="sg-copy" label="Copy the phase lead on this message" />
        </Field>
      </Panel>

      <Panel eyebrow="Feedback" title="What the server said">
        <div style={{ display: "grid", gap: "var(--s3)" }}>
          <Banner
            tone="warn"
            title="Credentials stored · sending is OFF on this server"
          >
            <p style={{ margin: 0 }}>
              Mail only leaves when both halves are set. EMAIL_MODE is a
              process-wide environment variable this console cannot change.
            </p>
          </Banner>
          <Banner
            tone="blocked"
            title="The skill could not be removed"
            serverMessage="3 open task(s) need 'rack-and-stack' and nobody else holds it. Give the skill to someone else first, or close that work."
          >
            <p style={{ margin: 0 }}>
              The server refused. Its message is shown exactly as it arrived.
            </p>
          </Banner>
        </div>
      </Panel>

      <Panel
        eyebrow="Rows"
        title="Programmes"
        actions={<Button variant="primary">Add programme</Button>}
      >
        <DataTable
          columns={["", "Code", "Name", "Pricing", "Template"]}
          rows={[
            [
              <StatusMarker key="a" status="done" label="complete" />,
              <span key="b" className={s.mono}>DC-COMMISSION</span>,
              "Datacentre commissioning",
              "v3 current",
              "v1 current",
            ],
            [
              <StatusMarker key="c" status="partial" label="partial" />,
              <span key="d" className={s.mono}>DC-AUDIT</span>,
              "Capacity audit",
              "v1 current",
              <span key="e" className={s.muted}>none</span>,
            ],
          ]}
        />
      </Panel>

      <Panel eyebrow="Hand-off" title="D18's three modal states">
        <p className={s.muted} style={{ margin: "0 0 var(--s4)" }}>
          None of these can be dismissed with Escape, a click outside, or Tab.
          The running state has no control at all; the two failures have one, and
          it says what it does.
        </p>
        <div style={{ display: "flex", gap: "var(--s3)", flexWrap: "wrap" }}>
          {HANDOFF_STATES.map(({ label, state }) => (
            <Button key={label} onClick={() => setHandoff(state)}>
              {label}
            </Button>
          ))}
        </div>
      </Panel>

      <Panel eyebrow="Buttons" title="Four weights, one accent">
        <div style={{ display: "flex", gap: "var(--s3)", flexWrap: "wrap" }}>
          <Button variant="primary">Publish new version</Button>
          <Button>Download template</Button>
          <Button variant="quiet">Cancel</Button>
          <Button variant="danger" onClick={() => setModalOpen(true)}>
            Reset organisation
          </Button>
          <Button disabled>Apply (needs zero errors)</Button>
        </div>
      </Panel>

      {handoff && (
        <HandoffModal state={handoff} onDismissFailure={() => setHandoff(null)} />
      )}

      {modalOpen && (
        <Modal title="This modal has no dismiss control">
          <p>
            D18's hand-off runs an unrecoverable chain, so its modal has no
            dismiss, no click-out and no escape key. Rather than a flag Task 14
            must remember to set, this primitive has no dismiss behaviour at all.
          </p>
          <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
            The button below exists only in the styleguide.
          </p>
          <Button variant="primary" onClick={() => setModalOpen(false)}>
            Close (styleguide only)
          </Button>
        </Modal>
      )}
    </Shell>
  );
}
