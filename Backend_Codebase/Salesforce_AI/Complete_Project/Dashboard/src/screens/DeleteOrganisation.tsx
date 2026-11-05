/**
 * Delete this organisation: the last section of the Reset screen (28 Oct 2026).
 *
 * Spec: docs/superpowers/specs/2026-10-28-org-delete-design.md, section 5.5.
 * Unlike a reset, this removes the organisation itself: its people and their
 * sign-ins, every record, every file. The preview is the server's own dry run;
 * the button stays disabled until the typed text matches `DELETE <name>` and a
 * password is typed. The server checks both again and refuses with "Nothing
 * was deleted" when either is wrong.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { isApiError } from "../api/errors";
import { OrgDeletePreviewRead, OrgDeleteResultRead } from "../api/reads";
import {
  confirmationMatches,
  deletedMessage,
  expectedConfirmation,
  type DeletedMessage,
} from "../bundle/orgDelete";
import { session } from "../session/store";
import { Banner, Button, Field, Panel, TextInput, styles as s } from "../ui/primitives";

function megabytes(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** The server checked and said no before touching anything (403, 422). */
function refused(error: unknown): boolean {
  return isApiError(error) && (error.status === 403 || error.status === 422);
}

export function DeleteOrganisation({
  orgName,
  onDeleted,
}: {
  orgName: string;
  onDeleted: (message: DeletedMessage) => void;
}) {
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState("");
  const [password, setPassword] = useState("");

  const preview = useQuery({
    queryKey: ["org-delete", "preview"],
    queryFn: () =>
      request(endpoints.deleteOrganisation, {
        as: "org",
        method: "POST",
        body: { dry_run: true },
        shape: OrgDeletePreviewRead,
      }),
  });

  const remove = useMutation({
    mutationFn: () =>
      request(endpoints.deleteOrganisation, {
        as: "org",
        method: "POST",
        body: { dry_run: false, confirm_text: typed, password },
        shape: OrgDeleteResultRead,
      }),
    onSuccess: (result) => {
      setPassword("");
      queryClient.clear();
      session.setOrg(null);
      onDeleted(deletedMessage(orgName, result));
    },
  });

  const ready = confirmationMatches(typed, orgName) && password.length > 0;
  const found = preview.data;

  return (
    <Panel eyebrow="Danger" title={`Delete ${orgName}`}>
      <p style={{ maxInlineSize: "var(--measure)" }}>
        Everything this organisation holds is deleted for good: its people and
        their sign-ins, clients, meetings, proposals, templates, settings,
        history and files. Other organisations are not touched. A full backup
        is kept on the server for 7 days, then removed.
      </p>

      {preview.isPending && <p className={s.muted}>Counting what would be deleted…</p>}

      {preview.isError && (
        <Banner
          tone="blocked"
          title="This console could not read what would be deleted"
          serverMessage={isApiError(preview.error) ? preview.error.detail : String(preview.error)}
        >
          <p style={{ margin: 0 }}>Do not delete without seeing it.</p>
        </Banner>
      )}

      {found && (
        <>
          <p style={{ maxInlineSize: "var(--measure)" }}>
            {`This removes ${plural(found.total, "record")} and ${plural(found.files, "file")} (${megabytes(found.bytes)}), and ends the sign-in of these people:`}
          </p>
          <ul>
            {found.users.map((u) => (
              <li key={u.email}>
                <span className={s.mono}>{u.email}</span> ({u.role})
              </li>
            ))}
          </ul>
          {found.outside_files.length > 0 && (
            <Banner tone="warn" title="Files outside this organisation's folder">
              <p style={{ marginBlockStart: 0 }}>
                Its settings name these files. They are kept, because another
                organisation may use them. Remove them by hand if they are only
                this organisation's.
              </p>
              <ul>
                {found.outside_files.map((f) => (
                  <li key={f} className={s.mono}>{f}</li>
                ))}
              </ul>
            </Banner>
          )}
          {Object.keys(found.other_org_mentions).length > 0 && (
            <Banner tone="warn" title="Other organisations mention this one">
              <p style={{ margin: 0 }}>
                {`${plural(Object.values(found.other_org_mentions).reduce((a, b) => a + b, 0), "record")} of other organisations mention it. They are not changed.`}
              </p>
            </Banner>
          )}
        </>
      )}

      <Field label={`Type ${expectedConfirmation(orgName)} to confirm`} htmlFor="delete-org-confirm">
        <TextInput
          id="delete-org-confirm"
          mono
          autoComplete="off"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={expectedConfirmation(orgName)}
        />
      </Field>
      <Field label="Your password" htmlFor="delete-org-password">
        <TextInput
          id="delete-org-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>

      <Button
        variant="danger"
        disabled={!ready || !found || remove.isPending}
        onClick={() => remove.mutate()}
      >
        {remove.isPending ? "Deleting…" : "Delete this organisation for good"}
      </Button>

      {remove.isError && (
        <Banner
          tone="blocked"
          title={refused(remove.error) ? "The server refused the delete" : "The delete did not finish"}
          serverMessage={isApiError(remove.error) ? remove.error.detail : String(remove.error)}
        >
          <p style={{ margin: 0 }}>
            {refused(remove.error)
              ? "Nothing was deleted."
              : "Part of it may already be gone. Do not try again from here: ask the developer to check the server and finish it with the delete script."}
          </p>
        </Banner>
      )}
    </Panel>
  );
}
