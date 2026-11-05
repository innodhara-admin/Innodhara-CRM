/**
 * Item 4 — what you sell.
 *
 * Two things this screen says up front, because both surprise people (§5.4):
 *
 *  - **`code` comes back changed.** `admin.py · add_program` upper-cases it on
 *    write and it is UNIQUE per organisation, compared case-insensitively. An
 *    operator who types `dc-audit` and later searches for it will not find it.
 *  - **There is no `PATCH`.** Editing a programme means delete-and-recreate,
 *    and the delete is **refused** once a project or a proposal references it —
 *    which is most of the time, on any organisation that has done work. So the
 *    name and description are effectively permanent from first use, and the
 *    description is the thing the offering matcher reads. That is a reason to
 *    write it properly now, and the screen says so at the field rather than in
 *    a footnote nobody reads before typing.
 *
 * The delete also cascades: `delete_program` removes that programme's pricing
 * tables, proposal templates, playbooks and playbook suggestions. Items 5, 6
 * and 8 all fall with it, which the confirmation states.
 *
 * ## P13 — the one refusal this console contradicts
 *
 * §4.1's rule is that a server refusal is rendered verbatim, because the
 * backend's wording already says what to do and this console is not in a
 * position to say it better. `delete_program`'s refusal is the exception that
 * proves it: it ends *"Mark it inactive instead"*, and **no route writes
 * `Program.is_active`** — grepped across `app/api/`, not inferred from a
 * missing `PATCH`.
 *
 * Rendering that verbatim and stopping would inherit the lie: the operator goes
 * hunting for a control that does not exist, and in a product where every other
 * refusal names a real remedy they conclude they have missed a screen. So the
 * message is still quoted in full — suppressing a server's own words is worse —
 * and the console then contradicts its last sentence in its own voice.
 * **Quote it, then contradict it; never quote it alone.** `09` §4a carries the
 * finding and the eventual fix, which needs an eleventh backend change.
 */
import { useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { ProgramsRead } from "../api/reads";
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
import { Banner, Button, DataTable, StatusMarker, styles as s } from "../ui/primitives";

const descriptor = DESCRIPTORS.programs;

export function Programs({ status }: { status: ItemStatus }) {
  const programs = useList("programs", endpoints.programs, ProgramsRead);
  const [confirming, setConfirming] = useState<{ id: string; name: string } | null>(null);

  const create = useWrite<Record<string, unknown>>(
    ["programs", "pricing", "proposalTemplates", "playbooks"],
    (body) => request(endpoints.programs, { as: "org", method: "POST", body }),
  );

  const remove = useWrite<string>(
    ["programs", "pricing", "proposalTemplates", "playbooks"],
    (id) => request(endpoints.program(id), { as: "org", method: "DELETE" }),
  );

  return (
    <>
      <ItemHeading item={4} marker={status.marker} caption={status.caption} />

      <Section title="Add an offering" eyebrow="Create">
        <EntityForm
          descriptor={descriptor}
          submitLabel="Create offering"
          busy={create.isPending}
          serverError={asApiError(create.error)}
          resetSignal={create.submittedAt}
          onSubmit={(body) => create.mutate(body as Record<string, unknown>)}
        >
          <Banner tone="note" title="This is close to permanent">
            <p style={{ margin: 0 }}>
              There is no route that edits an offering. Changing anything means
              deleting and recreating it, and the delete is refused once a
              project or proposal references this offering. Write the description
              as though it were final — it is what the AI reads to decide which
              offering a conversation was about.
            </p>
          </Banner>
        </EntityForm>
      </Section>

      <Section title="What you sell" eyebrow="Current">
        {programs.isError ? (
          <ReadError error={programs.error} what="the offering list" />
        ) : (
          <DataTable
            columns={["", "Code", "Name", "Description", ""]}
            empty="Nothing to sell yet. Conversations cannot be matched to an offering, and no proposal can be built."
            rows={(programs.data ?? []).map((p) => [
              <StatusMarker
                key="m"
                status={p.description?.trim() ? "done" : "partial"}
                label={p.description?.trim() ? "described" : "no description"}
              />,
              <span key="c" className={s.mono}>
                {p.code}
              </span>,
              <span key="n">
                {p.name}
                {!p.is_active && <span className={s.muted}> · inactive</span>}
              </span>,
              p.description ?? (
                <span key="d" className={s.muted}>
                  none — the matcher has nothing to read
                </span>
              ),
              <Button
                key="x"
                variant="danger"
                disabled={remove.isPending}
                onClick={() => setConfirming({ id: p.id, name: p.name })}
              >
                Remove
              </Button>,
            ])}
          />
        )}

        {confirming && (
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Banner tone="warn" title={`Remove ${confirming.name}?`}>
              <p style={{ margin: "0 0 var(--s3)" }}>
                This also removes that offering's <strong>rate cards, proposal
                templates and playbooks</strong> — items 5, 6 and 8 fall with it.
                The server will refuse outright if any project or proposal
                references the offering.
              </p>
              <div style={{ display: "flex", gap: "var(--s3)" }}>
                <Button
                  variant="danger"
                  onClick={() => {
                    remove.mutate(confirming.id);
                    setConfirming(null);
                  }}
                >
                  Remove it
                </Button>
                <Button variant="quiet" onClick={() => setConfirming(null)}>
                  Keep it
                </Button>
              </div>
            </Banner>
          </div>
        )}

        {remove.error && (
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Banner
              tone="blocked"
              title="The offering could not be removed"
              serverMessage={asApiError(remove.error)?.detail ?? String(remove.error)}
            >
              <p style={{ margin: "0 0 var(--s2)" }}>
                The server's message is shown above word for word, as every
                refusal in this console is.
              </p>
              <p style={{ margin: 0 }}>
                <strong>Ignore its last sentence.</strong> There is no way to
                mark an offering inactive: <code>Program.is_active</code> is
                readable and is written by no route in the API, so the control
                it sends you looking for does not exist and you have not missed
                a screen. An offering that cannot be deleted stays in every
                picker. Recorded as <strong>P13</strong>; retiring an offering
                in use needs a backend route that does not exist yet.
              </p>
            </Banner>
          </div>
        )}
      </Section>

      <FormatFor descriptor={descriptor} />
    </>
  );
}
