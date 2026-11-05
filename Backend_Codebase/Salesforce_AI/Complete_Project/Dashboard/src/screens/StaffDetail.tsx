/**
 * One staff member — `GET /admin/users/{user_id}` (change #4) and `PATCH`.
 *
 * The read exists because of this screen: before change #4 a staff-detail view
 * could only be assembled from `list_staff`, which returns six of the eleven
 * fields the app consumes. That was change #1 in `09_BACKEND_CHANGES.md`, and
 * this is the thing it was for.
 *
 * **`UpdateUserRequest` is `.partial().passthrough()` (P9), and `update_staff`
 * applies each field only `if body.<field> is not None`.** Two consequences the
 * form has to respect:
 *
 *  - **Send only what changed.** An unchanged field left out is untouched;
 *    including it is harmless but makes the audit row claim an edit that did
 *    not happen.
 *  - **There is no way to clear a field back to null.** `None` means "leave
 *    alone", so blanking Designation and saving does nothing at all. The screen
 *    says so rather than offering a control that silently fails — the same rule
 *    §5.4 applies to `PATCH /admin/settings`.
 */
import { useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { schemas } from "../api/generated";
import { DESCRIPTORS } from "../descriptors";
import { EntityForm } from "../ui/EntityForm";
import { asApiError, useWrite } from "../ui/ItemScreen";
import { isBlank } from "../ui/entityValidation";
import { Banner, Button, Panel, styles as s } from "../ui/primitives";
import { useQuery } from "@tanstack/react-query";

const descriptor = DESCRIPTORS.staff;
const UserRead = schemas.UserResponse;

/** Only the fields that actually differ, so the PATCH says what it means. */
export function changedFields(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
  fields: readonly string[],
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  for (const field of fields) {
    const next = after[field];
    // Blank means "not supplied" and PATCH reads it as "leave alone", so a
    // cleared box is never sent — it would be a no-op the operator misreads
    // as a deletion.
    if (isBlank(next)) continue;
    if (JSON.stringify(next) === JSON.stringify(before[field] ?? "")) continue;
    patch[field] = next;
  }
  return patch;
}

export function StaffDetail({ userId, onClose }: { userId: string; onClose: () => void }) {
  const [saved, setSaved] = useState<string[] | null>(null);

  const member = useQuery({
    queryKey: ["staff", userId],
    queryFn: () => request(endpoints.staffMember(userId), { as: "org", shape: UserRead }),
  });

  const save = useWrite<Record<string, unknown>>(["staff"], async (patch) => {
    const reply = await request(endpoints.staffMember(userId), {
      as: "org",
      method: "PATCH",
      body: patch,
    });
    setSaved(Object.keys(patch));
    return reply;
  });

  if (member.isError) {
    return (
      <Panel eyebrow="Staff member" title="Could not be read">
        <Banner
          tone="blocked"
          title="GET /admin/users/{id} failed"
          serverMessage={asApiError(member.error)?.detail ?? String(member.error)}
        />
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Button onClick={onClose}>Back to the list</Button>
        </div>
      </Panel>
    );
  }

  if (!member.data) {
    return (
      <Panel eyebrow="Staff member" title="Reading…">
        <p className={s.muted} style={{ margin: 0 }}>
          Waiting for GET /admin/users/{userId}.
        </p>
      </Panel>
    );
  }

  const current = member.data as unknown as Record<string, unknown>;
  // `email` is not on UpdateUserRequest at all — an address is the identity and
  // decides the organisation, so it cannot be edited here.
  const editable = descriptor.fields
    .map((f) => f.field)
    .filter((f) => f !== "email");

  return (
    <Panel
      eyebrow="Staff member"
      title={member.data.name}
      actions={<Button onClick={onClose}>Back to the list</Button>}
    >
      <p className={s.mono} style={{ fontSize: "var(--text-xs)", marginBlockStart: 0 }}>
        {member.data.email} · {member.data.role}
        {member.data.is_active ? "" : " · deactivated"}
      </p>

      {saved && (
        <div style={{ marginBlockEnd: "var(--s4)" }}>
          <Banner tone="note" title="Saved">
            <p style={{ margin: 0 }}>
              {saved.length === 0
                ? "Nothing had changed, so nothing was sent."
                : `Sent: ${saved.join(", ")}. Fields left blank were not sent — PATCH reads an absent field as "leave alone".`}
            </p>
          </Banner>
        </div>
      )}

      <EntityForm
        descriptor={descriptor}
        only={editable}
        initial={current}
        submitLabel="Save changes"
        busy={save.isPending}
        serverError={asApiError(save.error)}
        onSubmit={(values) => {
          const patch = changedFields(current, values, editable);
          setSaved(Object.keys(patch));
          if (Object.keys(patch).length > 0) save.mutate(patch);
        }}
      >
        <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)" }}>
          <strong>A field cannot be cleared here.</strong>{" "}
          <code>update_staff</code> applies each value only when it is not{" "}
          <code>None</code>, so blanking a box and saving leaves the stored value
          exactly as it was. There is no route that writes null, and a "clear"
          control that silently did nothing would be worse than its absence.
        </p>
      </EntityForm>
    </Panel>
  );
}
