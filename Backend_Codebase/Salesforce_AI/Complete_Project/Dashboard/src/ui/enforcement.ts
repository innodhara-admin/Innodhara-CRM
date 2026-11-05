/**
 * Who enforces a rule — 07_BUILD_PLAN.md A2.
 *
 * Declared here, in the presentation layer, because the caption is the only
 * place this distinction is ever visible. Task 15's `descriptors/types.ts`
 * imports this rather than redeclaring it: two copies of an honesty model is
 * how the model starts lying.
 *
 * The three values exist because the generator drops every constraint declared
 * inside an `anyOf` branch (P2), so "in the generated schema" and "enforced by
 * the server" stopped being the same statement. Sixteen console-relevant rules
 * sit in the gap. Calling them `ui-only` would tell the operator the server
 * accepts anything, which is false; calling them `schema` would claim a
 * provenance they do not have.
 */
export type Enforcement =
  /** In `generated.ts`. The server enforces it and the console validates it. */
  | { kind: "schema" }
  /**
   * The server enforces it; the generated schema does not carry it. Either a
   * handler-body check (`admin.py · _validated_department`) or a constraint the
   * generator dropped and `constraints.generated.ts` recovered.
   * `source` cites file and symbol — never a line number, which is wrong within
   * a week (06_DESIGN.md §9).
   */
  | { kind: "backend-undeclared"; source: string }
  /**
   * The server accepts anything. The rule exists only in this console.
   * `why` is required, not conventional: the caption has to say what the server
   * does instead, and a marker with no explanation is just a decoration.
   */
  | { kind: "ui-only"; why: string };

export const ENFORCEMENT_LABEL: Record<Enforcement["kind"], string> = {
  schema: "checked by the server",
  "backend-undeclared": "checked by the server",
  "ui-only": "checked here only",
};
