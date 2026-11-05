/**
 * Item 5 — a rate card for each offering.
 *
 * ## `default_quantity` is a checkbox plus a number, never a number
 *
 * `null` means *"this org did not say how many"*, and the value estimate treats
 * that differently from a stated quantity. `admin.py · PricingItem` carries ten
 * lines explaining that flattening the tri-state to a number pre-filled with 1
 * was a real regression, and §3.3 turns that into a rule: the control is a
 * checkbox and a number, the checkbox starts clear, and clearing it sends null.
 *
 * ## Versioned, and the version history is shown
 *
 * The button says **"Publish new version"** because that is what `POST` does —
 * there is no edit. A proposal locks `pricing_table_id` **and**
 * `pricing_version`, so a rate card that is already out on a proposal cannot be
 * changed underneath it. That is what makes editing prices safe, and it only
 * reads as safe when the superseded versions are visible.
 *
 * ## Delete promotes the predecessor, and says nothing about it
 *
 * `delete_pricing_version` calls `_promote_predecessor` when the version it
 * removed was current — then returns `{"deleted": true}`. Nothing in that reply
 * mentions the promotion, so the screen re-reads and states which version is
 * current now. Without that the operator sees a delete that appears to have
 * done nothing.
 */
import { useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { PricingRead, ProgramsRead } from "../api/reads";
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
import {
  Banner,
  Button,
  Field,
  QuantityField,
  Select,
  TextInput,
  styles as s,
} from "../ui/primitives";
import { VersionHistory } from "../ui/VersionHistory";
import { useQuery } from "@tanstack/react-query";

const descriptor = DESCRIPTORS.pricing;

type Line = {
  code: string;
  label: string;
  unit: string;
  unit_price: number | "";
  default_quantity: number | null;
  notes: string;
};

const BLANK: Line = {
  code: "",
  label: "",
  unit: "",
  unit_price: "",
  // Clear, not 1. §3.3: the operator states a quantity or does not.
  default_quantity: null,
  notes: "",
};

function LineEditor({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (next: unknown) => void;
}) {
  const lines: Line[] = Array.isArray(value) && value.length > 0 ? (value as Line[]) : [BLANK];
  const set = (index: number, patch: Partial<Line>) =>
    onChange(lines.map((line, i) => (i === index ? { ...line, ...patch } : line)));

  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      {lines.map((line, i) => (
        <div
          key={i}
          style={{
            display: "grid",
            gap: "var(--s2)",
            paddingBlockEnd: "var(--s3)",
            borderBlockEnd: "1px solid var(--rule)",
          }}
        >
          <p className={s.eyebrow}>{`Line ${i + 1}`}</p>
          <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>
            <TextInput
              mono
              placeholder="code"
              aria-label={`Line ${i + 1} code`}
              value={line.code}
              onChange={(e) => set(i, { code: e.target.value })}
            />
            <TextInput
              placeholder="label"
              aria-label={`Line ${i + 1} label`}
              value={line.label}
              onChange={(e) => set(i, { label: e.target.value })}
            />
            <TextInput
              placeholder="unit — per rack, per seat, per site"
              aria-label={`Line ${i + 1} unit`}
              value={line.unit}
              onChange={(e) => set(i, { unit: e.target.value })}
            />
            <TextInput
              type="number"
              min={0}
              step="any"
              placeholder="unit price"
              aria-label={`Line ${i + 1} unit price`}
              value={line.unit_price === "" ? "" : String(line.unit_price)}
              onChange={(e) =>
                set(i, { unit_price: e.target.value === "" ? "" : Number(e.target.value) })
              }
            />
          </div>
          <QuantityField
            id={`pricing-qty-${i}`}
            value={line.default_quantity}
            onChange={(next) => set(i, { default_quantity: next })}
          />
          <TextInput
            placeholder="notes (optional)"
            aria-label={`Line ${i + 1} notes`}
            value={line.notes}
            onChange={(e) => set(i, { notes: e.target.value })}
          />
          {lines.length > 1 && (
            <div>
              <Button
                variant="quiet"
                onClick={() => onChange(lines.filter((_, j) => j !== i))}
              >
                Remove line
              </Button>
            </div>
          )}
        </div>
      ))}
      <div>
        <Button onClick={() => onChange([...lines, { ...BLANK }])}>Add a line</Button>
      </div>
    </div>
  );
}

/** Blanks out of the body: `""` is not a price and `""` is not a note. */
function cleanLines(value: unknown): unknown {
  if (!Array.isArray(value)) return value;
  return (value as Line[]).map((line) => ({
    code: line.code,
    label: line.label,
    ...(line.unit ? { unit: line.unit } : {}),
    unit_price: line.unit_price === "" ? undefined : line.unit_price,
    // Always sent, including as null — this is the tri-state, and omitting it
    // would make "not stated" indistinguishable from "not filled in".
    default_quantity: line.default_quantity,
    ...(line.notes ? { notes: line.notes } : {}),
  }));
}

export function Pricing({ status }: { status: ItemStatus }) {
  const programs = useList("programs", endpoints.programs, ProgramsRead);
  const active = (programs.data ?? []).filter((p) => p.is_active);
  const [programId, setProgramId] = useState<string>("");
  const chosen = programId || active[0]?.id || "";
  const [promoted, setPromoted] = useState<string | null>(null);

  const versions = useQuery({
    queryKey: ["pricing", chosen],
    enabled: Boolean(chosen),
    queryFn: () => request(endpoints.pricing(chosen), { as: "org", shape: PricingRead }),
  });

  const publish = useWrite<Record<string, unknown>>(["pricing"], (body) =>
    request(endpoints.pricing(chosen), { as: "org", method: "POST", body }),
  );

  const remove = useWrite<number>(["pricing"], async (version) => {
    const reply = await request(endpoints.pricingVersion(chosen, version), {
      as: "org",
      method: "DELETE",
    });
    // The reply is `{"deleted": true}` and carries no promotion. Re-read, then
    // say what is current now.
    const after = await request(endpoints.pricing(chosen), { as: "org", shape: PricingRead });
    const current = after.find((v) => v.is_current);
    setPromoted(
      current
        ? `v${version} is gone. v${current.version} is now the current rate card.`
        : `v${version} is gone. This offering now has no rate card at all — no proposal can be created for it.`,
    );
    return reply;
  });

  if (active.length === 0) {
    return (
      <>
        <ItemHeading item={5} marker={status.marker} caption={status.caption} />
        <Section title="Nothing to price yet" eyebrow="Blocked">
          <Banner tone="note" title="Item 4 comes first">
            <p style={{ margin: 0 }}>
              A rate card hangs off an offering by foreign key. Create one on
              item 4 and this screen fills in.
            </p>
          </Banner>
        </Section>
        <FormatFor descriptor={descriptor} />
      </>
    );
  }

  return (
    <>
      <ItemHeading item={5} marker={status.marker} caption={status.caption} />

      <Section title="Which offering" eyebrow="Rate cards are per offering">
        <Field label="Offering" htmlFor="pricing-program">
          <Select
            id="pricing-program"
            options={active.map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))}
            value={chosen}
            onChange={(e) => {
              setProgramId(e.target.value);
              setPromoted(null);
            }}
          />
        </Field>
      </Section>

      <Section title="Publish a new version" eyebrow="Create">
        <EntityForm
          descriptor={descriptor}
          submitLabel="Publish new version"
          busy={publish.isPending}
          serverError={asApiError(publish.error)}
          initial={{ currency: "", items: [BLANK] }}
          onSubmit={(values) =>
            publish.mutate({ ...values, items: cleanLines(values.items) } as Record<
              string,
              unknown
            >)
          }
          slots={{
            items: ({ value, onChange }) => <LineEditor value={value} onChange={onChange} />,
          }}
        >
          <Banner tone="note" title="This supersedes, it does not overwrite">
            <p style={{ margin: 0 }}>
              Publishing creates version {(versions.data?.length ?? 0) + 1} and
              flips the current flag. Every proposal already sent keeps the
              version it locked, at the price it quoted.
            </p>
          </Banner>
        </EntityForm>
      </Section>

      <Section title="Versions" eyebrow="History">
        {promoted && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner tone="note" title="Removed">
              <p style={{ margin: 0 }}>{promoted}</p>
            </Banner>
          </div>
        )}
        {versions.isError ? (
          <ReadError error={versions.error} what="the rate card history" />
        ) : (
          <VersionHistory
            busy={remove.isPending}
            empty="No rate card. Proposals for this offering are refused: “No pricing table for this offering. Ask your administrator to add one.”"
            versions={(versions.data ?? []).map((v) => ({
              id: v.id,
              version: v.version,
              isCurrent: v.is_current,
              summary: (
                <span className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
                  {`${v.items.length} line${v.items.length === 1 ? "" : "s"} · ${v.currency} · `}
                  {v.items
                    .map(
                      (line) =>
                        `${line.code} ${line.unit_price}${
                          line.default_quantity === null ? "" : ` ×${line.default_quantity}`
                        }`,
                    )
                    .join(", ")}
                </span>
              ),
            }))}
            onDelete={(v) => remove.mutate(v.version)}
            deleteHint={
              <>
                Removing the current version promotes the highest remaining one
                back to current. The server's reply does not say which — it
                returns <code>{"{\"deleted\": true}"}</code> — so this screen
                re-reads and tells you. A version a proposal has locked cannot be
                removed at all.
              </>
            }
          />
        )}
        {remove.error && (
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Banner
              tone="blocked"
              title="That version could not be removed"
              serverMessage={asApiError(remove.error)?.detail ?? String(remove.error)}
            />
          </div>
        )}
      </Section>

      <FormatFor descriptor={descriptor} />
    </>
  );
}
