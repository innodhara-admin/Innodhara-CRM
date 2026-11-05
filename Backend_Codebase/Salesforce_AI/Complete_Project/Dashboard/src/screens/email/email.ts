/**
 * Pure helpers for item 7's Word email templates (28 Oct 2026).
 *
 * The upload rules here mirror `email_template_service` word for word, so the
 * form says what is wrong before the round trip; the server still refuses on
 * its own if this ever drifts.
 */
import type { EmailTemplate } from "../../api/reads";

/** Mirrors `email_template_service.MAX_TEMPLATE_BYTES`. */
export const MAX_TEMPLATE_BYTES = 10 * 1024 * 1024;
/** Mirrors `email_template_service.MAX_ATTACHMENT_BYTES`. */
export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

export type TemplateType = "common" | "product";
export type BuiltDocument = "none" | "proposal" | "mou";

export const TYPE_OPTIONS = [
  { value: "common", label: "Common email (grouped by category)" },
  { value: "product", label: "Product email (grouped by product)" },
];

export const BUILT_OPTIONS = [
  { value: "none", label: "Nothing" },
  { value: "proposal", label: "The client's built proposal for this product" },
  { value: "mou", label: "The client's built MoU for this product" },
];

export const ATTACHMENT_ACCEPT = ".pdf,.docx,.doc,.pptx,.xlsx,.png,.jpg,.jpeg";

export type UploadForm = {
  templateType: TemplateType;
  category: string;
  programId: string;
  name: string;
  builtDocument: BuiltDocument;
  file: { name: string; size: number } | null;
};

/** The first thing wrong with the form, in the server's words, or null. */
export function validateUpload(form: UploadForm): string | null {
  if (!form.name.trim()) return "Give the template a name.";
  if (form.templateType === "common") {
    if (form.programId) {
      return "A common email does not belong to a product. Choose Product email to tie it to one.";
    }
    if (form.builtDocument !== "none") {
      return "Only a product email can carry the client's built proposal or MoU.";
    }
    if (!form.category.trim()) return "A common email needs a category.";
  } else if (!form.programId) {
    return "A product email needs a product.";
  }
  if (form.file === null) return "Choose a Word file (.docx).";
  if (!form.file.name.toLowerCase().endsWith(".docx")) {
    return "Upload a Word document (.docx). A .doc or a PDF cannot be filled in.";
  }
  if (form.file.size > MAX_TEMPLATE_BYTES) {
    return `That file is larger than ${MAX_TEMPLATE_BYTES / (1024 * 1024)} MB.`;
  }
  return null;
}

/** "Common · Follow-up" or "Product · IBC Program". */
export function groupLabel(t: EmailTemplate): string {
  if (t.template_type === "product") {
    return `Product · ${t.program_name ?? "a removed product"}`;
  }
  return `Common · ${t.category_label ?? t.category ?? "no category"}`;
}

/**
 * Templates grouped for the list: common groups first, then product groups,
 * each sorted by label; within a group, current versions first, then by name
 * and newest version.
 */
export function groupTemplates(rows: EmailTemplate[]): { label: string; rows: EmailTemplate[] }[] {
  const groups = new Map<string, EmailTemplate[]>();
  for (const row of rows) {
    const label = groupLabel(row);
    groups.set(label, [...(groups.get(label) ?? []), row]);
  }
  const rank = (label: string) => (label.startsWith("Common") ? 0 : 1);
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([label, items]) => ({
      label,
      rows: [...items].sort(
        (a, b) =>
          Number(b.is_current) - Number(a.is_current) ||
          a.name.localeCompare(b.name) ||
          b.version - a.version,
      ),
    }));
}

/** What the attachment cell says. */
export function attachmentsLabel(t: EmailTemplate): string {
  const files = t.attachments.length;
  const built =
    t.built_document === "proposal" ? "the built proposal" :
    t.built_document === "mou" ? "the built MoU" : "";
  const parts = [built, files ? `${files} file${files === 1 ? "" : "s"}` : ""].filter(Boolean);
  return parts.length ? parts.join(" + ") : "none";
}
