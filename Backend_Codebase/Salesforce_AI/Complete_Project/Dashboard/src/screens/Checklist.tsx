/**
 * The checklist screen — the rail, and whichever row is selected.
 *
 * Task 16 builds the rail and the status derivation. The panel beside it shows
 * what the console can say about one row **without an editing screen**: its
 * live status, the manual's own words, and what has to come first. The real
 * item screens arrive in Tasks 17–20 and replace this panel, one item at a
 * time; until then it says so rather than pretending to be one.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ITEM_BY_NUMBER, TIER_LABEL } from "../checklist/items";
import { ITEM_SCREENS } from "../checklist/screens";
import { deriveStatus } from "../checklist/status";
import { useChecklistReads } from "../checklist/useChecklistReads";
import { useSession } from "../session/store";
import {
  Banner,
  Button,
  Masthead,
  Panel,
  Quote,
  Shell,
  StatusMarker,
  styles as s,
} from "../ui/primitives";
import { Rail } from "../ui/Rail";
import { DriftBanner, SessionBar } from "../ui/SessionBar";

const SPOKEN = {
  done: "satisfied",
  partial: "partial",
  none: "not started",
  blocked: "cannot be satisfied here",
} as const;

export function Checklist() {
  const navigate = useNavigate();
  const { org } = useSession();
  const [selected, setSelected] = useState<number>(1);

  // Every read needs the organisation token. Without one they would all fail
  // identically and the rail would read as a broken API (see the hook).
  const reads = useChecklistReads(Boolean(org));
  const item = ITEM_BY_NUMBER.get(selected)!;
  const status = deriveStatus(item, reads);
  const Screen = ITEM_SCREENS[selected];

  return (
    <Shell
      rail={
        <>
          <Masthead />
          <SessionBar />
          <hr className={s.ruleBreak} />
          {org ? (
            <Rail reads={reads} selected={selected} onSelect={setSelected} />
          ) : (
            <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
              The checklist reads its status from the API, so it appears once an
              organisation session exists.
            </p>
          )}
          <hr className={s.ruleBreak} />
          {/* The rail says what is entered; this says whether it will work. */}
          <Button variant="quiet" onClick={() => navigate("/go-live")}>
            Go-live check
          </Button>
          <Button variant="quiet" onClick={() => navigate("/import")}>
            Import a file
          </Button>
          <Button variant="quiet" onClick={() => navigate("/bundle")}>
            Bundle
          </Button>
          <Button variant="quiet" onClick={() => navigate("/reset")}>
            Reset
          </Button>
          <Button variant="quiet" onClick={() => navigate("/styleguide")}>
            Styleguide
          </Button>
        </>
      }
    >
      <DriftBanner />

      {!org ? (
        <Panel eyebrow="No session" title="Sign in to continue">
          <Banner tone="warn" title="No organisation session">
            <p style={{ margin: 0 }}>
              Every status on this checklist is derived from a live read, and
              each of those reads needs an organisation token.
            </p>
          </Banner>
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Button variant="primary" onClick={() => navigate("/sign-in")}>
              Go to sign-in
            </Button>
          </div>
        </Panel>
      ) : Screen ? (
        // The item screens own their own heading, format panel and rows: the
        // overview below is what a row without a screen can still say.
        <Screen status={status} />
      ) : (
        <Panel
          eyebrow={`Item ${item.n} · ${TIER_LABEL[item.tier]}`}
          title={item.title}
        >
          <p
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: "var(--s2)",
              margin: "0 0 var(--s5)",
            }}
          >
            {status.marker === "pending" ? (
              <span className={s.muted}>Reading the API…</span>
            ) : (
              <>
                <StatusMarker status={status.marker} label={SPOKEN[status.marker]} />
                <span className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
                  {status.caption}
                </span>
              </>
            )}
          </p>

          {/* Verbatim, in the product's own voice (§9). */}
          <Quote source={item.manualRef}>{item.quote}</Quote>

          <p style={{ maxInlineSize: "var(--measure)" }}>
            <strong>If you skip it: </strong>
            {item.ifSkipped}
          </p>

          {item.dependsOn.length > 0 && (
            <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
              {"Needs first: "}
              {item.dependsOn
                .map((n) => `item ${n} — ${ITEM_BY_NUMBER.get(n)!.title}`)
                .join("; ")}
            </p>
          )}

          <hr className={s.ruleBreak} />
          <p className={s.muted} style={{ fontSize: "var(--text-sm)", margin: 0 }}>
            {item.entity
              ? "The form, the format panel and the current rows for this item are built in Tasks 17–20."
              : "This item has no entity to create: it is configured elsewhere, and the console reports it rather than editing it."}
          </p>
        </Panel>
      )}
    </Shell>
  );
}
