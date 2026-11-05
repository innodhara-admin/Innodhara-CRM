/**
 * Reset — the destructive screen. 06_DESIGN.md §5.7, Task 24 Steps 1–3.
 *
 * Everything judged here is judged in `bundle/reset.ts`; this file renders it.
 *
 * ## Every quotation on this screen traces to a file in this repository
 *
 * There is **no product-manual quote on this screen**, and that absence is
 * deliberate: reset is not one of the sixteen checklist items and the manual
 * has no words for it. The two blocks below are the design's own, cited to
 * `06_DESIGN.md` §5.7. Inventing a plausible-sounding warning here would be the
 * costliest fabrication in the console — an operator would believe it at the
 * moment they are about to destroy data.
 *
 * **One quoted number is corrected in the console's own voice.** §5.7 says
 * "the twelve engine-only tables". `04_OPEN_QUESTIONS.md` Q13 names twelve, but
 * its own cited source — `03_API_SURFACE.md` §4.2 — lists **fourteen**, adding
 * `memory_chunks` and `lead_state_history`; all fourteen are in `WIPE`, checked
 * against the generated taxonomy. So the quote is rendered verbatim and then
 * corrected, which is `09` §4a's standing rule for a quotation known to be off:
 * quote it, then contradict it — never quote it alone.
 */
import { useMemo, useState } from "react";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { isApiError } from "../api/errors";
import { ResetRead, type ResetPreview } from "../api/reads";
import {
  ALL_FLAGS,
  CATALOGUE_ONLY,
  NO_FLAGS,
  blockedReason,
  bucketsFor,
  edgesApplyTo,
  selectedTotal,
  type BucketView,
  type ResetFlags,
} from "../bundle/reset";
import { useSession } from "../session/store";
import {
  Banner,
  Button,
  Checkbox,
  DataTable,
  Field,
  Masthead,
  Panel,
  Quote,
  Shell,
  TextInput,
  styles as s,
} from "../ui/primitives";
import { DriftBanner, SessionBar } from "../ui/SessionBar";
import { type DeletedMessage } from "../bundle/orgDelete";
import { DeleteOrganisation } from "./DeleteOrganisation";

/** A dry run. Read-only by construction — `dry_run: true` never commits. */
const dryRun = (flags: ResetFlags) =>
  request(endpoints.reset, {
    as: "org",
    method: "POST",
    body: { dry_run: true, ...flags },
    shape: ResetRead,
  });

function Counts({ view }: { view: BucketView }) {
  const [all, setAll] = useState(false);
  const rows = all ? view.tables : view.nonEmpty;

  if (view.total === null) {
    return (
      <>
        <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
          {view.tables.map((t) => t.table).join(" · ")}
        </p>
      </>
    );
  }

  return (
    <>
      {view.nonEmpty.length === 0 && !all ? (
        <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
          Every table in this group is already empty.
        </p>
      ) : (
        <DataTable
          columns={["Table", "Rows"]}
          rows={rows.map((t) => [
            <span key="t" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
              {t.table}
            </span>,
            <span key="n" className={s.mono}>
              {t.count}
            </span>,
          ])}
        />
      )}
      <Button variant="quiet" onClick={() => setAll(!all)}>
        {all
          ? `Show only the ${view.nonEmpty.length} with rows`
          : `Show all ${view.tables.length} tables`}
      </Button>
    </>
  );
}

export function Reset() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { org } = useSession();
  const [flags, setFlags] = useState<ResetFlags>({ ...NO_FLAGS, wipe_transactional: true });
  const [typedName, setTypedName] = useState("");
  const [report, setReport] = useState<ResetPreview | null>(null);
  // Set once "delete this organisation" succeeds; the org session is gone.
  const [deleted, setDeleted] = useState<DeletedMessage | null>(null);

  // Two dry runs, and the reason is in `reset.ts`: `counts` covers only the
  // flags it was called with, while `blocking_edges` is computed only for the
  // catalogue-only combination. One call cannot answer both.
  const [all, catalogueOnly] = useQueries({
    queries: [
      { queryKey: ["reset", "preview-all"], enabled: Boolean(org), queryFn: () => dryRun(ALL_FLAGS) },
      {
        queryKey: ["reset", "preview-catalogue-only"],
        enabled: Boolean(org),
        queryFn: () => dryRun(CATALOGUE_ONLY),
      },
    ],
  });

  const preview = all.data ?? null;
  const edges = catalogueOnly.data?.blocking_edges ?? [];
  const views = useMemo(() => bucketsFor(preview, flags), [preview, flags]);
  const total = selectedTotal(preview, flags);

  const blocked = org
    ? blockedReason({ flags, blockingEdges: edges, typedName, orgName: org.orgName })
    : "No organisation session.";

  const apply = useMutation({
    mutationFn: () =>
      request(endpoints.reset, {
        as: "org",
        method: "POST",
        body: { dry_run: false, ...flags, confirm_org_name: typedName.trim() },
        shape: ResetRead,
      }),
    onSuccess: (result) => {
      setReport(result);
      setTypedName("");
      // Everything the rail derives from has just changed.
      queryClient.invalidateQueries();
    },
  });

  const toggle = (flag: keyof ResetFlags) =>
    setFlags((f) => ({ ...f, [flag]: !f[flag] }));

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
          <Button variant="quiet" onClick={() => navigate("/bundle")}>
            Export a bundle first
          </Button>
        </>
      }
    >
      <DriftBanner />

      {deleted ? (
        <Panel eyebrow="Deleted" title="Organisation deleted">
          <Banner tone={deleted.tone}>
            <p style={{ margin: 0 }}>{deleted.text}</p>
          </Banner>
          <Button onClick={() => navigate("/sign-in")}>Sign in</Button>
        </Panel>
      ) : !org ? (
        <Panel eyebrow="No session" title="Sign in to continue">
          <Banner tone="warn" title="No organisation session">
            <p style={{ margin: 0 }}>A reset needs an organisation token.</p>
          </Banner>
        </Panel>
      ) : (
        <>
          <Panel eyebrow="Reset" title={`Clear data from ${org.orgName}`}>
            {/* Verbatim, from the design. There is no manual text for reset. */}
            <Quote source="Design, 06_DESIGN.md §5.7 (D6)">
              Resetting removes transactional data and, if you choose, the
              catalogue. Projects, plans, tasks and the twelve engine-only
              tables come back only by running the product — recording a meeting
              and confirming its review. This console cannot restore them.
            </Quote>
            <Banner tone="note" title="One correction to the sentence above">
              <p style={{ margin: 0 }}>
                It says <em>twelve</em> engine-only tables.{" "}
                <code>03_API_SURFACE.md</code> §4.2 — the source it is drawn
                from — lists <strong>fourteen</strong>, adding{" "}
                <code>memory_chunks</code> and <code>lead_state_history</code>.
                All fourteen are cleared by <code>wipe_transactional</code>.
              </p>
            </Banner>

            <ul style={{ maxInlineSize: "var(--measure)" }}>
              {/* Both bullets verbatim from 06_DESIGN.md §5.7. */}
              <li>
                The <strong>job queue and scheduler keep running</strong>. Wiping{" "}
                <code>jobs</code> mid-flight is a live-system hazard; idle the
                backend before applying, or expect a few rows to reappear.
              </li>
              <li>
                <strong>Staff accounts are never removed</strong>, whichever
                flags are set — including the account performing the reset.
              </li>
            </ul>
          </Panel>

          <Panel eyebrow="Step 1" title="Choose what to clear">
            <p style={{ maxInlineSize: "var(--measure)" }}>
              Three independent choices, not one button. A rehearsal reset
              clears transactional data only; a full reseed clears all three and
              re-imports a bundle.
            </p>
            {views
              .filter((v) => v.flag)
              .map((v) => (
                <Checkbox
                  key={v.bucket}
                  id={`flag-${v.bucket}`}
                  label={`${v.title} — ${
                    v.total === null ? "counting…" : `${v.total} row${v.total === 1 ? "" : "s"}`
                  }`}
                  checked={v.selected}
                  onChange={() => toggle(v.flag!)}
                />
              ))}

            <p className={s.muted} style={{ fontSize: "var(--text-sm)", maxInlineSize: "var(--measure)" }}>
              The counts beside each box come from a dry run made with{" "}
              <strong>all three</strong> selected, so you can see what each one
              would clear before choosing it. Only the boxes you tick are sent.
            </p>

            {total !== null && (
              <p className={s.mono}>
                {`Selected: ${total} row${total === 1 ? "" : "s"}`}
              </p>
            )}

            {(all.isError || catalogueOnly.isError) && (
              <Banner
                tone="blocked"
                title="This console could not read the preview"
                serverMessage={
                  isApiError(all.error) ? all.error.detail : String(all.error ?? catalogueOnly.error)
                }
              >
                <p style={{ margin: 0 }}>
                  Nothing below is the state of your organisation. Do not apply a
                  reset from a preview that failed.
                </p>
              </Banner>
            )}
          </Panel>

          {/* D22, at preview — Task 24 Step 2. Shown whenever the edges exist,
              not only once the combination is selected: a warning that appears
              after the choice has turned a stated refusal into a surprise. */}
          {edges.length > 0 && (
            <Banner
              tone={edgesApplyTo(flags) ? "blocked" : "warn"}
              title={
                edgesApplyTo(flags)
                  ? "This combination will be refused"
                  : "Clearing the catalogue on its own would be refused"
              }
            >
              <p style={{ marginBlockStart: 0 }}>
                These rows survive a catalogue-only reset and still reference
                what it would delete:
              </p>
              <DataTable
                columns={["Table", "Column", "References", "Rows"]}
                rows={edges.map((e) => [
                  <span key="t" className={s.mono}>{e.table}</span>,
                  <span key="c" className={s.mono}>{e.column}</span>,
                  <span key="r" className={s.mono}>{e.references}</span>,
                  <span key="n" className={s.mono}>{e.count}</span>,
                ])}
              />
              <p style={{ marginBlockEnd: 0 }}>
                The server's remedy: wipe transactional data too, or clear those
                rows first.{" "}
                {!edgesApplyTo(flags) &&
                  (flags.wipe_catalogue
                    ? "Transactional data is also ticked, so those rows are deleted first and nothing is orphaned — your current selection is fine."
                    : "Your current selection does not clear the catalogue at all, so this does not apply to it.")}
              </p>
            </Banner>
          )}

          {views.map((v) => (
            <Panel
              key={v.bucket}
              eyebrow={
                v.flag
                  ? `${v.selected ? "Selected" : "Not selected"} · ${v.flag}`
                  : "No flag reaches this"
              }
              title={v.title}
            >
              <p style={{ maxInlineSize: "var(--measure)" }}>{v.note}</p>
              <Counts view={v} />
            </Panel>
          ))}

          <Panel eyebrow="Step 2" title="Confirm">
            <Field
              label={`Type the organisation's name exactly: ${org.orgName}`}
              htmlFor="confirm-org"
            >
              <TextInput
                id="confirm-org"
                mono
                value={typedName}
                onChange={(e) => setTypedName(e.target.value)}
                placeholder={org.orgName}
              />
            </Field>

            {blocked && (
              <p className={s.muted} style={{ maxInlineSize: "var(--measure)" }}>
                {blocked}
              </p>
            )}

            <Button
              variant="danger"
              disabled={Boolean(blocked) || apply.isPending}
              onClick={() => apply.mutate()}
            >
              {apply.isPending
                ? "Applying…"
                : `Clear ${total ?? 0} row${total === 1 ? "" : "s"} — this cannot be undone`}
            </Button>

            {apply.isError && (
              <Banner
                tone="blocked"
                title="The server refused this reset"
                serverMessage={
                  isApiError(apply.error) ? apply.error.detail : String(apply.error)
                }
              >
                <p style={{ margin: 0 }}>Nothing was deleted.</p>
              </Banner>
            )}

            {report && (
              <Banner tone="note" title={`Reset applied — ${report.total} rows removed`}>
                <DataTable
                  columns={["Table", "Rows removed"]}
                  rows={Object.entries(report.counts)
                    .filter(([, n]) => n > 0)
                    .map(([table, n]) => [
                      <span key="t" className={s.mono}>{table}</span>,
                      <span key="n" className={s.mono}>{n}</span>,
                    ])}
                  empty="Nothing needed removing."
                />
                <p style={{ marginBlockEnd: 0 }}>
                  Re-import a bundle from{" "}
                  <Button variant="quiet" onClick={() => navigate("/bundle")}>
                    the bundle screen
                  </Button>{" "}
                  to restore the catalogue.
                </p>
              </Banner>
            )}
          </Panel>

          <DeleteOrganisation orgName={org.orgName} onDeleted={setDeleted} />
        </>
      )}
    </Shell>
  );
}
