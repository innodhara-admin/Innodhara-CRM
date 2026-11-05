/**
 * The blocking hand-off modal — D18 / 06_DESIGN.md §4.2.
 *
 * **No dismiss control, no overlay click-out, no escape key, in either state.**
 * The `Modal` primitive has no dismiss behaviour at all, so there is nothing
 * here to remember to turn off, and it traps focus so the operator cannot Tab
 * out and act on the page behind while the chain is running.
 */
import {
  remainingCalls,
  STEP_LABEL,
  type HandoffState,
  type HandoffStep,
} from "../session/handoff";
import { Banner, Button, Modal, StatusMarker, styles as s } from "./primitives";

const ORDER: HandoffStep[] = ["create", "login", "password"];

function Steps({ current, failedAt }: { current: HandoffStep; failedAt?: HandoffStep }) {
  const currentIndex = ORDER.indexOf(current);
  return (
    <ol style={{ listStyle: "none", padding: 0, margin: "0 0 var(--s4)" }}>
      {ORDER.map((step, i) => {
        const done = i < currentIndex;
        const failed = failedAt === step;
        return (
          <li
            key={step}
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: "var(--s2)",
              padding: "var(--s2) 0",
              borderBlockEnd: "1px solid var(--rule)",
              fontSize: "var(--text-sm)",
            }}
          >
            <StatusMarker
              status={failed ? "blocked" : done ? "done" : i === currentIndex ? "partial" : "none"}
              label={failed ? "failed" : done ? "done" : i === currentIndex ? "in progress" : "not started"}
            />
            <span>{STEP_LABEL[step]}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function HandoffModal({
  state,
  onDismissFailure,
}: {
  state: HandoffState;
  /**
   * Only ever wired for a **failure**. There is no dismiss on the running
   * state, and the recovery state's control says what it does rather than
   * pretending to close a dialog.
   */
  onDismissFailure: () => void;
}) {
  if (state.phase === "done") return null;

  if (state.phase === "running") {
    return (
      <Modal title="Setting up the organisation">
        <Steps current={state.step} />
        <p className={s.muted} style={{ fontSize: "var(--text-sm)", margin: 0 }}>
          This runs as one operation and cannot be interrupted. The temporary
          password the server issues is held in memory and never shown — there is
          nothing here to copy, lose, or leave on a clipboard.
        </p>
      </Modal>
    );
  }

  // ── Failed ──────────────────────────────────────────────────────────────
  const { step, error, recovery } = state;

  // Step 1 failed: nothing was created, so there is nothing to recover and no
  // secret to reveal. Saying that plainly matters — an empty password box here
  // would read as "the recovery key is missing", which is far more alarming
  // than the truth.
  if (!recovery) {
    return (
      <Modal title="The organisation was not created">
        <Steps current={step} failedAt={step} />
        <Banner tone="blocked" title="Nothing was created" serverMessage={error.detail}>
          <p style={{ margin: 0 }}>
            The first step did not complete, so no organisation exists and no
            account was made. Fix what the server reported and submit again.
          </p>
        </Banner>
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Button variant="primary" onClick={onDismissFailure}>
            Back to the form
          </Button>
        </div>
      </Modal>
    );
  }

  // Steps 2 or 3 failed: the organisation EXISTS and this password is the only
  // way into it. Hiding it here would turn a recoverable failure into a
  // stranded organisation (§4.2), so it is revealed as a recovery key.
  return (
    <Modal title="Finish this by hand — the organisation exists">
      <Steps current={step} failedAt={step} />

      <Banner
        tone="blocked"
        title={`${STEP_LABEL[step]} failed`}
        serverMessage={error.detail}
      >
        <p style={{ margin: 0 }}>
          <strong>{recovery.orgName}</strong> was created and its administrator
          account exists, but the password you chose was not applied. The
          temporary password below is the only way to reach that account.
        </p>
      </Banner>

      <div style={{ marginBlockStart: "var(--s4)" }}>
        <p className={s.eyebrow}>Temporary password — shown once, recorded nowhere</p>
        <p
          className={s.serverMessage}
          style={{ fontSize: "var(--text-base)", userSelect: "all" }}
        >
          {recovery.tempPassword}
        </p>
        <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s2) 0 0" }}>
          Copy it before leaving this screen. It is not stored by the server in
          any readable form and this console cannot show it again. Without it{" "}
          <strong>{recovery.orgName}</strong> has no reachable administrator: there
          is no <code>PATCH /orgs/{"{id}"}</code>, and the password-reset route
          needs the very session that was never established.
        </p>
      </div>

      <div style={{ marginBlockStart: "var(--s4)" }}>
        <p className={s.eyebrow}>Two calls remain</p>
        <ol style={{ margin: "var(--s2) 0 0", paddingInlineStart: "1.2rem" }}>
          {remainingCalls(recovery).map((call) => (
            <li
              key={call}
              className={s.mono}
              style={{ fontSize: "var(--text-xs)", marginBlockEnd: "var(--s2)", overflowWrap: "anywhere" }}
            >
              {call}
            </li>
          ))}
        </ol>
        <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s2) 0 0" }}>
          Sign in as <span className={s.mono}>{recovery.adminEmail}</span> with the
          temporary password, then change it. After that, sign in here normally.
        </p>
      </div>

      <div style={{ marginBlockStart: "var(--s5)" }}>
        <Button variant="primary" onClick={onDismissFailure}>
          I have copied the temporary password
        </Button>
      </div>
    </Modal>
  );
}
