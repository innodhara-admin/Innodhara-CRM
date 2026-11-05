/**
 * Import — choose entity, drop file, parse, validate, preview (§5.5).
 *
 * Task 22 adds the apply half: the button sends, the result screen reports every
 * row, and the failures file comes back in the format that went in.
 *
 * ## What the preview is for
 *
 * The backend has **no bulk transaction**. Rows are applied by sequential HTTP
 * calls with no retries (D17), so a file that is half right leaves a catalogue
 * that is half written. The preview is the only place that can be caught
 * cheaply, which is why apply is gated on **zero** validation errors rather
 * than on most of them.
 *
 * It cannot catch everything, and says so: a duplicate email, a programme code
 * already taken, a user id that does not exist — none of those are visible from
 * here. §5.5 treats partial application as ordinary rather than exceptional,
 * and Task 22's failures file is the answer to it.
 *
 * ## Re-import behaviour is per entity, and the loud one is versioning
 *
 * Four entities respond to the same file being imported twice by **creating a
 * new version and superseding the current one**. Nothing refuses it and nothing
 * reports it, so a careless re-import silently inflates version numbers. That
 * warning is rendered before the operator ever reaches the apply button.
 */
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { ProgramsRead, ProposalTemplatesRead } from "../api/reads";
import { useList } from "../ui/ItemScreen";
import { ALL_DESCRIPTORS, DESCRIPTORS } from "../descriptors";
import type { Descriptor, EntityKey } from "../descriptors/types";
import { FormatPanel } from "../ui/FormatPanel";
import {
  Banner,
  Button,
  DataTable,
  Field,
  Panel,
  Select,
  StatusMarker,
  TextArea,
  styles as s,
} from "../ui/primitives";
import { applyFile, writeTargetFor, type ApplyReport, type RowOutcome } from "../import/apply";
import { detectFormat, formatsFor, parseFile, type Format } from "../import/parse";
import { csvIsAwkward, filenameFor, templateFor } from "../import/template";
import { validateFile, type FileVerdict } from "../import/validate";
import { ImportResult } from "./ImportResult";

/**
 * §5.5's table, keyed by entity. Not derived from `descriptor.reimport`, which
 * is one sentence per entity — this is the tone, and the tone is the point:
 * three of these are warnings and the rest are facts.
 */
const REIMPORT_TONE: Record<EntityKey, "note" | "warn"> = {
  skills: "note",
  staff: "note",
  programs: "note",
  demoTeams: "note",
  pricing: "warn",
  proposalTemplates: "warn",
  messageTemplates: "warn",
  playbooks: "warn",
  approvalRules: "warn",
  vendors: "warn",
  settings: "note",
};

function Verdicts({ verdict }: { verdict: FileVerdict }) {
  // A CSV's unknown-column error repeats on every row. Showing it fifty times
  // buries the fifty different errors underneath it.
  const repeated = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of verdict.rows) {
      for (const message of Object.values(row.errors)) {
        counts.set(message, (counts.get(message) ?? 0) + 1);
      }
    }
    return new Set(
      [...counts.entries()]
        .filter(([, n]) => n === verdict.rows.length && verdict.rows.length > 1)
        .map(([message]) => message),
    );
  }, [verdict]);

  return (
    <>
      {repeated.size > 0 && (
        <div style={{ marginBlockEnd: "var(--s4)" }}>
          <Banner tone="blocked" title="Every row has the same problem">
            <ul style={{ margin: 0, paddingInlineStart: "1.1rem" }}>
              {[...repeated].map((message) => (
                <li key={message} style={{ fontSize: "var(--text-sm)" }}>
                  {message}
                </li>
              ))}
            </ul>
            <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-sm)" }}>
              Almost always the header line. Fix it once and re-check.
            </p>
          </Banner>
        </div>
      )}

      <DataTable
        columns={["", "Row", "What would be sent", "Problem"]}
        empty="No rows in this file."
        rows={verdict.rows.map((row) => [
          <StatusMarker
            key="m"
            status={row.ok ? "done" : "blocked"}
            label={row.ok ? "ready" : "will not be sent"}
          />,
          <span key="l" className={s.mono}>
            {row.line}
          </span>,
          <span key="b" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
            {Object.keys(row.body).length === 0
              ? "nothing"
              : Object.entries(row.body)
                  .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                  .join(" · ")}
          </span>,
          row.ok ? (
            <span key="e" className={s.muted}>
              —
            </span>
          ) : (
            <ul key="e" style={{ margin: 0, paddingInlineStart: "1.1rem" }}>
              {Object.entries(row.errors)
                .filter(([, message]) => !repeated.has(message))
                .map(([field, message]) => (
                  <li key={field} style={{ fontSize: "var(--text-xs)" }}>
                    <span className={s.mono}>{field}</span>
                    {` — ${message}`}
                  </li>
                ))}
              {Object.values(row.errors).every((m) => repeated.has(m)) && (
                <li className={s.muted} style={{ fontSize: "var(--text-xs)" }}>
                  the file-wide problem above
                </li>
              )}
            </ul>
          ),
        ])}
      />
    </>
  );
}

function TemplateBlock({ descriptor, format }: { descriptor: Descriptor; format: Format }) {
  const text = templateFor(descriptor, format);
  const [copied, setCopied] = useState(false);

  return (
    <>
      <pre
        className={s.mono}
        style={{
          margin: "0 0 var(--s3)",
          padding: "var(--s3)",
          background: "var(--paper-sunken)",
          border: "1px solid var(--rule)",
          borderRadius: "var(--radius)",
          overflowX: "auto",
          fontSize: "var(--text-xs)",
          whiteSpace: "pre",
        }}
      >
        {text}
      </pre>
      <div style={{ display: "flex", gap: "var(--s3)", flexWrap: "wrap" }}>
        <Button
          onClick={() => {
            navigator.clipboard?.writeText(text).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
        >
          {copied ? "Copied" : "Copy the template"}
        </Button>
        <a
          className={s.mono}
          style={{ fontSize: "var(--text-sm)", alignSelf: "center" }}
          download={filenameFor(descriptor, format)}
          href={URL.createObjectURL(new Blob([text], { type: "text/plain" }))}
        >
          {filenameFor(descriptor, format)}
        </a>
      </div>
    </>
  );
}

export function Import() {
  const [key, setKey] = useState<EntityKey>("staff");
  const descriptor = DESCRIPTORS[key];
  const formats = formatsFor(descriptor);
  const [format, setFormat] = useState<Format>("csv");
  const [text, setText] = useState("");
  const [filename, setFilename] = useState<string | null>(null);
  const [programId, setProgramId] = useState("");
  const [report, setReport] = useState<ApplyReport | null>(null);
  const [running, setRunning] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const programs = useList("programs", endpoints.programs, ProgramsRead);
  const activePrograms = (programs.data ?? []).filter((p) => p.is_active);

  // The chosen entity may not accept the chosen format — switching to settings
  // while on CSV, for instance. The descriptor decides, not this component.
  const effective: Format = formats.includes(format) ? format : formats[0];

  const parsed = useMemo(
    () => (text.trim() === "" ? null : parseFile(descriptor, text, effective)),
    [descriptor, text, effective],
  );
  // A proposal-template import that would supersede a Word-document template
  // replaces a branded document with a plain text one, silently, on the way to
  // a client. `validate.ts` makes that a refusal rather than a warning; this is
  // where the console works out that it applies.
  const currentTemplates = useQuery({
    queryKey: ["proposalTemplates", programId],
    enabled: descriptor.key === "proposalTemplates" && Boolean(programId),
    queryFn: () =>
      request(endpoints.proposalTemplates(programId), {
        as: "org",
        shape: ProposalTemplatesRead,
      }),
  });
  const supersedesDocxTemplate = (currentTemplates.data ?? []).some(
    (t) => t.is_current && t.kind === "docx",
  );

  const verdict = useMemo(
    () =>
      parsed && !parsed.fatal
        ? validateFile(descriptor, parsed.rows, effective, { supersedesDocxTemplate })
        : null,
    [descriptor, parsed, effective, supersedesDocxTemplate],
  );

  const target = writeTargetFor(descriptor, { programId: programId || undefined });
  const needsProgram = "error" in target;

  function startOver() {
    setReport(null);
    setApplyError(null);
  }

  async function apply() {
    if (!verdict) return;
    setRunning(true);
    setApplyError(null);
    // Rendered as it goes: a 50-row file takes 50 round trips, and a screen
    // that sat still for all of them would look hung at exactly the moment the
    // operator most wants to know what is happening.
    const live: RowOutcome[] = [];
    setReport({ outcomes: [], applied: 0, refused: 0 });
    try {
      const finished = await applyFile({
        descriptor,
        verdict,
        context: { programId: programId || undefined },
        onProgress: (outcome) => {
          live.push(outcome);
          setReport({
            outcomes: [...live],
            applied: live.filter((o) => o.status === "applied").length,
            refused: live.filter((o) => o.status === "refused").length,
          });
        },
      });
      setReport(finished);
      // Everything the rail derives a status from may have moved.
      await queryClient.invalidateQueries();
    } catch (cause) {
      setApplyError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setRunning(false);
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    const detected = detectFormat(file.name);
    startOver();
    setFilename(file.name);
    setFormat(formats.includes(detected) ? detected : formats[0]);
    setText(await file.text());
  }

  return (
    <>
      <Panel eyebrow="Import" title="Load a file into this organisation">
        <p style={{ margin: 0, maxInlineSize: "var(--measure)" }}>
          Choose what you are importing, drop the file in, and read the verdict
          on every row before anything is sent. Nothing below writes to the
          server.
        </p>
      </Panel>

      <Panel eyebrow="Step 1" title="What are you importing?">
        <Field label="Entity" htmlFor="import-entity">
          <Select
            id="import-entity"
            options={ALL_DESCRIPTORS.map((d) => ({
              value: d.key,
              label: `Item ${d.item} · ${d.title}`,
            }))}
            value={key}
            onChange={(e) => {
              setKey(e.target.value as EntityKey);
              setText("");
              setFilename(null);
              startOver();
            }}
          />
        </Field>

        <Field
          label="Format"
          htmlFor="import-format"
          enforcement={{
            kind: "ui-only",
            why: "which formats an entity accepts comes from its descriptor — the server takes JSON either way",
          }}
          caption={
            formats.length === 1
              ? `${descriptor.title} is JSON only`
              : "CSV or JSON · the file's extension picks this for you"
          }
        >
          <Select
            id="import-format"
            options={formats}
            value={effective}
            onChange={(e) => setFormat(e.target.value as Format)}
          />
        </Field>

        {formats.length === 1 && (
          <Banner tone="note" title="This one has no CSV form">
            <p style={{ margin: 0 }}>
              {key === "settings"
                ? "Settings is one row, not a list, so a CSV of it would be a header and a single line — JSON says the same thing without the ceremony."
                : "Its fields carry nested JSON, which a CSV cell cannot express without quoting rules nobody should have to think about."}
            </p>
          </Banner>
        )}

        {effective === "csv" && csvIsAwkward(descriptor) && (
          <Banner tone="warn" title="JSON is the easier road for this one">
            <p style={{ margin: 0 }}>
              This entity's text runs to several lines, and a line break survives
              CSV only inside double quotes. The template below is quoted
              correctly — if you build the file another way and it comes back
              with errors on columns you did not touch, an unquoted line break is
              the usual reason.
            </p>
          </Banner>
        )}
      </Panel>

      <Panel eyebrow="Step 2" title="The file">
        <Field label="Choose a file" htmlFor="import-file">
          <input
            id="import-file"
            type="file"
            accept={effective === "csv" ? ".csv,text/csv" : ".json,application/json"}
            onChange={(e) => onFile(e.target.files?.[0])}
          />
        </Field>

        <Field
          label="Or paste it"
          htmlFor="import-text"
          caption="the same parser reads either"
        >
          <TextArea
            id="import-text"
            mono
            rows={8}
            spellCheck={false}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setFilename(null);
              startOver();
            }}
          />
        </Field>

        {filename && (
          <p className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
            {filename}
          </p>
        )}
      </Panel>

      {parsed?.fatal && (
        <Panel eyebrow="Step 3" title="This file could not be read">
          <Banner tone="blocked" title="Nothing was parsed" serverMessage={parsed.fatal}>
            <p style={{ margin: 0 }}>
              No rows came out of it, so there is nothing to check and nothing to
              send.
            </p>
          </Banner>
        </Panel>
      )}

      {parsed && !parsed.fatal && verdict && (
        <>
          {parsed.ignored.length > 0 && (
            <Panel eyebrow="Noticed" title="This looks like a failures file">
              <Banner tone="note" title={`Ignoring ${parsed.ignored.join(", ")}`}>
                <p style={{ margin: 0 }}>
                  Columns beginning with <code>_</code> are ignored, which is what
                  makes a failures file directly re-importable: fix the rows in
                  place and drop the same file back in. Nothing else about it
                  needs editing.
                </p>
              </Banner>
            </Panel>
          )}

          <Panel
            eyebrow="Step 3"
            title={`${verdict.rows.length} row${verdict.rows.length === 1 ? "" : "s"} · ${verdict.okCount} ready · ${verdict.errorCount} with problems`}
          >
            {verdict.shape === "file-is-one-call" && (
              <div style={{ marginBlockEnd: "var(--s4)" }}>
                <Banner tone="note" title="Every row here is one line of a single rate card">
                  <p style={{ margin: 0 }}>
                    A rate-card CSV is not one call per row: the whole file
                    becomes <strong>one new version</strong> with{" "}
                    {verdict.rows.length} line
                    {verdict.rows.length === 1 ? "" : "s"} on it. Which offering
                    it belongs to is chosen when it is applied, not carried in the
                    file.
                  </p>
                </Banner>
              </div>
            )}

            <Verdicts verdict={verdict} />
          </Panel>

          <Panel eyebrow="Step 4" title="What applying this would do">
            <Banner tone={REIMPORT_TONE[descriptor.key]} title="If this file has been imported before">
              <p style={{ margin: 0 }}>{descriptor.reimport}</p>
              {REIMPORT_TONE[descriptor.key] === "warn" &&
                ["pricing", "proposalTemplates", "messageTemplates", "playbooks"].includes(
                  descriptor.key,
                ) && (
                  <p style={{ margin: "var(--s2) 0 0" }}>
                    <strong>Nothing refuses this and nothing reports it.</strong>{" "}
                    Importing the same file three times leaves you at version 3
                    with two superseded copies, and the only way to notice is to
                    look at the version history.
                  </p>
                )}
            </Banner>

            <div style={{ marginBlockStart: "var(--s4)" }}>
              <Banner tone="note" title="What this preview cannot see">
                <p style={{ margin: 0 }}>
                  A duplicate email, a code already taken, a user id that does not
                  exist in this organisation — those live on the server and only
                  appear when a row is actually sent. The backend has no bulk
                  transaction and this console does not retry, so some rows
                  failing at that point is ordinary rather than exceptional.
                </p>
              </Banner>
            </div>

            {needsProgram && (
              <div style={{ marginBlockStart: "var(--s4)" }}>
                <Field
                  label="Which offering"
                  htmlFor="import-program"
                  enforcement={{
                    kind: "backend-undeclared",
                    source: "admin.py · " + (key === "pricing" ? "add_pricing" : "add_proposal_template"),
                  }}
                  caption="the offering is a path segment on this route, so the file cannot carry it"
                >
                  <Select
                    id="import-program"
                    placeholder="Choose an offering"
                    options={activePrograms.map((p) => ({
                      value: p.id,
                      label: `${p.code} — ${p.name}`,
                    }))}
                    value={programId}
                    onChange={(e) => setProgramId(e.target.value)}
                  />
                </Field>
              </div>
            )}

            {applyError && (
              <div style={{ marginBlockStart: "var(--s4)" }}>
                <Banner tone="blocked" title="Nothing was sent" serverMessage={applyError} />
              </div>
            )}

            <div
              style={{
                display: "flex",
                gap: "var(--s3)",
                alignItems: "center",
                flexWrap: "wrap",
                marginBlockStart: "var(--s5)",
              }}
            >
              <Button
                variant="primary"
                disabled={!verdict.canApply || needsProgram || running || Boolean(report)}
                onClick={apply}
              >
                {running
                  ? "Sending…"
                  : verdict.shape === "file-is-one-call"
                    ? "Publish this rate card"
                    : `Apply ${verdict.okCount} row${verdict.okCount === 1 ? "" : "s"}`}
              </Button>
              <p className={s.muted} style={{ margin: 0, fontSize: "var(--text-sm)" }}>
                {!verdict.canApply
                  ? `Apply is gated on zero problems, not on most of them — ${verdict.errorCount} row${verdict.errorCount === 1 ? "" : "s"} would have to be fixed first.`
                  : needsProgram
                    ? (target as { error: string }).error
                    : report
                      ? "This file has been sent. Choose another file to import again."
                      : "Every row will be attempted, one at a time. A refusal does not stop the run, and nothing is retried."}
              </p>
            </div>
          </Panel>
        </>
      )}

      {report && parsed && (
        <ImportResult
          descriptor={descriptor}
          format={effective}
          columns={parsed.columns}
          report={report}
          running={running}
          total={verdict?.rows.length ?? 0}
          onStartOver={() => {
            startOver();
            setText("");
            setFilename(null);
          }}
        />
      )}

      <Panel eyebrow="Template" title={`A ${effective.toUpperCase()} file this entity accepts`}>
        <p className={s.muted} style={{ marginBlockStart: 0, fontSize: "var(--text-sm)" }}>
          Header and one worked example, both from the same declaration the
          validator reads — so this file is one the console accepts, and a test
          asserts that on every run.
        </p>
        <TemplateBlock descriptor={descriptor} format={effective} />
      </Panel>

      <FormatPanel descriptor={descriptor} />
    </>
  );
}
