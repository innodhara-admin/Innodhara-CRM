/**
 * The version list for the four versioned families — 06_DESIGN.md §5.3.
 *
 * **Shown, never hidden.** Rate cards, proposal templates, message templates
 * and playbooks all create a new row and flip `is_current` rather than editing
 * in place, and a sent proposal locks `pricing_table_id` + `pricing_version`
 * and `template_id` + `template_version`. That locking is the whole reason
 * editing a rate card is safe, and it only reads as safe if the operator can
 * see that the old version is still there.
 *
 * ## Delete promotes the predecessor, and the API will not say which
 *
 * `admin.py`'s three catalogue deletes call `_promote_predecessor` when the row
 * they removed was current — and then return **`{"deleted": true}`** and
 * nothing else. So the console cannot report the promotion from the response;
 * it re-reads the list and states what is current now. `onDeleted` exists for
 * exactly that, and the screens pass a callback that names the new current
 * version rather than a generic "done".
 */
import type { ReactNode } from "react";

import { Button, DataTable, StatusMarker, styles as s } from "./primitives";

export type Version = {
  id: string;
  version: number;
  isCurrent: boolean;
  /** One line describing this version — lines, name, subject, whatever fits. */
  summary: ReactNode;
};

export function VersionHistory({
  versions,
  onDelete,
  busy,
  empty,
  deleteHint,
}: {
  versions: readonly Version[];
  onDelete?: (version: Version) => void;
  busy?: boolean;
  empty: string;
  /** What the operator should know before pressing Remove on this family. */
  deleteHint?: ReactNode;
}) {
  const ordered = [...versions].sort((a, b) => b.version - a.version);

  return (
    <>
      <DataTable
        columns={["", "Version", "", ""]}
        empty={empty}
        rows={ordered.map((v) => [
          <StatusMarker
            key="m"
            status={v.isCurrent ? "done" : "none"}
            label={v.isCurrent ? "current" : "superseded"}
          />,
          <span key="v" className={s.mono}>
            {`v${v.version}`}
            {v.isCurrent && <span className={s.muted}> · current</span>}
          </span>,
          v.summary,
          onDelete ? (
            <Button key="d" variant="danger" disabled={busy} onClick={() => onDelete(v)}>
              Remove
            </Button>
          ) : (
            <span key="d" />
          ),
        ])}
      />
      {deleteHint && (
        <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)" }}>
          {deleteHint}
        </p>
      )}
    </>
  );
}
