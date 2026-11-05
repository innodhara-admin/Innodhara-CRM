/**
 * The reseed bundle — export and re-import. 06_DESIGN.md §5.8, Task 24 Step 4.
 *
 * The one quotation on this screen is §5.8's own sentence about staff, cited to
 * the design. There is no product-manual text for the bundle, and none is
 * invented.
 *
 * **The file is offered as a data: URL the operator clicks**, not written by
 * script. Nothing here reaches outside the origin.
 */
import { useMemo, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { isApiError } from "../api/errors";
import { schemas } from "../api/generated";
import {
  ApprovalRulesRead,
  DemoTeamsRead,
  MessageTemplatesRead,
  PlaybooksRead,
  PricingRead,
  ProgramsRead,
  ProposalTemplatesRead,
  SkillsRead,
  VendorsRead,
} from "../api/reads";
import {
  bundleFilename,
  bundleTally,
  buildBundle,
  rowsFromReads,
  serialiseBundle,
  skippedFromReads,
  type Bundle,
} from "../bundle/export";
import { applyBundle, parseBundle, type BundleReport } from "../bundle/import";
import { BUNDLE_ENTITIES, DESCRIPTORS } from "../descriptors";
import type { EntityKey } from "../descriptors/types";
import { useSession } from "../session/store";
import {
  Banner,
  Button,
  DataTable,
  Masthead,
  Panel,
  Quote,
  Shell,
  styles as s,
} from "../ui/primitives";
import { DriftBanner, SessionBar } from "../ui/SessionBar";

/** Write fields per entity, from `generated.ts` — never a hand-kept list. */
const WRITE_FIELDS = Object.fromEntries(
  BUNDLE_ENTITIES.map((key) => {
    const shape = (schemas[DESCRIPTORS[key].writeSchema] as { shape?: object }).shape;
    return [key, shape ? Object.keys(shape) : []];
  }),
) as Partial<Record<EntityKey, readonly string[]>>;

export function Bundle() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { org } = useSession();
  const fileInput = useRef<HTMLInputElement>(null);
  const [incoming, setIncoming] = useState<string | null>(null);
  const [filename, setFilename] = useState<string>("");
  const [report, setReport] = useState<BundleReport | null>(null);
  const [running, setRunning] = useState(false);

  const enabled = Boolean(org);
  const [programs, skills, messageTemplates, playbooks, approvalRules, demoTeams, vendors] =
    useQueries({
      queries: [
        { queryKey: ["programs"], enabled, queryFn: () => request(endpoints.programs, { as: "org", shape: ProgramsRead }) },
        { queryKey: ["skills"], enabled, queryFn: () => request(endpoints.skills, { as: "org", shape: SkillsRead }) },
        { queryKey: ["messageTemplates"], enabled, queryFn: () => request(endpoints.messageTemplates, { as: "org", shape: MessageTemplatesRead }) },
        { queryKey: ["playbooks"], enabled, queryFn: () => request(endpoints.playbooks, { as: "org", shape: PlaybooksRead }) },
        { queryKey: ["approvalRules"], enabled, queryFn: () => request(endpoints.approvalRules, { as: "org", shape: ApprovalRulesRead }) },
        { queryKey: ["demoTeams"], enabled, queryFn: () => request(endpoints.demoTeams, { as: "org", shape: DemoTeamsRead }) },
        { queryKey: ["vendors"], enabled, queryFn: () => request(endpoints.vendors, { as: "org", shape: VendorsRead }) },
      ],
    });

  // Items 5 and 6 fan out per programme, exactly as the rail does.
  const activeIds = (programs.data ?? []).filter((p) => p.is_active).map((p) => p.id);
  const pricingQueries = useQueries({
    queries: activeIds.map((id) => ({
      queryKey: ["pricing", id],
      queryFn: () => request(endpoints.pricing(id), { as: "org", shape: PricingRead }),
    })),
  });
  const templateQueries = useQueries({
    queries: activeIds.map((id) => ({
      queryKey: ["proposalTemplates", id],
      queryFn: () => request(endpoints.proposalTemplates(id), { as: "org", shape: ProposalTemplatesRead }),
    })),
  });

  const reads = [programs, skills, messageTemplates, playbooks, approvalRules, demoTeams, vendors];
  const loading =
    reads.some((q) => q.isLoading) ||
    pricingQueries.some((q) => q.isLoading) ||
    templateQueries.some((q) => q.isLoading);
  const failed = [...reads, ...pricingQueries, ...templateQueries].find((q) => q.isError);

  const bundle: Bundle | null = useMemo(() => {
    if (!org || loading || failed || !programs.data) return null;
    if (pricingQueries.some((q) => !q.data) || templateQueries.some((q) => !q.data)) return null;
    return buildBundle({
      org: { id: org.orgId, name: org.orgName },
      rows: rowsFromReads({
        programs: programs.data,
        programRows: programs.data as unknown as Record<string, unknown>[],
        skills: (skills.data ?? []) as unknown as Record<string, unknown>[],
        pricingByProgram: Object.fromEntries(
          activeIds.map((id, i) => [id, (pricingQueries[i].data ?? []) as unknown as Record<string, unknown>[]]),
        ),
        templatesByProgram: Object.fromEntries(
          activeIds.map((id, i) => [id, (templateQueries[i].data ?? []) as unknown as Record<string, unknown>[]]),
        ),
        messageTemplates: (messageTemplates.data ?? []) as unknown as Record<string, unknown>[],
        playbooks: (playbooks.data ?? []) as unknown as Record<string, unknown>[],
        approvalRules: (approvalRules.data ?? []) as unknown as Record<string, unknown>[],
        demoTeams: (demoTeams.data ?? []) as unknown as Record<string, unknown>[],
        vendors: (vendors.data ?? []) as unknown as Record<string, unknown>[],
      }),
      writeFields: WRITE_FIELDS,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org, loading, failed, programs.data, skills.data, messageTemplates.data, playbooks.data,
      approvalRules.data, demoTeams.data, vendors.data,
      pricingQueries.map((q) => q.data).join(), templateQueries.map((q) => q.data).join()]);

  // Rows the export deliberately dropped. Same inputs as the bundle above, so
  // the summary and the file cannot disagree about what was carried.
  const skipped = useMemo(
    () =>
      programs.data
        ? skippedFromReads({
            programs: programs.data,
            templatesByProgram: Object.fromEntries(
              activeIds.map((id, i) => [
                id,
                (templateQueries[i].data ?? []) as unknown as Record<string, unknown>[],
              ]),
            ),
          })
        : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [programs.data, activeIds.join(), templateQueries.map((q) => q.data).join()],
  );

  const parsed =
    incoming && org
      ? parseBundle(incoming, { orgId: org.orgId, orgName: org.orgName })
      : null;

  async function runImport() {
    if (!parsed || "fatal" in parsed || !org) return;
    setRunning(true);
    setReport(null);
    try {
      const existing = Object.fromEntries(
        (programs.data ?? []).map((p) => [p.code.toUpperCase(), p.id]),
      );
      const result = await applyBundle({ parsed, existingProgramIds: existing });
      setReport(result);
      queryClient.invalidateQueries();
    } finally {
      setRunning(false);
    }
  }

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
          <Button variant="quiet" onClick={() => navigate("/reset")}>
            Reset
          </Button>
        </>
      }
    >
      <DriftBanner />

      {!org ? (
        <Panel eyebrow="No session" title="Sign in to continue">
          <Banner tone="warn" title="No organisation session">
            <p style={{ margin: 0 }}>A bundle is read from, and written to, one organisation.</p>
          </Banner>
        </Panel>
      ) : (
        <>
          <Panel eyebrow="Bundle" title="Export, reset, re-import">
            <p style={{ maxInlineSize: "var(--measure)" }}>
              One JSON file holding the{" "}
              <strong>{BUNDLE_ENTITIES.length} entity types</strong> a reset can
              clear. The bundle and the reset flags are one mechanism:
              everything the bundle carries, the reset can clear, and nothing
              else.
            </p>
            {/* Verbatim, from the design. §5.8 asks for it at the point of export. */}
            <Quote source="Design, 06_DESIGN.md §5.8">
              Staff accounts are not exported. They are never removed by a reset
              — the account you are signed in as is one of them — so there is
              nothing to restore.
            </Quote>
            <p className={s.muted} style={{ fontSize: "var(--text-sm)", maxInlineSize: "var(--measure)" }}>
              A bundle is stamped with the organisation that made it and this
              console refuses one from anywhere else: skills round-trip on user
              id, and those ids belong to the organisation that exported them.
              It is a reseed loop, not a way to copy one organisation into
              another.
            </p>
          </Panel>

          <Panel eyebrow="Export" title="Take a bundle now">
            {failed ? (
              <Banner
                tone="blocked"
                title="This console could not read everything the bundle needs"
                serverMessage={isApiError(failed.error) ? failed.error.detail : String(failed.error)}
              >
                <p style={{ margin: 0 }}>
                  No bundle is offered. A partial bundle would restore a partial
                  organisation and look complete doing it.
                </p>
              </Banner>
            ) : !bundle ? (
              <p className={s.muted}>Reading the organisation…</p>
            ) : (
              <>
                <DataTable
                  columns={["Entity", "Rows"]}
                  rows={bundleTally(bundle).map((t) => [
                    <span key="k" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
                      {t.key}
                    </span>,
                    <span key="n" className={s.mono}>{t.rows}</span>,
                  ])}
                />
                {skipped.length > 0 && (
                  <div style={{ marginBlockStart: "var(--s4)" }}>
                    <Banner
                      tone="warn"
                      title={
                        skipped.length === 1
                          ? "One template is not in this bundle"
                          : `${skipped.length} templates are not in this bundle`
                      }
                    >
                      <p style={{ margin: "0 0 var(--s2)" }}>{skipped[0].reason}</p>
                      <ul style={{ margin: 0, paddingInlineStart: "var(--s5)" }}>
                        {skipped.map((sk) => (
                          <li
                            key={sk.label}
                            className={s.mono}
                            style={{ fontSize: "var(--text-xs)" }}
                          >
                            {sk.label}
                          </li>
                        ))}
                      </ul>
                    </Banner>
                  </div>
                )}
                <p style={{ maxInlineSize: "var(--measure)" }}>
                  Only the <strong>current</strong> version of each rate card,
                  proposal template, message template and playbook is exported. A
                  reseed restores the state, not the version history — each of
                  those endpoints creates a new version per write, so restoring
                  a whole history would rebuild it in import order with the
                  wrong one current.
                </p>
                <a
                  className={s.button}
                  href={`data:application/json;charset=utf-8,${encodeURIComponent(serialiseBundle(bundle))}`}
                  download={bundleFilename(bundle)}
                >
                  {`Download ${bundleFilename(bundle)}`}
                </a>
              </>
            )}
          </Panel>

          <Panel eyebrow="Re-import" title="Restore from a bundle">
            <input
              ref={fileInput}
              type="file"
              accept="application/json,.json"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setFilename(file.name);
                setReport(null);
                setIncoming(await file.text());
              }}
            />

            {parsed && "fatal" in parsed && (
              <Banner tone="blocked" title={`${filename} was refused`}>
                <p style={{ margin: 0 }}>{parsed.why}</p>
              </Banner>
            )}

            {parsed && !("fatal" in parsed) && (
              <>
                <Banner tone="note" title={`${filename} — ${parsed.total} rows ready`}>
                  <p style={{ margin: 0 }}>
                    Exported {parsed.bundle.exported_at.slice(0, 10)} from this
                    organisation. Rows are sent in dependency order, so a
                    programme exists before the rate card that names it.
                  </p>
                </Banner>
                <DataTable
                  columns={["Entity", "Rows"]}
                  rows={parsed.plan.map((p) => [
                    <span key="k" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>{p.key}</span>,
                    <span key="n" className={s.mono}>{p.rows.length}</span>,
                  ])}
                />
                <p className={s.muted} style={{ fontSize: "var(--text-sm)", maxInlineSize: "var(--measure)" }}>
                  Every row is attempted and nothing is retried (D21, D17). Rows
                  the server refuses are listed with its own words; the rest are
                  applied.
                </p>
                <Button variant="primary" disabled={running} onClick={runImport}>
                  {running ? "Restoring…" : `Restore ${parsed.total} rows`}
                </Button>
              </>
            )}

            {report && (
              <Banner
                tone={report.refused > 0 ? "warn" : "note"}
                title={`${report.applied} restored · ${report.refused} refused`}
              >
                <DataTable
                  columns={["", "Entity", "Row", "What the server said"]}
                  rows={report.outcomes.map((o) => [
                    <span key="s" className={s.mono}>{o.status === "applied" ? "ok" : "no"}</span>,
                    <span key="k" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>{o.key}</span>,
                    <span key="l" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>{o.label}</span>,
                    o.message,
                  ])}
                  empty="The bundle held no rows."
                />
              </Banner>
            )}
          </Panel>
        </>
      )}
    </Shell>
  );
}
