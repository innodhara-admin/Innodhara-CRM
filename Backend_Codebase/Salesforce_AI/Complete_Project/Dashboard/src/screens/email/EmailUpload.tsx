/**
 * Upload a Word email template (28 Oct 2026, spec section 7).
 *
 * A common email picks a category, a product email picks a product and,
 * optionally, the client's built proposal or MoU to carry. The Word file's
 * first line is the subject (`Subject: ...`); its blanks are tags in the same
 * style as the proposal templates. Default attachments are added on the list
 * below once the template exists, so a failed upload never leaves files behind.
 */
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "../../api/client";
import { endpoints } from "../../api/endpoints";
import { EmailCategoriesRead, ProgramsRead, type EmailTemplate } from "../../api/reads";
import { asApiError } from "../../ui/ItemScreen";
import { Banner, Button, Field, Select, TextInput, styles as s } from "../../ui/primitives";
import {
  BUILT_OPTIONS,
  TYPE_OPTIONS,
  validateUpload,
  type BuiltDocument,
  type TemplateType,
} from "./email";

const OWN_CATEGORY = "__own__";

export function EmailUpload() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [templateType, setTemplateType] = useState<TemplateType>("common");
  const [category, setCategory] = useState("follow_up");
  const [ownCategory, setOwnCategory] = useState("");
  const [programId, setProgramId] = useState("");
  const [name, setName] = useState("");
  const [whenToUse, setWhenToUse] = useState("");
  const [builtDocument, setBuiltDocument] = useState<BuiltDocument>("none");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EmailTemplate | null>(null);

  const categories = useQuery({
    queryKey: ["emailCategories"],
    queryFn: () => request(endpoints.emailCategories, { as: "org", shape: EmailCategoriesRead }),
  });
  const programs = useQuery({
    queryKey: ["programs"],
    queryFn: () => request(endpoints.programs, { as: "org", shape: ProgramsRead }),
  });
  const products = (programs.data ?? []).filter((p) => p.is_active);

  const chosenCategory = category === OWN_CATEGORY ? ownCategory : category;
  const problem = validateUpload({
    templateType,
    category: templateType === "common" ? chosenCategory : "",
    programId: templateType === "product" ? programId : "",
    name,
    builtDocument: templateType === "product" ? builtDocument : "none",
    file: file === null ? null : { name: file.name, size: file.size },
  });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (problem !== null || file === null) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append("template_type", templateType);
      form.append("name", name.trim());
      if (whenToUse.trim()) form.append("when_to_use", whenToUse.trim());
      if (templateType === "common") {
        form.append("category", chosenCategory.trim());
      } else {
        form.append("program_id", programId);
        form.append("built_document", builtDocument);
      }
      form.append("file", file);
      const reply = (await request(endpoints.emailTemplates, {
        as: "org",
        method: "POST",
        body: form,
      })) as EmailTemplate;
      setResult(reply);
      setName("");
      setWhenToUse("");
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await queryClient.invalidateQueries({ queryKey: ["emailTemplates"] });
      await queryClient.invalidateQueries({ queryKey: ["emailCategories"] });
    } catch (err) {
      setError(asApiError(err)?.detail ?? String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <Field label="Type" htmlFor="email-type">
        <Select
          id="email-type"
          options={TYPE_OPTIONS}
          value={templateType}
          onChange={(e) => setTemplateType(e.target.value as TemplateType)}
        />
      </Field>

      {templateType === "common" ? (
        <Field label="Category" htmlFor="email-category" caption="common emails are grouped by category">
          <Select
            id="email-category"
            options={[
              ...(categories.data ?? []).map((c) => ({ value: c.key, label: c.label })),
              { value: OWN_CATEGORY, label: "Add your own…" },
            ]}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
          {category === OWN_CATEGORY && (
            <TextInput
              id="email-own-category"
              value={ownCategory}
              onChange={(e) => setOwnCategory(e.target.value)}
              placeholder="Exam season note"
            />
          )}
        </Field>
      ) : (
        <>
          <Field label="Product" htmlFor="email-product" caption="product emails are grouped by product">
            <Select
              id="email-product"
              placeholder="Choose a product"
              options={products.map((p) => ({ value: p.id, label: `${p.code} · ${p.name}` }))}
              value={programId}
              onChange={(e) => setProgramId(e.target.value)}
            />
          </Field>
          <Field
            label="Also attach"
            htmlFor="email-built"
            caption="if the client has none built yet, Jarvis warns and does not send"
          >
            <Select
              id="email-built"
              options={BUILT_OPTIONS}
              value={builtDocument}
              onChange={(e) => setBuiltDocument(e.target.value as BuiltDocument)}
            />
          </Field>
        </>
      )}

      <Field label="Name" htmlFor="email-name" caption="versions are numbered per name; reusing a name replaces that one only">
        <TextInput
          id="email-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="No reply follow-up"
        />
      </Field>

      <Field label="When to use it" htmlFor="email-when" caption="one line; Jarvis reads it to pick the right email">
        <TextInput
          id="email-when"
          value={whenToUse}
          onChange={(e) => setWhenToUse(e.target.value)}
          placeholder="The client has not replied to our first email"
        />
      </Field>

      <Field
        label="Word document"
        htmlFor="email-file"
        caption="a .docx up to 10 MB; first line Subject: ..., blanks written as <School Name> or <ask:...>"
      >
        <input
          id="email-file"
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

      {problem !== null && (name || file) && (
        <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s2) 0 0" }}>
          {problem}
        </p>
      )}

      <div style={{ marginBlockStart: "var(--s4)" }}>
        <Button type="submit" variant="primary" disabled={problem !== null || busy}>
          {busy ? "Uploading…" : "Upload and publish"}
        </Button>
      </div>

      {error && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="blocked" title="That template could not be used" serverMessage={error} />
        </div>
      )}

      {result && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner
            tone={result.leftover_blanks.length ? "warn" : "note"}
            title={`“${result.name}” v${result.version} is published`}
          >
            <p style={{ margin: 0 }}>{`Subject: ${result.subject}`}</p>
            <p style={{ margin: "var(--s1) 0 0" }}>
              {`${result.tags} tag${result.tags === 1 ? "" : "s"} found, ` +
                `${result.always_asked} always asked. Add default attachments in the list below.`}
            </p>
            {result.leftover_blanks.length > 0 && (
              <p style={{ margin: "var(--s2) 0 0" }}>
                {`These blanks are not tags and will block every email made from it: ${result.leftover_blanks.join(", ")}. ` +
                  "Write them as tags, for example <School Name>, and upload it again."}
              </p>
            )}
          </Banner>
        </div>
      )}
    </form>
  );
}
