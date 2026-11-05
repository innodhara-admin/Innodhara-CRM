/**
 * Item 2 — staff accounts, with the right role.
 *
 * ## The temporary password (P8)
 *
 * `POST /admin/users` returns `{...UserResponse, temp_password}` and sets
 * `must_change_password=True`, **which nothing in the backend enforces**. The
 * design's §4.2 hand-off is about the *org admin's* password and never mentions
 * this one, so an implementer following the design alone would drop a
 * credential on the floor for every staff member created.
 *
 * It is shown once, with a copy control — and the screen states the asymmetry
 * with the org admin's password out loud, because the two look identical and
 * behave oppositely. A staff password is **recoverable**:
 * `POST /admin/users/{id}/reset-password` issues a fresh one and affects
 * nothing else. The org admin's is not, which is the entire reason D18 has a
 * modal and this screen does not.
 *
 * ## The domain rule
 *
 * `admin.py · register_staff` refuses any address not ending `@<org domain>`,
 * and `/auth/me` does not carry `email_domain` (P7) — only `POST /orgs` ever
 * returned it, and only to the tab that created the organisation. So the
 * caption states the rule with the domain when this session happens to know it
 * and without it otherwise, rather than guessing one from the admin's own
 * address: a second admin invited from another domain would make that guess
 * wrong in the one place it matters.
 */
import { useState } from "react";

import { endpoints } from "../api/endpoints";
import { request } from "../api/client";
import { schemas } from "../api/generated";
import { DESCRIPTORS } from "../descriptors";
import { session, useSession } from "../session/store";
import { EntityForm } from "../ui/EntityForm";
import {
  FormatFor,
  ItemHeading,
  ReadError,
  Section,
  asApiError,
  useList,
  useWrite,
} from "../ui/ItemScreen";
import {
  Banner,
  Button,
  DataTable,
  StatusMarker,
  styles as s,
} from "../ui/primitives";
import type { ItemStatus } from "../checklist/status";
import { StaffDetail } from "./StaffDetail";

const StaffRead = schemas.UserResponse.array();
const descriptor = DESCRIPTORS.staff;

type Created = { id: string; name: string; email: string; temp_password: string };

/**
 * A password the operator has one chance to keep. Selecting it by hand out of
 * a mono span is how it gets truncated, so there is a copy control — and a
 * plain statement of what to do when it is lost anyway.
 */
function TempPassword({ created, onDismiss }: { created: Created; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Banner tone="warn" title={`Temporary password for ${created.name}`}>
      <p style={{ margin: "0 0 var(--s3)" }}>
        Shown once. {created.email} must change it at first sign-in — although
        nothing in the backend enforces that, so the sign-in screen does.
      </p>
      <p
        className={s.mono}
        style={{
          margin: "0 0 var(--s3)",
          fontSize: "var(--text-lg)",
          userSelect: "all",
          wordBreak: "break-all",
        }}
      >
        {created.temp_password}
      </p>
      <div style={{ display: "flex", gap: "var(--s3)", flexWrap: "wrap" }}>
        <Button
          onClick={() => {
            navigator.clipboard?.writeText(created.temp_password).then(
              () => setCopied(true),
              // Clipboard access can be refused. Saying so beats a button that
              // silently did nothing while the operator moves on.
              () => setCopied(false),
            );
          }}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button variant="quiet" onClick={onDismiss}>
          I have it
        </Button>
      </div>
      <p style={{ margin: "var(--s3) 0 0", fontSize: "var(--text-sm)" }}>
        <strong>If it is lost, issue a new one from this person's row.</strong>{" "}
        Nothing else is affected. This is the opposite of the organisation
        administrator's temporary password, which is recoverable from nowhere —
        that is why creating an organisation has a modal and this does not.
      </p>
    </Banner>
  );
}

export function Staff({ status }: { status: ItemStatus }) {
  const { org } = useSession();
  const staff = useList("staff", endpoints.staff, StaffRead);
  const [created, setCreated] = useState<Created | null>(null);
  const [resetFor, setResetFor] = useState<Created | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  const create = useWrite<Record<string, unknown>>(["staff", "skills"], async (body) => {
    const reply = (await request(endpoints.staff, {
      as: "org",
      method: "POST",
      body,
    })) as Created;
    setCreated(reply);
    return reply;
  });

  const resetPassword = useWrite<{ id: string; name: string; email: string }>(
    ["staff"],
    async (user) => {
      const reply = (await request(endpoints.staffResetPassword(user.id), {
        as: "org",
        method: "POST",
      })) as { temp_password: string };
      setResetFor({ ...user, temp_password: reply.temp_password });
      return reply;
    },
  );

  const setActive = useWrite<{ id: string; active: boolean }>(["staff"], ({ id, active }) =>
    request(endpoints.staffMember(id), {
      as: "org",
      method: "PATCH",
      body: { is_active: active },
    }),
  );

  const domainRule = org?.emailDomain
    ? `must end @${org.emailDomain} — this organisation's own domain`
    : "must end with this organisation's own domain · /auth/me does not carry it, so it cannot be shown here (P7)";

  return (
    <>
      <ItemHeading item={2} marker={status.marker} caption={status.caption} />

      {created && <TempPassword created={created} onDismiss={() => setCreated(null)} />}
      {resetFor && <TempPassword created={resetFor} onDismiss={() => setResetFor(null)} />}

      {openId && <StaffDetail userId={openId} onClose={() => setOpenId(null)} />}

      <Section title="Add somebody" eyebrow="Create">
        <EntityForm
          descriptor={descriptor}
          submitLabel="Create account"
          busy={create.isPending}
          serverError={asApiError(create.error)}
          resetSignal={create.submittedAt}
          onSubmit={(body) => create.mutate(body as Record<string, unknown>)}
        >
          <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s2) 0 0" }}>
            <strong>Email: </strong>
            {domainRule}
          </p>
        </EntityForm>
      </Section>

      <Section title="Who is here" eyebrow="Current">
        {staff.isError ? (
          <ReadError error={staff.error} what="the staff list" />
        ) : (
          <DataTable
            columns={["", "Name", "Email", "Role", "Department", ""]}
            empty="Nobody yet — the administrator is the only account."
            rows={(staff.data ?? []).map((u) => [
              <StatusMarker
                key="m"
                status={u.department ? "done" : "partial"}
                label={u.department ? "has a department" : "no department"}
              />,
              <span key="n">
                {u.name}
                {!u.is_active && <span className={s.muted}> · deactivated</span>}
              </span>,
              <span key="e" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
                {u.email}
              </span>,
              u.role,
              u.department ?? (
                <span key="d" className={s.muted}>
                  not recorded
                </span>
              ),
              <span key="a" style={{ display: "flex", gap: "var(--s2)" }}>
                <Button onClick={() => setOpenId(u.id)}>Open</Button>
                <Button
                  onClick={() =>
                    resetPassword.mutate({ id: u.id, name: u.name, email: u.email })
                  }
                  disabled={resetPassword.isPending}
                >
                  New password
                </Button>
                <Button
                  variant="quiet"
                  onClick={() => setActive.mutate({ id: u.id, active: !u.is_active })}
                  disabled={setActive.isPending || u.id === session.get().org?.userId}
                >
                  {u.is_active ? "Deactivate" : "Reactivate"}
                </Button>
              </span>,
            ])}
          />
        )}
        <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)" }}>
          There is no staff delete, deliberately: <code>users</code> is in the
          reset taxonomy&rsquo;s KEEP bucket under every flag (D16), so an
          account can be deactivated but never destroyed. Deactivating also
          removes that person&rsquo;s skills from coverage —{" "}
          <code>ops.py · delete_skill</code> counts active holders only, and
          item 3 above agrees with it.
        </p>
        {(setActive.error || resetPassword.error) && (
          <div style={{ marginBlockStart: "var(--s3)" }}>
            <Banner
              tone="blocked"
              title="The server refused that"
              serverMessage={
                asApiError(setActive.error)?.detail ??
                asApiError(resetPassword.error)?.detail ??
                ""
              }
            />
          </div>
        )}
      </Section>

      <FormatFor descriptor={descriptor} />
    </>
  );
}
