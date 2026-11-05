/**
 * The frame every item screen shares, and the two things they all need.
 *
 * `<ItemScreen>` renders the checklist row's own heading, its live status and
 * the format panel, so an item screen is only the part that is actually
 * specific to that entity. `useEntity` is the read/write pair: one shape-parsed
 * read, and a mutation that invalidates it and nothing else.
 *
 * **Mutations never retry** (D17) — that is the `queryClient` default and no
 * screen may override it. The server reads no `Idempotency-Key` and has no
 * dedupe on any admin write, so a retried POST creates a second programme, a
 * second vendor, a second approval rule, and says nothing.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ZodType } from "zod";

import { request } from "../api/client";
import { isApiError, type ApiError } from "../api/errors";
import { ITEM_BY_NUMBER, TIER_LABEL } from "../checklist/items";
import type { Descriptor } from "../descriptors/types";
import { FormatPanel } from "./FormatPanel";
import { Banner, Panel, StatusMarker, styles as s, type Status } from "./primitives";

const SPOKEN: Record<Status, string> = {
  done: "satisfied",
  partial: "partial",
  none: "not started",
  blocked: "cannot be satisfied here",
};

export function ItemHeading({
  item,
  marker,
  caption,
}: {
  item: number;
  marker: Status | "pending";
  caption: string;
}) {
  const row = ITEM_BY_NUMBER.get(item)!;
  return (
    <Panel eyebrow={`Item ${row.n} · ${TIER_LABEL[row.tier]}`} title={row.title}>
      <p style={{ display: "flex", alignItems: "baseline", gap: "var(--s2)", margin: 0 }}>
        {marker === "pending" ? (
          <span className={s.muted}>Reading the API…</span>
        ) : (
          <>
            <StatusMarker status={marker} label={SPOKEN[marker]} />
            <span className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
              {caption}
            </span>
          </>
        )}
      </p>
    </Panel>
  );
}

/** Renders whatever the read failed with, in the server's own words. */
export function ReadError({ error, what }: { error: unknown; what: string }) {
  return (
    <Banner
      tone="blocked"
      title={`This console could not read ${what}`}
      serverMessage={isApiError(error) ? error.detail : String(error)}
    >
      <p style={{ margin: 0 }}>
        Nothing below is the state of your organisation — it is what this console
        managed to read, which is nothing.
      </p>
    </Banner>
  );
}

export function FormatFor({ descriptor }: { descriptor: Descriptor }) {
  return <FormatPanel descriptor={descriptor} />;
}

/** One list read, shape-parsed, with its query key exposed for invalidation. */
export function useList<T>(key: string, path: string, shape: ZodType<T>) {
  return useQuery({
    queryKey: [key],
    queryFn: () => request(path, { as: "org", shape }),
  });
}

/**
 * A write, plus the reads it invalidates.
 *
 * `invalidates` is explicit rather than a blanket refetch: the rail derives
 * item statuses from twelve reads, and re-issuing all of them after every
 * keystroke-sized write would make the console feel like it was thinking.
 */
export function useWrite<TVars>(
  invalidates: string[],
  fn: (vars: TVars) => Promise<unknown>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const key of invalidates) queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
}

export function asApiError(error: unknown): ApiError | null {
  return isApiError(error) ? error : null;
}

export function Section({
  title,
  eyebrow,
  actions,
  children,
}: {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Panel title={title} eyebrow={eyebrow} actions={actions}>
      {children}
    </Panel>
  );
}
