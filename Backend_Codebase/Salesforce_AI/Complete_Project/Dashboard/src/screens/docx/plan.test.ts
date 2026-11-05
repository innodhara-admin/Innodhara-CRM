/**
 * The editor's plan arithmetic, tested without React (Task 20 Step 1).
 *
 * Everything the administrator does in the editor — accept, reject, reword,
 * move, add — is a pure function from one plan to the next, so it is testable
 * here rather than through a screen this suite deliberately does not render
 * (D11, no component tests).
 *
 * Two properties are worth more than the rest, because getting either wrong
 * produces a plan the console cheerfully saves and the backend then refuses,
 * or worse, accepts and mis-fills:
 *
 * 1. **A moved anchor carries a new fingerprint.** `docx/fill.py::apply` calls
 *    `outline.verify(doc, path, entry["fingerprint"])` before it writes
 *    anything. An entry moved from `body[7]` to `body[6]` while still carrying
 *    body[7]'s fingerprint fails that check at generation time — long after the
 *    administrator has left the screen.
 * 2. **Nothing here mutates its input.** These run inside React state
 *    transitions; a function that edits the plan in place leaves the rendered
 *    chips describing a plan that is no longer the one held in state.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { Block } from "../../api/reads";
import {
  BINDABLE_FIELDS,
  acceptSuggestion,
  addInsert,
  bindToken,
  checkLiteral,
  clearTableMapping,
  entriesForBlock,
  fieldForLiteral,
  literalForField,
  maxHeaderRows,
  moveEntry,
  planProblems,
  rejectSuggestion,
  setTableMapping,
  tableMappingFor,
  tableMappingProblems,
  tablePreviewRows,
  tablePreviewTotal,
  updateBrief,
  usableSuggestions,
  type Plan,
  type Suggestion,
} from "./plan";

/** `Dashboard/src`, from which the backend is two levels up. */
const SRC = dirname(dirname(dirname(fileURLToPath(import.meta.url))));

/** A block outline shaped exactly like `docx/outline.py::parse` produces. */
function block(path: string, kind: Block["kind"], text: string, style = ""): Block {
  return {
    id: `b-${path}`,
    path,
    kind,
    style,
    level: kind === "heading" ? 1 : null,
    text,
    images: [],
    table:
      kind === "table"
        ? { rows: 3, cols: 2, header: ["Item", "Amount"], sample: [["Item", "Amount"]] }
        : null,
    fingerprint: `sha256:${path}`,
  };
}

// body[0] heading, body[1] paragraph, body[2] empty, body[3] paragraph,
// body[4] table, then a footer in its own container.
const BLOCKS: Block[] = [
  block("body[0]", "heading", "Our proposal"),
  block("body[1]", "paragraph", "We are pleased to present this programme.", "Body"),
  block("body[2]", "empty", ""),
  block("body[3]", "paragraph", "The programme runs across three terms.", "Body"),
  block("body[4]", "table", "Item | Amount"),
  block("sec[0]/ftr/body[0]", "paragraph", "Copyright 2026", "Footer"),
];

const EMPTY: Plan = { version: 1, entries: [] };

const GREETING: Suggestion = {
  kind: "insert",
  key: "greeting",
  after: "body[0]",
  style_ref: "body[1]",
  fingerprint: "sha256:body[0]",
  shape: "paragraph",
  brief: "Greet the school by name and say why we are writing.",
  max_words: 60,
  required: true,
  confidence: 0.82,
  why: "The document opens straight into the offering with no address to the reader.",
};

const CLIENT_TOKEN: Suggestion = {
  kind: "token",
  key: "client_name",
  literal: "School Name",
  confidence: 0.95,
  why: "Appears seven times and is plainly a stand-in.",
};

describe("accepting and rejecting a suggestion", () => {
  it("adds exactly one entry", () => {
    const next = acceptSuggestion(EMPTY, GREETING);
    expect(next.entries).toHaveLength(1);
    expect(next.entries[0].key).toBe("greeting");
    expect(next.entries[0].after).toBe("body[0]");
    expect(next.version).toBe(1);
  });

  it("does not duplicate when the same suggestion is accepted twice", () => {
    const once = acceptSuggestion(EMPTY, GREETING);
    const twice = acceptSuggestion(once, GREETING);
    expect(twice.entries).toHaveLength(1);
  });

  it("re-accepting replaces in place rather than appending at the end", () => {
    // Order is the document's order; a re-accept must not move a placeholder to
    // the bottom of the plan.
    const withBoth = acceptSuggestion(acceptSuggestion(EMPTY, GREETING), CLIENT_TOKEN);
    const again = acceptSuggestion(withBoth, { ...GREETING, max_words: 40 });
    expect(again.entries.map((e) => e.key)).toEqual(["greeting", "client_name"]);
    expect(again.entries[0].max_words).toBe(40);
  });

  it("leaves the model's reasoning out of the saved plan", () => {
    // `confidence` and `why` exist to help a human decide. The plan is the
    // contract with docx/fill.py, and it is stored on the row forever.
    const entry = acceptSuggestion(EMPTY, GREETING).entries[0] as Record<string, unknown>;
    expect(entry).not.toHaveProperty("confidence");
    expect(entry).not.toHaveProperty("why");
    expect(entry.brief).toBe(GREETING.brief);
  });

  it("removes the entry again when it is rejected", () => {
    const plan = acceptSuggestion(acceptSuggestion(EMPTY, GREETING), CLIENT_TOKEN);
    const next = rejectSuggestion(plan, "greeting");
    expect(next.entries.map((e) => e.key)).toEqual(["client_name"]);
  });

  it("says nothing and changes nothing when rejecting a key that is not there", () => {
    const plan = acceptSuggestion(EMPTY, GREETING);
    expect(rejectSuggestion(plan, "nobody").entries).toHaveLength(1);
  });
});

describe("rewording a brief", () => {
  it("changes only the named entry", () => {
    const plan = acceptSuggestion(acceptSuggestion(EMPTY, GREETING), {
      ...GREETING,
      key: "closing",
      after: "body[3]",
      fingerprint: "sha256:body[3]",
      brief: "Close by naming the next step.",
    });
    const next = updateBrief(plan, "closing", "Close by offering a date for a visit.");
    expect(next.entries[0].brief).toBe(GREETING.brief);
    expect(next.entries[1].brief).toBe("Close by offering a date for a visit.");
  });

  it("leaves the plan alone when the key is unknown", () => {
    const plan = acceptSuggestion(EMPTY, GREETING);
    expect(updateBrief(plan, "nobody", "…")).toBe(plan);
  });
});

describe("moving an entry", () => {
  const plan = acceptSuggestion(EMPTY, GREETING); // anchored after body[0]

  it("re-anchors to the next block", () => {
    const next = moveEntry(plan, "greeting", "down", BLOCKS);
    expect(next.entries[0].after).toBe("body[1]");
  });

  it("re-anchors to the previous block", () => {
    const down = moveEntry(plan, "greeting", "down", BLOCKS);
    const back = moveEntry(down, "greeting", "up", BLOCKS);
    expect(back.entries[0].after).toBe("body[0]");
  });

  it("carries the new anchor's fingerprint", () => {
    // Without this, docx/fill.py::apply raises AnchorError at generation time
    // against a plan this console saved as valid.
    const next = moveEntry(plan, "greeting", "down", BLOCKS);
    expect(next.entries[0].fingerprint).toBe("sha256:body[1]");
  });

  it("refuses to move past the top", () => {
    expect(moveEntry(plan, "greeting", "up", BLOCKS)).toBe(plan);
  });

  it("refuses to move past the bottom of its own container", () => {
    const atEnd = acceptSuggestion(EMPTY, {
      ...GREETING,
      after: "body[4]",
      fingerprint: "sha256:body[4]",
    });
    // body[4] is the last body block. The next block in the outline is in the
    // footer, and a greeting does not belong in the footer.
    expect(moveEntry(atEnd, "greeting", "down", BLOCKS)).toBe(atEnd);
  });

  it("moves a replace entry by its own path", () => {
    const plan2 = acceptSuggestion(EMPTY, {
      kind: "replace",
      key: "summary",
      path: "body[3]",
      fingerprint: "sha256:body[3]",
      brief: "Summarise what the school asked for.",
    });
    const next = moveEntry(plan2, "summary", "up", BLOCKS);
    expect(next.entries[0].path).toBe("body[2]");
    expect(next.entries[0].fingerprint).toBe("sha256:body[2]");
  });

  it("leaves an entry with no anchor where it is", () => {
    // A token is replaced everywhere it appears; it has no position to move.
    const plan2 = acceptSuggestion(EMPTY, CLIENT_TOKEN);
    expect(moveEntry(plan2, "client_name", "down", BLOCKS)).toBe(plan2);
  });

  it("leaves a table binding alone, since only a table can hold one", () => {
    const plan2 = acceptSuggestion(EMPTY, {
      kind: "table",
      key: "pricing",
      path: "body[4]",
      fingerprint: "sha256:body[4]",
      columns: [{ col: 0, field: "label" }],
      header_rows: 1,
    });
    expect(moveEntry(plan2, "pricing", "up", BLOCKS)).toBe(plan2);
  });
});

describe("adding a placeholder by hand", () => {
  it("picks the nearest preceding paragraph as the style reference", () => {
    // body[2] is empty and body[0] is a heading, so the answer is body[1].
    const next = addInsert(EMPTY, "body[2]", null, BLOCKS);
    const entry = next.entries[0];
    expect(entry.kind).toBe("insert");
    expect(entry.after).toBe("body[2]");
    expect(entry.style_ref).toBe("body[1]");
    expect(entry.fingerprint).toBe("sha256:body[2]");
  });

  it("uses the anchor itself when the anchor is a paragraph", () => {
    expect(addInsert(EMPTY, "body[3]", null, BLOCKS).entries[0].style_ref).toBe("body[3]");
  });

  it("honours a style reference the caller chose", () => {
    expect(addInsert(EMPTY, "body[3]", "body[1]", BLOCKS).entries[0].style_ref).toBe(
      "body[1]",
    );
  });

  it("fails clearly when there is no paragraph to copy formatting from", () => {
    const headingOnly = [BLOCKS[0]];
    expect(() => addInsert(EMPTY, "body[0]", null, headingOnly)).toThrow(
      /no ordinary paragraph before/i,
    );
  });

  it("fails clearly when the anchor is not a block in this document", () => {
    expect(() => addInsert(EMPTY, "body[99]", null, BLOCKS)).toThrow(/body\[99\]/);
  });

  it("gives each new placeholder a key of its own", () => {
    const one = addInsert(EMPTY, "body[1]", null, BLOCKS);
    const two = addInsert(one, "body[3]", null, BLOCKS);
    const keys = two.entries.map((e) => e.key);
    expect(new Set(keys).size).toBe(2);
    expect(keys[0]).toMatch(/^insert_/);
  });
});

describe("what is anchored at a block", () => {
  it("returns the entries anchored there, in plan order", () => {
    const plan: Plan = {
      version: 1,
      entries: [
        { kind: "insert", key: "a", after: "body[1]" },
        { kind: "token", key: "client_name", literal: "School Name" },
        { kind: "insert", key: "b", before: "body[1]" },
        { kind: "replace", key: "c", path: "body[1]" },
        { kind: "insert", key: "d", after: "body[3]" },
      ],
    };
    expect(entriesForBlock(plan, "body[1]").map((e) => e.key)).toEqual(["a", "b", "c"]);
    expect(entriesForBlock(plan, "body[3]").map((e) => e.key)).toEqual(["d"]);
    expect(entriesForBlock(plan, "body[0]")).toEqual([]);
  });
});

describe("nothing here edits the plan it was given", () => {
  // These run inside React state transitions. A function that mutates would
  // leave the rendered chips describing a plan that is no longer in state.
  const plan = acceptSuggestion(acceptSuggestion(EMPTY, GREETING), CLIENT_TOKEN);
  const before = JSON.stringify(plan);

  it.each([
    ["acceptSuggestion", () => acceptSuggestion(plan, { ...GREETING, brief: "x" })],
    ["rejectSuggestion", () => rejectSuggestion(plan, "greeting")],
    ["updateBrief", () => updateBrief(plan, "greeting", "x")],
    ["moveEntry", () => moveEntry(plan, "greeting", "down", BLOCKS)],
    ["addInsert", () => addInsert(plan, "body[3]", null, BLOCKS)],
  ])("%s", (_name, run) => {
    run();
    expect(JSON.stringify(plan)).toBe(before);
  });
});

describe("suggestions the editor can place", () => {
  const reply = {
    suggestions: [
      GREETING,
      CLIENT_TOKEN,
      { kind: "insert", key: "ghost", after: "body[99]", style_ref: "body[1]" },
      { kind: "insert", key: "no-style", after: "body[1]", style_ref: "body[99]" },
      { kind: "table", key: "pricing", path: "body[4]", columns: [] },
      { kind: "table", key: "not-here", path: "body[42]" },
      { kind: "token", key: "blank", literal: "   " },
      { kind: "elsewhere", key: "wrong-kind" },
      { key: "no-kind" },
      { kind: "token", key: "client_name", literal: "School Name" },
      null,
    ],
  };

  it("keeps the ones anchored in this document", () => {
    expect(usableSuggestions(reply, BLOCKS).map((s) => s.key)).toEqual([
      "greeting",
      "client_name",
      "pricing",
    ]);
  });

  it("survives a reply that is not the shape it expects", () => {
    expect(usableSuggestions(null, BLOCKS)).toEqual([]);
    expect(usableSuggestions({}, BLOCKS)).toEqual([]);
    expect(usableSuggestions({ suggestions: "no" }, BLOCKS)).toEqual([]);
  });
});

describe("reading back what the backend refused", () => {
  it("splits the joined refusal into one line per problem", () => {
    expect(
      planProblems(
        "This plan does not match the document: entry 1 ('greeting'): " +
          "'body[999]' is not a block in this document; entry 2: has no key",
      ),
    ).toEqual([
      "entry 1 ('greeting'): 'body[999]' is not a block in this document",
      "entry 2: has no key",
    ]);
  });

  it("passes a message it does not recognise through whole", () => {
    // Chopping an unrelated message at its semicolons would invent problems
    // the server never reported.
    expect(planProblems("You do not have permission; ask an administrator.")).toEqual([
      "You do not have permission; ask an administrator.",
    ]);
    expect(planProblems("")).toEqual([]);
  });
});

/* ── Task 21: token binding and the rate-card table mapping ───────────────── */

describe("binding a literal to a field", () => {
  it("adds a token entry keyed by the field", () => {
    const next = bindToken(EMPTY, "School Name", "client_name");
    expect(next.entries).toEqual([
      { kind: "token", key: "client_name", literal: "School Name" },
    ]);
  });

  it("unbinds when the field is cleared", () => {
    const bound = bindToken(EMPTY, "School Name", "client_name");
    expect(bindToken(bound, "School Name", "").entries).toEqual([]);
  });

  it("rebinds a literal in place rather than appending", () => {
    const plan = bindToken(
      bindToken(EMPTY, "School Name", "client_name"),
      "Head Teacher",
      "contact_name",
    );
    const next = bindToken(plan, "School Name", "org_name");
    expect(next.entries.map((e) => e.key)).toEqual(["org_name", "contact_name"]);
    expect(next.entries[0].literal).toBe("School Name");
  });

  it("moves a field off whatever literal held it, because a key is unique", () => {
    // Two entries keyed client_name is what validate_plan refuses with
    // "'client_name' is used more than once". The panel cannot offer a state
    // the backend will not store.
    const plan = bindToken(EMPTY, "School Name", "client_name");
    const next = bindToken(plan, "Client Name", "client_name");
    expect(next.entries).toHaveLength(1);
    expect(next.entries[0].literal).toBe("Client Name");
  });

  it("reads back which field a literal holds, and which literal holds a field", () => {
    const plan = bindToken(EMPTY, "School Name", "client_name");
    expect(fieldForLiteral(plan, "School Name")).toBe("client_name");
    expect(fieldForLiteral(plan, "Nothing")).toBeNull();
    expect(literalForField(plan, "client_name")).toBe("School Name");
    expect(literalForField(plan, "org_name")).toBeNull();
  });

  it("leaves every other kind of entry alone", () => {
    const plan = acceptSuggestion(EMPTY, GREETING);
    const next = bindToken(plan, "School Name", "client_name");
    expect(next.entries.map((e) => e.key)).toEqual(["greeting", "client_name"]);
  });

  it("offers only fields the backend can actually resolve", () => {
    // build_docx_content does values[entry.key] = variables.get(entry.key), so
    // a key absent from that dict resolves to None and leaves the literal
    // standing in the client's document. This is the one place the two
    // languages agree by hand, so it is checked against the source itself.
    const source = readFileSync(
      join(SRC, "..", "..", "app", "services", "proposal_service.py"),
      "utf-8",
    );
    const block = source.slice(source.indexOf("variables: dict[str, Any] = {"));
    const known = new Set(
      [...block.slice(0, block.indexOf("\n    }")).matchAll(/^\s{8}"([a-z_]+)":/gm)].map(
        (m) => m[1],
      ),
    );
    expect(known.size, "did not parse the variables dict").toBeGreaterThan(8);
    expect(BINDABLE_FIELDS.filter((f) => !known.has(f))).toEqual([]);
  });
});

describe("checking a literal the detector missed", () => {
  it("finds one that is in the document, and counts it", () => {
    expect(checkLiteral("programme", BLOCKS)).toEqual({
      verdict: "found",
      occurrences: 2,
    });
  });

  it("looks inside a table's sample rows, not only its header", () => {
    const withCells: Block[] = [
      {
        ...BLOCKS[4],
        table: {
          rows: 2,
          cols: 2,
          header: ["Item", "Amount"],
          sample: [
            ["Item", "Amount"],
            ["<Client> licence", "0"],
          ],
        },
      },
    ];
    expect(checkLiteral("<Client>", withCells).verdict).toBe("found");
  });

  it("says plainly when it is not there", () => {
    expect(checkLiteral("Nowhere In Here", BLOCKS)).toEqual({
      verdict: "not-found",
      occurrences: 0,
    });
  });

  it("refuses a literal too slight to be a stand-in", () => {
    // docx_suggest guards the model's literals this way; nothing guarded a
    // typed one. Measured there: a literal of a single space was accepted and
    // would have rewritten 533 occurrences in Essential Lab.docx, and "e" 369.
    // Replacement is global and runs over headers and footers too, so one
    // acceptance corrupts the whole file.
    expect(checkLiteral(" ", BLOCKS).verdict).toBe("too-slight");
    expect(checkLiteral("e", BLOCKS).verdict).toBe("too-slight");
    expect(checkLiteral("1234", BLOCKS).verdict).toBe("too-slight");
    expect(checkLiteral("", BLOCKS).verdict).toBe("too-slight");
  });
});

describe("mapping a table to the rate card", () => {
  const TABLE: Block = {
    ...BLOCKS[4],
    table: {
      rows: 5,
      cols: 4,
      header: ["Item", "Unit", "Unit price", "Amount"],
      sample: [["Item", "Unit", "Unit price", "Amount"]],
    },
  };
  const MAPPING = {
    columns: [
      { col: 0, field: "label" },
      { col: 1, field: "unit" },
      { col: 2, field: "unit_price" },
      { col: 3, field: "line_total" },
    ],
    header_rows: 1,
    total_row: { label_col: 0, value_col: 3 },
  };

  it("stores an entry carrying the block's fingerprint", () => {
    // fill.py::apply verifies a table entry's fingerprint along with every
    // other structural entry, before it writes anything.
    const next = setTableMapping(EMPTY, TABLE, MAPPING);
    expect(next.entries[0]).toMatchObject({
      kind: "table",
      path: TABLE.path,
      fingerprint: TABLE.fingerprint,
      header_rows: 1,
    });
    expect(next.entries[0].key).toMatch(/^pricing_/);
  });

  it("keeps the key when the mapping is edited again", () => {
    const once = setTableMapping(EMPTY, TABLE, MAPPING);
    const twice = setTableMapping(once, TABLE, { ...MAPPING, header_rows: 2 });
    expect(twice.entries).toHaveLength(1);
    expect(twice.entries[0].key).toBe(once.entries[0].key);
    expect(twice.entries[0].header_rows).toBe(2);
  });

  it("reads the mapping back", () => {
    const plan = setTableMapping(EMPTY, TABLE, MAPPING);
    expect(tableMappingFor(plan, TABLE.path)).toEqual(MAPPING);
    expect(tableMappingFor(plan, "body[0]")).toBeNull();
  });

  it("clears it", () => {
    const plan = setTableMapping(EMPTY, TABLE, MAPPING);
    expect(clearTableMapping(plan, TABLE.path).entries).toEqual([]);
  });

  it("knows how many header rows the table can spare", () => {
    // edit.py::fill_table clones the first BODY row as its template and raises
    // AnchorError when there is none. validate_plan does not check this, so it
    // would otherwise surface at proposal time against a saved plan.
    expect(maxHeaderRows(5, true)).toBe(3);
    expect(maxHeaderRows(5, false)).toBe(4);
    expect(maxHeaderRows(2, true)).toBe(0);
    expect(maxHeaderRows(1, true)).toBe(-1);
    expect(maxHeaderRows(1, false)).toBe(0);
  });

  it("reports the mappings the backend would refuse or mis-fill", () => {
    expect(tableMappingProblems({ ...MAPPING, columns: [] }, TABLE)).toEqual([
      "Map at least one column to a rate-card field.",
    ]);
    expect(
      tableMappingProblems(
        {
          ...MAPPING,
          columns: [
            { col: 0, field: "label" },
            { col: 1, field: "label" },
          ],
        },
        TABLE,
      ),
    ).toEqual(["The rate-card field “label” is mapped to two columns."]);
    expect(tableMappingProblems({ ...MAPPING, header_rows: 4 }, TABLE)).toEqual([
      "This table has 5 rows and a total row, so at most 3 can be header rows — " +
        "otherwise there is no body row left to copy the styling from.",
    ]);
    expect(
      tableMappingProblems({ ...MAPPING, total_row: { label_col: 0, value_col: 9 } }, TABLE),
    ).toEqual(["The total's value column must be one of this table's 4 columns."]);
    expect(tableMappingProblems(MAPPING, TABLE)).toEqual([]);
  });

  it("previews the mapping, blanking every column it does not map", () => {
    // Not cosmetic: fill_table writes "" into every cell whose column is not in
    // `columns`, so an unmapped column is EMPTIED in each generated row rather
    // than left as it was.
    const rows = tablePreviewRows(
      { ...MAPPING, columns: MAPPING.columns.slice(0, 2) },
      TABLE,
    );
    expect(rows).toEqual([
      ["Robotics lab setup", "per lab", "", ""],
      ["Teacher training", "per teacher", "", ""],
    ]);
  });

  it("sums the same two items it previews", () => {
    // The dialog shows a total row beside the sample rows. If the constant and
    // the items ever drift apart, the preview quietly lies about arithmetic on
    // a screen whose whole job is showing that the mapping is right.
    const totals = tablePreviewRows(
      { ...MAPPING, columns: [{ col: 0, field: "line_total" }] },
      TABLE,
    ).map((r) => Number(r[0].replace(/,/g, "")));
    const sum = totals.reduce((a, b) => a + b, 0);
    expect(tablePreviewTotal()).toBe(sum.toLocaleString("en-US"));
    expect(tablePreviewTotal()).toBe("282,000");
  });

  it("formats each field the way the backend does", () => {
    expect(tablePreviewRows(MAPPING, TABLE)).toEqual([
      ["Robotics lab setup", "per lab", "120,000", "240,000"],
      ["Teacher training", "per teacher", "3,500", "42,000"],
    ]);
    // quantity goes through str(int(float(...))) — never "2.0".
    const withQuantity = { ...MAPPING, columns: [{ col: 0, field: "quantity" }] };
    expect(tablePreviewRows(withQuantity, TABLE)[0][0]).toBe("2");
  });
});
