import { describe, expect, it } from "vitest";

import type { EmailTemplate } from "../../api/reads";
import {
  MAX_TEMPLATE_BYTES,
  groupLabel,
  groupTemplates,
  validateUpload,
  type UploadForm,
} from "./email";

const row = (over: Partial<EmailTemplate>): EmailTemplate => ({
  id: "t1",
  template_type: "common",
  category: "follow_up",
  category_label: "Follow-up",
  program_id: null,
  program_name: null,
  name: "No reply follow-up",
  when_to_use: null,
  version: 1,
  is_current: true,
  built_document: "none",
  subject: "Hello <School Name>",
  filename: "a.docx",
  tags: 7,
  always_asked: 1,
  distinct: [],
  leftover_blanks: [],
  attachments: [],
  ...over,
});

const file = (name: string, size = 1000) => ({ name, size });

const form = (over: Partial<UploadForm>): UploadForm => ({
  templateType: "common",
  category: "follow_up",
  programId: "",
  name: "No reply follow-up",
  builtDocument: "none",
  file: file("a.docx"),
  ...over,
});

describe("groupLabel", () => {
  it("names a common email by its category and a product email by its product", () => {
    expect(groupLabel(row({}))).toBe("Common · Follow-up");
    expect(
      groupLabel(row({ template_type: "product", category: null, category_label: null,
                       program_id: "p1", program_name: "IBC Program" })),
    ).toBe("Product · IBC Program");
  });
});

describe("groupTemplates", () => {
  it("puts common groups before product groups, current versions first", () => {
    const groups = groupTemplates([
      row({ id: "p", template_type: "product", category: null, category_label: null,
            program_id: "p1", program_name: "IBC Program" }),
      row({ id: "old", is_current: false, version: 1 }),
      row({ id: "new", version: 2 }),
      row({ id: "intro", category: "intro", category_label: "Intro" }),
    ]);
    expect(groups.map((g) => g.label)).toEqual([
      "Common · Follow-up",
      "Common · Intro",
      "Product · IBC Program",
    ]);
    expect(groups[0].rows.map((r) => r.id)).toEqual(["new", "old"]);
  });
});

describe("validateUpload", () => {
  it("accepts a complete common email", () => {
    expect(validateUpload(form({}))).toBeNull();
  });
  it("refuses a common email tied to a product", () => {
    expect(validateUpload(form({ programId: "p1" }))).toMatch(/product/i);
  });
  it("refuses a product email without a product", () => {
    expect(
      validateUpload(form({ templateType: "product", category: "" })),
    ).toMatch(/needs a product/);
  });
  it("refuses a common email without a category", () => {
    expect(validateUpload(form({ category: "  " }))).toMatch(/category/);
  });
  it("refuses a common email carrying a built document", () => {
    expect(validateUpload(form({ builtDocument: "proposal" }))).toMatch(/product email/);
  });
  it("refuses no file, the wrong type and a file that is too large", () => {
    expect(validateUpload(form({ file: null }))).toMatch(/Choose a Word file/);
    expect(validateUpload(form({ file: file("a.pdf") }))).toMatch(/\.docx/);
    expect(
      validateUpload(form({ file: file("a.docx", MAX_TEMPLATE_BYTES + 1) })),
    ).toMatch(/10 MB/);
  });
  it("refuses a missing name", () => {
    expect(validateUpload(form({ name: " " }))).toMatch(/name/);
  });
});
