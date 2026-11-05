/**
 * The go-live check — 06_DESIGN.md §5.6.
 *
 * **The sheet you read before you turn the product on**, and the screen that
 * makes this console more than sixteen forms. Everything here is derived in
 * `checklist/golive.ts` from reads the rail has already fetched; this file only
 * renders it, so nothing on screen is a judgement made in JSX.
 *
 * Three deliberate absences, all of them §9's:
 *
 *  - **No score and no percentage.** Six checks, each with its own marker and
 *    its own rows. "83% ready" averages an unpriced offering against a rank tie.
 *  - **No "you are ready" verdict.** The sheet reports; the operator signs off.
 *    A console that declares readiness owns a decision it cannot be accountable
 *    for, and check 6 alone can be unanswerable (P7).
 *  - **No re-fetch button.** These are the rail's own reads, live through
 *    React Query. A refresh control would imply the numbers go stale silently.
 */
import { useNavigate } from "react-router-dom";

import { runGoLive, type Check, type CheckRow } from "../checklist/golive";
import { useChecklistReads } from "../checklist/useChecklistReads";
import { useSession } from "../session/store";
import {
  Banner,
  Button,
  DataTable,
  Masthead,
  Panel,
  Quote,
  Shell,
  StatusMarker,
  styles as s,
  type Status,
} from "../ui/primitives";
import { DriftBanner, SessionBar } from "../ui/SessionBar";

const SPOKEN: Record<Status, string> = {
  done: "satisfied",
  partial: "partial",
  none: "not started",
  blocked: "cannot be answered here",
};

function Marker({ marker }: { marker: Check["marker"] }) {
  if (marker === "pending") {
    return <span className={s.muted}>reading…</span>;
  }
  return <StatusMarker status={marker} label={SPOKEN[marker]} />;
}

function Rows({ rows }: { rows: CheckRow[] }) {
  return (
    <DataTable
      columns={["", "What", "What is true about it"]}
      rows={rows.map((r) => [
        <Marker key="m" marker={r.marker} />,
        // `nowrap` because these are identifiers — a skill, a programme code, a
        // kind/channel pair. `power-commissioning` broken across two lines at
        // its hyphen reads as two different things. The table already scrolls
        // inside its own container, so a long one costs no page-level overflow.
        <span
          key="s"
          className={s.mono}
          style={{ fontSize: "var(--text-xs)", whiteSpace: "nowrap" }}
        >
          {r.subject}
        </span>,
        r.detail,
      ])}
    />
  );
}

function CheckPanel({ check }: { check: Check }) {
  return (
    <Panel eyebrow={`Check ${check.n}`} title={check.title}>
      <p
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: "var(--s2)",
          margin: "0 0 var(--s4)",
        }}
      >
        <Marker marker={check.marker} />
        <span className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
          {check.summary}
        </span>
      </p>

      {check.rows.length > 0 && <Rows rows={check.rows} />}

      {/* A6: the domain check must say which source answered it, because the
          three sources are not equally strong and one of them cannot pass. */}
      {check.source && (
        <p
          className={s.muted}
          style={{ fontSize: "var(--text-sm)", marginBlockEnd: 0 }}
        >
          {"Answered from: "}
          {check.source}
        </p>
      )}
    </Panel>
  );
}

export function GoLive() {
  const navigate = useNavigate();
  const { org } = useSession();
  const reads = useChecklistReads(Boolean(org));
  const checks = runGoLive(reads, { emailDomain: org?.emailDomain });

  return (
    <Shell
      rail={
        <>
          <Masthead />
          <SessionBar />
          <hr className={s.ruleBreak} />
          <Button variant="quiet" onClick={() => navigate("/checklist")}>
            Back to the checklist
          </Button>
          <Button variant="quiet" onClick={() => navigate("/import")}>
            Import a file
          </Button>
        </>
      }
    >
      <DriftBanner />

      {!org ? (
        <Panel eyebrow="No session" title="Sign in to continue">
          <Banner tone="warn" title="No organisation session">
            <p style={{ margin: 0 }}>
              Every check on this sheet is derived from a live read, and each of
              those reads needs an organisation token.
            </p>
          </Banner>
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Button variant="primary" onClick={() => navigate("/sign-in")}>
              Go to sign-in
            </Button>
          </div>
        </Panel>
      ) : (
        <>
          <Panel eyebrow="Go-live check" title="Before you turn it on">
            {/* Verbatim, from "BEFORE YOU GO LIVE". Never paraphrased (§9). */}
            <Quote source="Product manual, p. 7 · BEFORE YOU GO LIVE">
              at least one person holds each skill your rate card implies; the
              quickest check is to open any project after the first meeting and
              confirm every task shows a named person rather than the phase
              lead.
            </Quote>
            <p style={{ maxInlineSize: "var(--measure)" }}>
              Check 1 below is that test, run against your data instead of
              against a project — so a skill nobody holds is found now rather
              than in front of a client. The other five are the rest of what has
              to be true for the same reason.
            </p>
            <p style={{ maxInlineSize: "var(--measure)" }}>
              Each check names the part of the backend it is asserting, so a
              result can be argued with rather than only believed.{" "}
              <strong>This sheet does not declare you ready</strong> — it
              reports what is true, and the sign-off is yours.
            </p>
          </Panel>

          {checks.map((check) => (
            <CheckPanel key={check.id} check={check} />
          ))}
        </>
      )}
    </Shell>
  );
}
