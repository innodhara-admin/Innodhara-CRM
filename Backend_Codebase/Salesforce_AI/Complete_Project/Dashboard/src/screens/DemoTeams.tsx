/**
 * Item 13 — demo teams.
 *
 * ## Show the names, edit against the ids
 *
 * `list_demo_teams` returns **both** halves since backend change #10: `lead` /
 * `media_rep` / `sales_rep` resolved to names, and `lead_user_id` /
 * `media_rep_id` / `sales_rep_id`. Before it, only the names came back, and
 * "edit" — which is delete-and-recreate here — silently lost all three role
 * assignments, because a name cannot be turned back into an id. `User.name` is
 * not unique, so inferring one would have been a coin toss on any organisation
 * with two people called the same thing.
 *
 * **Never infer an id from a name.** The ids are supplied now; use them.
 *
 * ## Editing is delete-and-recreate, and the name is UNIQUE
 *
 * There is no `PATCH`, and `name` is unique per organisation (compared
 * case-insensitively), so the delete must succeed before the recreate can even
 * be attempted. The delete is refused when a demo is booked against the team —
 * which is the common case on any organisation that has used the product — so
 * the honest thing to say is that a team in use cannot be edited at all.
 */
import { useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { DemoTeamsRead, type DemoTeams as Teams } from "../api/reads";
import { schemas } from "../api/generated";
import type { ItemStatus } from "../checklist/status";
import { DESCRIPTORS } from "../descriptors";
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
import { Banner, Button, DataTable, Select, styles as s } from "../ui/primitives";

const StaffRead = schemas.UserResponse.array();
const descriptor = DESCRIPTORS.demoTeams;

type Team = Teams[number];

export function DemoTeams({ status }: { status: ItemStatus }) {
  const staff = useList("staff", endpoints.staff, StaffRead);
  const teams = useList("demoTeams", endpoints.demoTeams, DemoTeamsRead);
  const [replacing, setReplacing] = useState<Team | null>(null);
  const [report, setReport] = useState<string | null>(null);

  const active = (staff.data ?? []).filter((u) => u.is_active);
  const people = active.map((u) => ({ value: u.id, label: `${u.name} · ${u.role}` }));

  const create = useWrite<Record<string, unknown>>(["demoTeams"], (body) =>
    request(endpoints.demoTeams, { as: "org", method: "POST", body }),
  );

  const remove = useWrite<string>(["demoTeams"], (id) =>
    request(endpoints.demoTeam(id), { as: "org", method: "DELETE" }),
  );

  /** Delete then create, in that order — the name is unique, so it must be. */
  const replace = useWrite<{ original: Team; body: Record<string, unknown> }>(
    ["demoTeams"],
    async ({ original, body }) => {
      setReport(null);
      await request(endpoints.demoTeam(original.id), { as: "org", method: "DELETE" });
      try {
        const reply = await request(endpoints.demoTeams, {
          as: "org",
          method: "POST",
          body,
        });
        setReport(
          `Replaced “${original.name}”. The team has a new id; the three role assignments were carried across by id, not by name.`,
        );
        setReplacing(null);
        return reply;
      } catch (cause) {
        setReport(
          `“${original.name}” was deleted and the replacement was REFUSED. That team no longer exists. Its details are still in the form below — create it again.`,
        );
        throw cause;
      }
    },
  );

  if (active.length === 0) {
    return (
      <>
        <ItemHeading item={13} marker={status.marker} caption={status.caption} />
        <Section title="Nobody to put in a team yet" eyebrow="Blocked">
          <Banner tone="note" title="Item 2 comes first">
            <p style={{ margin: 0 }}>
              Every role on a team is a user id, and the server checks each one
              exists in this organisation before it writes anything.
            </p>
          </Banner>
        </Section>
        <FormatFor descriptor={descriptor} />
      </>
    );
  }

  return (
    <>
      <ItemHeading item={13} marker={status.marker} caption={status.caption} />

      {report && (
        <Section title={report.includes("REFUSED") ? "The replacement did not land" : "Replaced"} eyebrow="Result">
          <Banner
            tone={report.includes("REFUSED") ? "blocked" : "note"}
            title={report.includes("REFUSED") ? "Nothing is there now" : "Done"}
          >
            <p style={{ margin: 0 }}>{report}</p>
          </Banner>
        </Section>
      )}

      <Section
        title={replacing ? `Replace “${replacing.name}”` : "Add a team"}
        eyebrow={replacing ? "Edit" : "Create"}
      >
        {replacing && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner tone="warn" title="Editing means deleting and recreating">
              <p style={{ margin: 0 }}>
                There is no route that edits a demo team, and the name is unique
                per organisation — so the old team must be deleted before the
                new one can be created under the same name. Two calls, not
                atomic. If a demo is booked against this team the delete will be
                refused and nothing will change, which is the safe outcome.
              </p>
            </Banner>
          </div>
        )}

        <EntityForm
          key={replacing?.id ?? "new"}
          descriptor={descriptor}
          submitLabel={replacing ? "Delete and recreate" : "Create team"}
          busy={create.isPending || replace.isPending}
          serverError={asApiError(create.error) ?? asApiError(replace.error)}
          resetSignal={create.submittedAt}
          initial={
            replacing
              ? {
                  name: replacing.name,
                  // By id. Change #10 is what makes this possible at all.
                  lead_user_id: replacing.lead_user_id ?? "",
                  media_rep_id: replacing.media_rep_id ?? "",
                  sales_rep_id: replacing.sales_rep_id ?? "",
                  member_ids: replacing.members.map((m) => m.id),
                }
              : undefined
          }
          onSubmit={(body) =>
            replacing
              ? replace.mutate({ original: replacing, body: body as Record<string, unknown> })
              : create.mutate(body as Record<string, unknown>)
          }
          slots={Object.fromEntries(
            (["lead_user_id", "media_rep_id", "sales_rep_id"] as const).map((field) => [
              field,
              ({ value, onChange, id }: { value: unknown; onChange: (n: unknown) => void; id: string }) => (
                <Select
                  id={id}
                  placeholder="Nobody"
                  options={people}
                  value={String(value ?? "")}
                  onChange={(e) => onChange(e.target.value)}
                />
              ),
            ]),
          )}
        >
          {replacing && (
            <div style={{ marginBlockStart: "var(--s4)" }}>
              <Button variant="quiet" onClick={() => setReplacing(null)}>
                Cancel and leave the existing team alone
              </Button>
            </div>
          )}
        </EntityForm>
      </Section>

      <Section title="Teams" eyebrow="Current">
        {teams.isError ? (
          <ReadError error={teams.error} what="the demo teams" />
        ) : (
          <DataTable
            columns={["Team", "Lead", "Media", "Sales", "Members", ""]}
            empty="No teams. Demos are still bookable; they simply carry no team."
            rows={(teams.data ?? []).map((team) => [
              team.name,
              team.lead ?? <span key="l" className={s.muted}>nobody</span>,
              team.media_rep ?? <span key="m" className={s.muted}>nobody</span>,
              team.sales_rep ?? <span key="sr" className={s.muted}>nobody</span>,
              team.members.length === 0 ? (
                <span key="mm" className={s.muted}>none</span>
              ) : (
                team.members.map((m) => m.name).join(", ")
              ),
              <span key="a" style={{ display: "flex", gap: "var(--s2)" }}>
                <Button onClick={() => setReplacing(team)}>Edit</Button>
                <Button
                  variant="danger"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(team.id)}
                >
                  Remove
                </Button>
              </span>,
            ])}
          />
        )}
        <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)" }}>
          The names above are what the server resolved; the form edits the ids
          behind them. Two people with the same name are therefore not a hazard
          here — which they were before backend change #10 supplied the ids.
        </p>
        {remove.error && (
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Banner
              tone="blocked"
              title="That team could not be removed"
              serverMessage={asApiError(remove.error)?.detail ?? String(remove.error)}
            >
              <p style={{ margin: 0 }}>
                A team with demos booked against it cannot be deleted — and
                therefore cannot be edited either, since editing goes through a
                delete. Its composition is fixed for as long as those demos
                exist.
              </p>
            </Banner>
          </div>
        )}
      </Section>

      <FormatFor descriptor={descriptor} />
    </>
  );
}
