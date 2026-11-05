/**
 * Which flow a template version uses, and the words for each (Task B3).
 *
 * Pure, so it is tested here rather than through a screen this suite
 * deliberately does not render (D11, no component tests). Everything in this
 * file is a decision the administrator sees in plain language, and every one
 * of them is wrong in a way a type checker cannot catch: the wrong `flow` on
 * the request, a `docx_simple` version that reads as "0 characters" in the
 * history, or a success panel that offers an editor the simple flow does not
 * have.
 */

/** The `flow` form field `POST .../proposal-templates/docx` expects. */
export type TemplateFlow = "simple" | "complex";

/** What the administrator picks under "How this version is written". */
export type WriteMode = "simple" | "docx" | "markdown";

/**
 * Simple is first and is the default, which is the owner's decision: the
 * template author writes the placeholders and the administrator only uploads.
 * The flow that shipped first moves to second place rather than away.
 */
export const MODE_OPTIONS: { value: WriteMode; label: string }[] = [
  { value: "simple", label: "Word document — tags filled by the assistant" },
  { value: "docx", label: "Word document — placeholders marked here" },
  { value: "markdown", label: "Markdown body, written here" },
];

export const DEFAULT_MODE: WriteMode = "simple";

/** The flow to upload as, or null when this mode is not a document upload. */
export function flowOf(mode: WriteMode): TemplateFlow | null {
  if (mode === "simple") return "simple";
  if (mode === "docx") return "complex";
  return null;
}

/**
 * How a published version describes itself in the history.
 *
 * A `docx_simple` version must not fall through to the character count: a
 * document template's `body_md` is its projected plain text, so the old
 * `t.kind === "docx"` test would have shown a length for it and said nothing
 * about which flow produced it.
 */
export function kindLabel(kind: string, bodyLength: number): string {
  if (kind === "docx_simple") return "Word document · tags filled by the assistant";
  if (kind === "docx") return "Word document · placeholders marked here";
  return `${bodyLength} characters`;
}

/**
 * The stages an upload moves through, so the wait is legible rather than a
 * spinner. The simple flow does not read the images at upload — that is a
 * background job now (B2), which is why it has one stage fewer and is the
 * faster of the two by a factor of thirty.
 */
export function stagesFor(flow: TemplateFlow): string[] {
  if (flow === "simple") {
    return ["Reading the document", "Finding the tags", "Saving"];
  }
  return [
    "Reading the document",
    "Reading the text inside its images",
    "Saving",
  ];
}

export type DocumentType = "proposal" | "mou";

export const DOCUMENT_TYPE_OPTIONS: { value: DocumentType; label: string }[] = [
  { value: "proposal", label: "Proposal" },
  { value: "mou", label: "MOU (memorandum of understanding)" },
];

export const DEFAULT_DOCUMENT_TYPE: DocumentType = "proposal";

export type UploadResult = {
  doc_id: string;
  name: string;
  version: number;
  index_kind: string;
  blocks: number;
  flow?: string;
  tags?: number;
  always_asked?: number;
  distinct?: string[];
  document_type?: string;
  ruled_blanks?: number;
};

export function documentTypeLabel(t: string | undefined): string {
  return t === "mou" ? "MOU" : "Proposal";
}

/**
 * What kind of document a template is.
 *
 * A template published before this feature has no `document_type` key at all,
 * and everything published before it was a proposal -- so anything that is not
 * explicitly an MOU is one. Defaulting the other way would relabel every
 * template already in the database overnight.
 */
export function documentTypeOf(
  plan: { document_type?: string } | undefined,
): DocumentType {
  return plan?.document_type === "mou" ? "mou" : "proposal";
}

/**
 * An MOU is only ever filled by the assistant.
 *
 * The complex flow is an administrator marking placeholders up in this console
 * afterwards. A contract's author writes the tags into the Word file
 * themselves, and there is no MOU template of the other kind -- so the choice
 * is made here, where it can be explained, rather than refused by the upload.
 */
export function forcesSimpleFlow(t: DocumentType): boolean {
  return t === "mou";
}

/**
 * D-F. A ruled blank is `Date: ______` -- an underscore run the author meant
 * as a fill-in. It is NOT a tag, nothing will ever write into it, and it
 * reaches the client as underscores on a document they are asked to sign.
 *
 * A WARNING, never an error. The upload succeeded and the document is stored;
 * refusing it would leave the author with no template at all over something
 * only they can fix, in a file only they have.
 */
export function ruledBlankWarning(n: number | undefined): string | null {
  const count = n ?? 0;
  if (count <= 0) return null;
  return (
    `${count} ruled blank${count === 1 ? "" : "s"} (like "Date: ______") ` +
    `found. These are not tags and will reach the client as underscores. ` +
    `Replace each with a tag before using this template.`
  );
}

export function isSimple(result: UploadResult): boolean {
  return result.flow === "simple";
}

/**
 * What the success panel says. For the simple flow this IS the whole screen —
 * there is no editor and no next step — so it has to be enough on its own.
 *
 * It counts OCCURRENCES, not literals, because `<ask:1 Unit>` written into
 * four cells is four questions about four different items (D1). Saying "1 tag"
 * there would understate the conversation four-fold.
 */
export function successLines(result: UploadResult): string[] {
  if (!isSimple(result)) {
    return [
      `${result.blocks} blocks were read from the document.`,
      "Mark where the system should fill things in next.",
    ];
  }
  const tags = result.tags ?? 0;
  const asked = result.always_asked ?? 0;
  const distinct = result.distinct ?? [];
  const lines = [
    `${tags} ${tags === 1 ? "tag" : "tags"} found, ` +
      `${distinct.length} distinct.`,
  ];
  lines.push(
    asked === 0
      ? "The assistant will fill every one of them from what it knows about the client."
      : `${asked} of them will always be asked about, whatever the assistant works out.`,
  );
  lines.push(
    "Nothing else to do here. The assistant fills this document when a " +
      "salesperson asks for a proposal, and checks every value with them first.",
  );
  return lines;
}
