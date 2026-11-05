/**
 * What reaches the operator's eyes, checked as text — 07_BUILD_PLAN.md Task 25.
 *
 * Prose written in this console is rendered as **plain text**, so markdown in
 * it arrives on screen with its punctuation intact. Three instances shipped
 * before anyone noticed, and all three were found by *looking at a browser*:
 *
 * | where | what was on screen |
 * |---|---|
 * | `BUCKET_NOTE` (Task 24) | a backticked `users`, on the reset screen, immediately above a destructive control |
 * | `Staff.tsx` (Task 25) | the same, beneath the account table |
 * | `skills.quote` (Task 25) | "the neutral skill `general`" — `02` §3's **own markdown emphasis**, inside a quotation that §9 requires to be verbatim |
 *
 * ## What this guard covers, and what it deliberately does not
 *
 * It checks **prose that exists as data** — exported constants and descriptor
 * fields — which needs no parsing and is therefore exact.
 *
 * It does **not** scan JSX text in the screens. Two attempts did, and both were
 * worse than nothing: a backtick pair in JSX text is character-for-character
 * identical to a template literal, so distinguishing them needs a real parser,
 * and the versions that guessed reported five correct files as broken. **A
 * guard that cries wolf gets deleted**, which would take the exact half with
 * it. Screens have no unit tests by design (D11) and are covered by the browser
 * pass every task ends with — which is, in fact, what caught all three.
 *
 * Where a code voice is wanted on screen, use a `<code>` element.
 */
import { describe, expect, it } from "vitest";

import { BUCKET_NOTE, BUCKET_TITLE } from "../bundle/reset";
import { ITEMS } from "../checklist/items";
import { ALL_DESCRIPTORS } from "../descriptors";

const TICK = String.fromCharCode(96);

/**
 * A backtick, or markdown's double asterisk.
 *
 * **Not the underscore, and not a single asterisk.** Captions here legitimately
 * name API symbols, and `super_admin`, `set_skill` and `max_open_tasks` are
 * content rather than emphasis. A first version included underscores and
 * reported eight correct captions as defects, which is how that was found.
 */
const MARKDOWN = new RegExp("(" + TICK + "|\\*\\*)");

const say = (label: string, value: string): [string, string] => [label, value];

describe("no markdown in prose the console renders", () => {
  const strings: Array<[string, string]> = [
    ...Object.entries(BUCKET_NOTE).map(([k, v]) => say(`BUCKET_NOTE.${k}`, v)),
    ...Object.entries(BUCKET_TITLE).map(([k, v]) => say(`BUCKET_TITLE.${k}`, v)),
    ...ALL_DESCRIPTORS.flatMap((d) => [
      say(`${d.key}.title`, d.title),
      say(`${d.key}.reimport`, d.reimport),
      ...d.fields.flatMap((f) => [
        say(`${d.key}.${f.field}.label`, f.label),
        say(`${d.key}.${f.field}.caption`, f.caption),
        // `why` exists on the two enforcement kinds the server does not fully
        // declare; the generated-schema kind carries none.
        say(`${d.key}.${f.field}.why`, "why" in f.enforcement ? f.enforcement.why : ""),
      ]),
      ...(d.crossFieldRules ?? []).map((r) => say(`${d.key}.${r.field}.says`, r.says)),
    ]),
    ...ITEMS.map((i) => say(`item ${i.n}.title`, i.title)),
  ];

  it("is looking at the prose it claims to be looking at", () => {
    // A list built by mapping can quietly become empty; this is the assertion
    // that stops every case below passing vacuously.
    expect(strings.length).toBeGreaterThan(80);
    expect(strings.map(([k]) => k)).toContain("BUCKET_NOTE.KEEP");
  });

  it("catches the shape that shipped", () => {
    expect("the " + TICK + "users" + TICK + " table").toMatch(MARKDOWN);
    expect("**never** removed").toMatch(MARKDOWN);
    // Content, not emphasis — every one of these is a real caption string.
    expect("Never removed, by any flag — the audit log stays").not.toMatch(MARKDOWN);
    expect("rack-and-stack").not.toMatch(MARKDOWN);
    expect("super_admin cannot be assigned here · admin.py").not.toMatch(MARKDOWN);
    expect("ops.py · set_skill stores whatever string it is given").not.toMatch(MARKDOWN);
  });

  it.each(strings)("%s", (_label, value) => {
    expect(value, "markdown here is rendered as punctuation").not.toMatch(MARKDOWN);
  });
});

describe("the manual's words are the manual's, not another document's markup", () => {
  // The sharper case: a quotation §9 requires to be verbatim must not carry the
  // emphasis of the document it was transcribed from.
  it.each(ALL_DESCRIPTORS.map((d) => [d.key, d] as const))("%s", (_key, d) => {
    expect(d.quote, "markdown in a verbatim quotation").not.toMatch(MARKDOWN);
    expect(d.ifSkipped, "markdown in a verbatim quotation").not.toMatch(MARKDOWN);
  });

  it.each(ITEMS.map((i) => [`item ${i.n}`, i] as const))("%s", (_n, item) => {
    expect(item.quote, "markdown in a verbatim quotation").not.toMatch(MARKDOWN);
    expect(item.ifSkipped, "markdown in a verbatim quotation").not.toMatch(MARKDOWN);
  });
});
