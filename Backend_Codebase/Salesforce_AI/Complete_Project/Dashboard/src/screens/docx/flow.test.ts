import { describe, expect, it } from "vitest";

import {
  DEFAULT_MODE,
  MODE_OPTIONS,
  documentTypeLabel,
  documentTypeOf,
  flowOf,
  forcesSimpleFlow,
  isSimple,
  kindLabel,
  ruledBlankWarning,
  stagesFor,
  successLines,
  type UploadResult,
} from "./flow";

const simple: UploadResult = {
  doc_id: "d1",
  name: "Innovation Lab",
  version: 1,
  index_kind: "none",
  blocks: 147,
  flow: "simple",
  tags: 25,
  always_asked: 19,
  distinct: ["<School Name>", "<ask:1 Unit>"],
};

const complex: UploadResult = {
  doc_id: "d2",
  name: "Essential Lab",
  version: 1,
  index_kind: "none",
  blocks: 105,
  flow: "complex",
  tags: 0,
  always_asked: 0,
  distinct: [],
};

describe("which flow a version uses", () => {
  it("offers the assistant-filled flow first and defaults to it", () => {
    expect(DEFAULT_MODE).toBe("simple");
    expect(MODE_OPTIONS[0].value).toBe("simple");
    expect(MODE_OPTIONS.map((o) => o.value)).toEqual([
      "simple",
      "docx",
      "markdown",
    ]);
  });

  it("sends `complex` for the flow the console calls `docx`", () => {
    // The screen's own vocabulary predates the feature; the wire word does not.
    expect(flowOf("docx")).toBe("complex");
    expect(flowOf("simple")).toBe("simple");
  });

  it("uploads nothing for a markdown body", () => {
    expect(flowOf("markdown")).toBeNull();
  });
});

describe("what a published version says about itself", () => {
  it("tells the two document flows apart", () => {
    expect(kindLabel("docx_simple", 0)).toContain("tags filled by the assistant");
    expect(kindLabel("docx", 0)).toContain("placeholders marked here");
  });

  it("never describes a document template by its character count", () => {
    // body_md for a docx template is its projected plain text, so the old
    // `kind === "docx"` test would have shown a length for a simple one.
    expect(kindLabel("docx_simple", 2986)).not.toContain("characters");
  });

  it("still counts characters for a markdown body", () => {
    expect(kindLabel("markdown", 1200)).toBe("1200 characters");
  });
});

describe("the wait", () => {
  it("says it is finding tags, not reading images, on the simple flow", () => {
    const stages = stagesFor("simple");
    expect(stages).toContain("Finding the tags");
    expect(stages.join(" ")).not.toContain("images");
  });

  it("still says it is reading the images on the complex flow", () => {
    // The complex flow still OCRs inline at upload, so its wait is real.
    expect(stagesFor("complex").join(" ")).toContain("images");
  });
});

describe("the success panel", () => {
  it("counts occurrences and distinct literals separately", () => {
    // 25 occurrences of 20 distinct literals in the owner's real template:
    // saying "2 tags" for this fixture would understate the conversation.
    expect(successLines(simple)[0]).toBe("25 tags found, 2 distinct.");
  });

  it("says how many will always be asked about", () => {
    expect(successLines(simple)[1]).toContain("19 of them will always be asked");
  });

  it("says there is nothing else to do", () => {
    // No editor and no next step is the whole point of the simple flow.
    expect(successLines(simple).join(" ")).toContain("Nothing else to do here");
  });

  it("does not claim questions when every tag is semantic", () => {
    const lines = successLines({ ...simple, always_asked: 0 });
    expect(lines[1]).toContain("fill every one of them");
    expect(lines[1]).not.toContain("0 of them");
  });

  it("says one tag rather than 1 tags", () => {
    expect(successLines({ ...simple, tags: 1, distinct: ["<Name>"] })[0]).toBe(
      "1 tag found, 1 distinct.",
    );
  });

  it("still points the complex flow at the editor", () => {
    expect(successLines(complex)).toEqual([
      "105 blocks were read from the document.",
      "Mark where the system should fill things in next.",
    ]);
  });

  it("treats a template uploaded before this feature as complex", () => {
    // No `flow` key at all: every version published before the simple flow.
    const legacy = { ...complex, flow: undefined };
    expect(isSimple(legacy)).toBe(false);
    expect(successLines(legacy)[1]).toContain("Mark where");
  });
});

describe("what kind of document a template is", () => {
  it("reads a template published before this feature as a proposal", () => {
    // No `document_type` key at all, which is every template in the database
    // before U2. Defaulting the other way would relabel all of them.
    expect(documentTypeOf(undefined)).toBe("proposal");
    expect(documentTypeOf({})).toBe("proposal");
    expect(documentTypeOf({ document_type: "proposal" })).toBe("proposal");
  });

  it("reads an MOU as an MOU", () => {
    expect(documentTypeOf({ document_type: "mou" })).toBe("mou");
  });

  it("names it the way an administrator would say it", () => {
    expect(documentTypeLabel("mou")).toBe("MOU");
    expect(documentTypeLabel("proposal")).toBe("Proposal");
    expect(documentTypeLabel(undefined)).toBe("Proposal");
  });

  it("settles the flow for an MOU and leaves a proposal's alone", () => {
    // A contract's author writes the tags into the Word file themselves;
    // there is no MOU template an administrator marks up afterwards.
    expect(forcesSimpleFlow("mou")).toBe(true);
    expect(forcesSimpleFlow("proposal")).toBe(false);
  });
});

describe("the ruled-blank warning (D-F)", () => {
  it("says nothing when there are none", () => {
    expect(ruledBlankWarning(0)).toBeNull();
    // The backend omits the key entirely for a complex-flow upload.
    expect(ruledBlankWarning(undefined)).toBeNull();
  });

  it("is singular at one and plural above it", () => {
    expect(ruledBlankWarning(1)).toContain("1 ruled blank ");
    expect(ruledBlankWarning(1)).not.toContain("blanks");
    expect(ruledBlankWarning(2)).toContain("2 ruled blanks ");
  });

  it("says what will happen rather than only what was found", () => {
    // An administrator who is told "2 ruled blanks" and nothing else has no
    // reason to act. The consequence is the part that makes them fix it.
    const message = ruledBlankWarning(2) ?? "";
    expect(message).toContain("underscores");
    expect(message).toContain("Replace each with a tag");
  });
});
