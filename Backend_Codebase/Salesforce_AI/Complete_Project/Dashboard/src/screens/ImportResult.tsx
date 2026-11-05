/**
 * What the apply actually did — Task 22 Steps 2–3.
 *
 * One row per line of the file, in file order, with the server's own words on
 * every refusal. Two things this screen is careful about:
 *
 *  - **It never says "failed" and stops.** Every row was attempted (D21), so
 *    the table is a complete account of the file rather than a report that
 *    trails off at the first problem. The summary says so in as many words,
 *    because "3 refused" out of a 50-row file is otherwise ambiguous about
 *    whether rows 13–50 were even tried.
 *  - **The failures file is offered immediately**, in the format that went in,
 *    with the fix-and-re-import loop stated. That is the difference between a
 *    list of errors and a way out of them.
 */
import { useMemo } from "react";

import type { ApplyReport, RowOutcome } from "../import/apply";
import { failuresFile } from "../import/failures";
import type { Format } from "../import/parse";
import type { Descriptor } from "../descriptors/types";
import { Banner, Button, DataTable, Panel, StatusMarker, styles as s } from "../ui/primitives";

export function ImportResult({
  descriptor,
  format,
  columns,
  report,
  running,
  total,
  onStartOver,
}: {
  descriptor: Descriptor;
  format: Format;
  columns: readonly string[];
  report: ApplyReport;
  /** True while rows are still going out — the table fills in as they land. */
  running: boolean;
  total: number;
  onStartOver: () => void;
}) {
  const failures = useMemo(
    () => failuresFile({ descriptor, format, columns, outcomes: report.outcomes }),
    [descriptor, format, columns, report.outcomes],
  );

  const done = report.outcomes.length;

  return (
    <>
      <Panel
        eyebrow={running ? "Applying" : "Applied"}
        title={
          running
            ? `Sending row ${done} of ${total}…`
            : `${report.applied} applied · ${report.refused} refused`
        }
      >
        {running ? (
          <p style={{ margin: 0 }}>
            Rows are sent one at a time. A refusal does not stop the run — every
            row is attempted, so this is a complete account of the file by the
            time it finishes.
          </p>
        ) : (
          <p style={{ margin: 0 }}>
            <strong>Every one of the {total} rows was attempted.</strong>{" "}
            {report.refused === 0
              ? "None was refused."
              : `${report.refused} came back refused, and the server's own message for each is below. Nothing was retried — this backend has no idempotency, so a retry would create a duplicate rather than fix anything.`}
          </p>
        )}
      </Panel>

      {failures && !running && (
        <Panel eyebrow="Next" title="Fix the failures and drop the same file back in">
          <Banner tone="warn" title={`${failures.rows} row${failures.rows === 1 ? "" : "s"} to fix`}>
            <p style={{ margin: "0 0 var(--s3)" }}>
              This is your file, in the format you sent it, with the rows that
              failed and one extra column — <code>_error</code> — carrying the
              server's message. Columns beginning with <code>_</code> are ignored
              on import, so fix the rows in place and re-import this exact file.
              Nothing about the header needs editing.
            </p>
            <div style={{ display: "flex", gap: "var(--s3)", flexWrap: "wrap" }}>
              <a
                className={s.mono}
                style={{ fontSize: "var(--text-sm)", alignSelf: "center" }}
                download={failures.filename}
                href={URL.createObjectURL(new Blob([failures.text], { type: "text/plain" }))}
              >
                {failures.filename}
              </a>
              <Button onClick={() => navigator.clipboard?.writeText(failures.text)}>
                Copy it
              </Button>
            </div>
          </Banner>

          <pre
            className={s.mono}
            style={{
              margin: "var(--s4) 0 0",
              padding: "var(--s3)",
              background: "var(--paper-sunken)",
              border: "1px solid var(--rule)",
              borderRadius: "var(--radius)",
              overflowX: "auto",
              fontSize: "var(--text-xs)",
              whiteSpace: "pre",
            }}
          >
            {failures.text}
          </pre>
        </Panel>
      )}

      <Panel
        eyebrow="Every row"
        title="What the server said"
        actions={
          !running && (
            <Button onClick={onStartOver}>Import another file</Button>
          )
        }
      >
        <DataTable
          columns={["", "Row", "Outcome"]}
          empty="Nothing sent yet."
          rows={report.outcomes.map((outcome: RowOutcome) => [
            <StatusMarker
              key="m"
              status={outcome.status === "applied" ? "done" : "blocked"}
              label={outcome.status === "applied" ? "applied" : "refused"}
            />,
            <span key="l" className={s.mono}>
              {outcome.line}
            </span>,
            outcome.status === "applied" ? (
              <span key="o" className={s.muted}>
                {outcome.message}
              </span>
            ) : (
              // Verbatim. The backend's message already says what to do.
              <span key="o" className={s.serverMessage}>
                {outcome.message}
              </span>
            ),
          ])}
        />
      </Panel>
    </>
  );
}
