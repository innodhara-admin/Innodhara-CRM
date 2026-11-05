/**
 * The import screen's shell — the rail beside it, and the session it needs.
 *
 * `Import.tsx` is the body and is deliberately free of routing, session and
 * layout: it takes no props, reads no session, and calls nothing. That is what
 * lets the whole parse → validate → preview path be reasoned about as three
 * pure functions with a table in front of them.
 *
 * The checklist rail stays visible here for the reason §5.1 gives about the
 * rail generally: importing is a way of satisfying checklist items, and the
 * statuses are what tell the operator whether the file did what they hoped.
 */
import { useNavigate } from "react-router-dom";

import { useChecklistReads } from "../checklist/useChecklistReads";
import { useSession } from "../session/store";
import { Banner, Button, Masthead, Panel, Shell, styles as s } from "../ui/primitives";
import { Rail } from "../ui/Rail";
import { DriftBanner, SessionBar } from "../ui/SessionBar";
import { Import } from "./Import";

export function ImportScreen() {
  const navigate = useNavigate();
  const { org } = useSession();
  const reads = useChecklistReads(Boolean(org));

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
          <hr className={s.ruleBreak} />
          {org && (
            <Rail
              reads={reads}
              selected={null}
              onSelect={(n) => navigate(`/checklist`, { state: { item: n } })}
            />
          )}
        </>
      }
    >
      <DriftBanner />
      {org ? (
        <Import />
      ) : (
        <Panel eyebrow="No session" title="Sign in to continue">
          <Banner tone="warn" title="No organisation session">
            <p style={{ margin: 0 }}>
              A file can be parsed and checked without one, but there would be
              nowhere to apply it and no statuses to change afterwards.
            </p>
          </Banner>
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Button variant="primary" onClick={() => navigate("/sign-in")}>
              Go to sign-in
            </Button>
          </div>
        </Panel>
      )}
    </Shell>
  );
}
