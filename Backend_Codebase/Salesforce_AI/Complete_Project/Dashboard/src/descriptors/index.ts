/**
 * The eleven descriptors, and the five consumers they feed (§3.4):
 * `<EntityForm>`, `import/validate.ts`, `<FormatPanel>`, `import/template.ts`
 * and `checklist/status.ts`.
 */
import {
  messageTemplates,
  pricing,
  programs,
  proposalTemplates,
  skills,
} from "./catalogue";
import {
  approvalRules,
  demoTeams,
  playbooks,
  settings,
  vendors,
} from "./governance";
import { staff } from "./staff";
import type { Descriptor, EntityKey } from "./types";

export const DESCRIPTORS = {
  staff,
  skills,
  programs,
  pricing,
  proposalTemplates,
  messageTemplates,
  playbooks,
  approvalRules,
  demoTeams,
  vendors,
  settings,
} as const satisfies Record<EntityKey, Descriptor>;

export const ALL_DESCRIPTORS: readonly Descriptor[] = Object.values(DESCRIPTORS);

/** The nine entity types the reseed bundle carries (§5.8). */
export const BUNDLE_ENTITIES: readonly EntityKey[] = ALL_DESCRIPTORS.filter(
  (d) => d.inBundle,
).map((d) => d.key);

/**
 * Dependency order — a topological sort of `dependsOn`, which is itself derived
 * from foreign keys and handler validation (`02` §0), not from the manual's
 * flat list. Import and the checklist both need to work in this order.
 */
export function dependencyOrder(): EntityKey[] {
  const done = new Set<EntityKey>();
  const order: EntityKey[] = [];
  const visit = (key: EntityKey, seen: Set<EntityKey>) => {
    if (done.has(key)) return;
    if (seen.has(key)) throw new Error(`dependency cycle at ${key}`);
    seen.add(key);
    for (const parent of DESCRIPTORS[key].dependsOn) visit(parent, seen);
    done.add(key);
    order.push(key);
  };
  for (const d of ALL_DESCRIPTORS) visit(d.key, new Set());
  return order;
}

export type { Descriptor, EntityKey } from "./types";
