/**
 * Read-shape drift — 07_BUILD_PLAN.md A1.
 *
 * Eleven of the fifteen reads this console makes return `"schema": {}` in the
 * spec, so their shapes cannot be generated and are hand-written in
 * `reads.ts` (Task 15). Hand-written means they can drift, and a shape that has
 * drifted produces `undefined` where a status derivation expected a value —
 * which renders as "not started" rather than as "this console can no longer
 * read the server".
 *
 * So a failed parse is recorded here and surfaced, never swallowed:
 *
 *  - the client does not return the body,
 *  - a banner names the route and the failing path,
 *  - and every checklist status derived from that read becomes `—` with the
 *    reason, **never `○`** — "not started" and "cannot be read" are different
 *    facts and §6 exists to keep them apart.
 */
import { useSyncExternalStore } from "react";

export type Drift = {
  route: string;
  /** Zod's own path, e.g. `[0, "rank"]`, rendered for a human. */
  path: string;
  message: string;
  /** The keys that did arrive, which is usually enough to spot the rename. */
  receivedKeys: string[];
  at: number;
};

let drifts: Drift[] = [];
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((l) => l());
}

export const driftLog = {
  get: (): Drift[] => drifts,

  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },

  report(drift: Omit<Drift, "at">): void {
    // One entry per route: a list that grows on every poll would bury the first
    // and most useful report under identical repeats.
    drifts = [...drifts.filter((d) => d.route !== drift.route), { ...drift, at: Date.now() }];
    emit();
  },

  /** True when a given read is currently unreadable, so status can show `—`. */
  has(route: string): boolean {
    return drifts.some((d) => d.route === route);
  },

  clear(): void {
    drifts = [];
    emit();
  },
};

export function useDrifts(): Drift[] {
  return useSyncExternalStore(driftLog.subscribe, driftLog.get, driftLog.get);
}
