/**
 * Item 15 — vendors.
 *
 * All six fields read back since backend change #7. Before it `GET /vendors`
 * returned `{id, name, category, notes}` and the contact name, phone and email
 * were written and never readable — so a console could collect them and then
 * show the operator nothing.
 *
 * ## The delete is unguarded, and that is correct
 *
 * **The plan said otherwise and was out of date.** `07`'s Task 20 Step 3 said
 * the delete is refused when `action_items.external_wait["vendor_id"]` names
 * the vendor. That guard was written, found to be checking a key **no caller
 * ever writes**, and then removed outright rather than fixed — `09` §4a records
 * it. `ops.py · delete_vendor` now carries the reasoning: nothing in the schema
 * references `vendors.id`; the only place a vendor appears outside its own
 * table is a free-text JSON blob holding a typed `vendor_name`, which is a name
 * and not a reference. Deleting a vendor therefore cannot orphan anything, and
 * a task's recorded promise keeps its typed name either way.
 *
 * So this screen promises no guard. Saying "the server will stop you" when it
 * will not is the failure mode this whole console is written against.
 *
 * ## Nothing here is unique
 *
 * No constraint of any kind: the same vendor can be created twice, and a
 * re-import creates duplicates silently. The list below flags repeated names
 * because that is the only place it can be noticed.
 */
import { useMemo } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { VendorsRead } from "../api/reads";
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

const descriptor = DESCRIPTORS.vendors;

export function Vendors({ status }: { status: ItemStatus }) {
  const vendors = useList("vendors", endpoints.vendors, VendorsRead);

  const create = useWrite<Record<string, unknown>>(["vendors"], (body) =>
    request(endpoints.vendors, { as: "org", method: "POST", body }),
  );

  const remove = useWrite<string>(["vendors"], (id) =>
    request(endpoints.vendor(id), { as: "org", method: "DELETE" }),
  );

  const duplicates = useMemo(() => {
    const seen = new Map<string, number>();
    for (const v of vendors.data ?? []) {
      const key = v.name.trim().toLowerCase();
      seen.set(key, (seen.get(key) ?? 0) + 1);
    }
    return new Set([...seen.entries()].filter(([, n]) => n > 1).map(([k]) => k));
  }, [vendors.data]);

  return (
    <>
      <ItemHeading item={15} marker={status.marker} caption={status.caption} />

      <Section title="Add a supplier" eyebrow="Create">
        <EntityForm
          descriptor={descriptor}
          submitLabel="Add vendor"
          busy={create.isPending}
          serverError={asApiError(create.error)}
          resetSignal={create.submittedAt}
          onSubmit={(body) => create.mutate(body as Record<string, unknown>)}
        >
          <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s2) 0 0" }}>
            Only the name is required, and <strong>nothing here is validated or
            unique</strong> — the request body is written straight into the row.
            The same supplier can be added twice and the server will not mind.
          </p>
        </EntityForm>
      </Section>

      <Section title="Suppliers" eyebrow="Current">
        {vendors.isError ? (
          <ReadError error={vendors.error} what="the vendor list" />
        ) : (
          <DataTable
            columns={["", "Name", "Contact", "Phone", "Email", "Category", ""]}
            empty="No vendors. Vendor promises can still be typed as free text, but are not tracked as vendors."
            rows={(vendors.data ?? []).map((v) => [
              <StatusMarker
                key="m"
                status={duplicates.has(v.name.trim().toLowerCase()) ? "partial" : "done"}
                label={
                  duplicates.has(v.name.trim().toLowerCase())
                    ? "duplicate name"
                    : "recorded"
                }
              />,
              <span key="n">
                {v.name}
                {duplicates.has(v.name.trim().toLowerCase()) && (
                  <span className={s.muted}> · more than one row has this name</span>
                )}
              </span>,
              v.contact_name ?? <span key="c" className={s.muted}>—</span>,
              v.phone ?? <span key="p" className={s.muted}>—</span>,
              v.email ?? <span key="e" className={s.muted}>—</span>,
              v.category ?? <span key="g" className={s.muted}>—</span>,
              <Button
                key="d"
                variant="danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(v.id)}
              >
                Remove
              </Button>,
            ])}
          />
        )}

        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="note" title="Removing a vendor is safe, and nothing will stop you">
            <p style={{ margin: 0 }}>
              Nothing in the database points at a vendor row — no foreign key, no
              id-shaped column. A vendor promise recorded against a task stores
              the <em>typed name</em>, not a reference, so it survives the row
              being deleted and keeps reading exactly as it did. There is
              deliberately no confirmation here beyond this sentence: a
              confirmation implies a consequence, and there is not one.
            </p>
          </Banner>
        </div>

        {remove.error && (
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Banner
              tone="blocked"
              title="That vendor could not be removed"
              serverMessage={asApiError(remove.error)?.detail ?? String(remove.error)}
            />
          </div>
        )}
      </Section>

      <FormatFor descriptor={descriptor} />
    </>
  );
}
