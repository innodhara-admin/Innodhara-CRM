/**
 * Upload a Word document as a proposal template version.
 *
 * The document is stored as it is and never re-rendered. Everything that makes
 * it look like the organisation's own — the cover, the images, the headers and
 * footers, the styled tables — survives because nothing here rebuilds it; a
 * proposal is `source.docx + plan + values -> a new file`.
 *
 * The size guard is checked before the request rather than after, because a
 * 25 MB upload that is going to be refused should not be sent over a school's
 * connection first.
 */
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { request } from "../../api/client";
import { endpoints } from "../../api/endpoints";
import { asApiError } from "../../ui/ItemScreen";
import { Banner, Button, Field, TextInput, styles as s } from "../../ui/primitives";
import {
  isSimple,
  stagesFor,
  successLines,
  type TemplateFlow,
  type UploadResult,
  ruledBlankWarning,
  type DocumentType,
} from "./flow";

/** Mirrors `docx_template_service.MAX_UPLOAD_BYTES`. */
const MAX_BYTES = 25 * 1024 * 1024;

/** What the backend detected, said in words an administrator can act on. */
const INDEX_NOTE: Record<string, string> = {
  static:
    "This document's contents page is plain text, so its page numbers are " +
    "refreshed when a proposal is produced.",
  field:
    "This document has a Word contents field; Word will refresh it when the " +
    "file is opened.",
  none: "",
};

/**
 * The wait, said in stages rather than shown as a spinner.
 *
 * Nothing here knows which stage the server is really on -- an upload is
 * one request -- so the labels advance on a timer. They are honest about
 * WHAT happens and in what order, which is what an administrator watching
 * a ten-second complex upload actually wants to know.
 */
function Stages({ stages, at }: { stages: string[]; at: number }) {
  return (
    <ol
      className={s.muted}
      style={{
        fontSize: "var(--text-xs)",
        margin: "var(--s2) 0 0",
        paddingInlineStart: "var(--s4)",
      }}
    >
      {stages.map((label, i) => (
        <li key={label} style={{ opacity: i <= at ? 1 : 0.5 }}>
          {i < at ? `${label} — done` : i === at ? `${label}…` : label}
        </li>
      ))}
    </ol>
  );
}

export function DocxUpload({
  programId,
  flow,
  documentType,
  onUploaded,
}: {
  programId: string;
  flow: TemplateFlow;
  documentType: DocumentType;
  onUploaded?: (docId: string) => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [stage, setStage] = useState(0);

  useEffect(() => {
    if (!busy) {
      setStage(0);
      return;
    }
    const last = stagesFor(flow).length - 1;
    const timer = setInterval(
      () => setStage((n) => Math.min(n + 1, last)),
      900,
    );
    return () => clearInterval(timer);
  }, [busy, flow]);

  const tooBig = file !== null && file.size > MAX_BYTES;
  const wrongType = file !== null && !file.name.toLowerCase().endsWith(".docx");
  const ready = name.trim().length > 0 && file !== null && !tooBig && !wrongType;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready || file === null) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("make_current", "true");
      form.append("flow", flow);
      form.append("document_type", documentType);
      form.append("file", file);
      const reply = (await request(endpoints.proposalTemplatesDocx(programId), {
        as: "org",
        method: "POST",
        body: form,
      })) as UploadResult;
      setResult(reply);
      setName("");
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await queryClient.invalidateQueries({ queryKey: ["proposalTemplates"] });
      onUploaded?.(reply.doc_id);
    } catch (err) {
      // The backend's own message is already written for a human.
      setError(asApiError(err)?.detail ?? String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <Field label="Name" htmlFor="docx-name" caption="versions are numbered per name, so reusing a name supersedes that family">
        <TextInput
          id="docx-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Standard commissioning"
        />
      </Field>

      <Field
        label="Word document"
        htmlFor="docx-file"
        caption="a .docx saved from Word or Google Docs, up to 25 MB"
      >
        <input
          id="docx-file"
          ref={fileInput}
          type="file"
          accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setError(null);
            setResult(null);
          }}
        />
      </Field>

      {file && (
        <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s1) 0 0" }}>
          {`${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB`}
        </p>
      )}

      {wrongType && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="blocked" title="That is not a Word document">
            <p style={{ margin: 0 }}>
              Choose a .docx file. A .doc or a PDF cannot be filled in, because
              the placeholders are written into the document's own structure.
            </p>
          </Banner>
        </div>
      )}

      {tooBig && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="blocked" title="That file is larger than 25 MB">
            <p style={{ margin: 0 }}>
              {`${(file!.size / (1024 * 1024)).toFixed(1)} MB. Compress the images in ` +
                "Word (Picture Format → Compress Pictures) and upload it again."}
            </p>
          </Banner>
        </div>
      )}

      <div style={{ marginBlockStart: "var(--s4)" }}>
        <Button type="submit" variant="primary" disabled={!ready || busy}>
          {busy ? "Uploading…" : "Upload and publish"}
        </Button>
      </div>

      {result !== null && ruledBlankWarning(result.ruled_blanks) !== null && (
        <p
          role="status"
          style={{
            marginTop: 8,
            padding: "8px 10px",
            borderRadius: 6,
            background: "#fff8e1",
            border: "1px solid #ffe082",
            color: "#5d4037",
          }}
        >
          {ruledBlankWarning(result.ruled_blanks)}
        </p>
      )}
      {busy && <Stages stages={stagesFor(flow)} at={stage} />}

      {error && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="blocked" title="That document could not be used" serverMessage={error} />
        </div>
      )}

      {result && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="note" title={`“${result.name}” v${result.version} is published`}>
            {successLines(result).map((line) => (
              <p key={line} style={{ margin: "var(--s1) 0 0" }}>
                {line}
              </p>
            ))}
            {isSimple(result) && (result.distinct ?? []).length > 0 && (
              <p
                className={s.mono}
                style={{ fontSize: "var(--text-xs)", margin: "var(--s2) 0 0" }}
              >
                {(result.distinct ?? []).join("  ")}
              </p>
            )}
            {INDEX_NOTE[result.index_kind] && (
              <p style={{ margin: "var(--s2) 0 0" }}>{INDEX_NOTE[result.index_kind]}</p>
            )}
            {/* The document is published either way; until placeholders are
                marked, a proposal built from it is the document verbatim, with
                the client's own details still absent. */}
            {/* No editor for a simple template: its placeholders were
                written by whoever wrote the document, and the assistant
                fills them at proposal time. There is no next step. */}
            {!isSimple(result) && (
              <div style={{ marginBlockStart: "var(--s3)" }}>
                <Button
                  variant="primary"
                  onClick={() => navigate(`/item/6/doc/${result.doc_id}`)}
                >
                  Mark the placeholders
                </Button>
              </div>
            )}
          </Banner>
        </div>
      )}
    </form>
  );
}
