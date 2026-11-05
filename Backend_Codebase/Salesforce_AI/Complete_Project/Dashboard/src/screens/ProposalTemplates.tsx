/**
 * Item 6 — a proposal template for each offering.
 *
 * Same versioning model as the rate card, and the same promote-on-delete with
 * the same silent reply, so the same re-read-and-say-so treatment.
 *
 * One thing is specific to this family and worth stating at the field:
 * **versions are numbered per `(org, program, name)`**, and `make_current=true`
 * flips `is_current=False` on *every* current template for the programme, not
 * only same-named ones. So posting under a new name starts a v1 that
 * immediately supersedes an unrelated v3 — which looks like data loss and is
 * not. The form says it before the operator types a name.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { ProgramsRead, ProposalTemplatesRead } from "../api/reads";
import type { ItemStatus } from "../checklist/status";
import { DESCRIPTORS } from "../descriptors";
import { EntityForm } from "../ui/EntityForm";
import { DocxUpload } from "./docx/DocxUpload";
import {
  DEFAULT_MODE,
  DEFAULT_DOCUMENT_TYPE,
  DOCUMENT_TYPE_OPTIONS,
  MODE_OPTIONS,
  flowOf,
  forcesSimpleFlow,
  kindLabel,
  type DocumentType,
  type WriteMode,
} from "./docx/flow";
import {
  FormatFor,
  ItemHeading,
  ReadError,
  Section,
  asApiError,
  useList,
  useWrite,
} from "../ui/ItemScreen";
import { Banner, Field, Select, styles as s } from "../ui/primitives";
import { VersionHistory } from "../ui/VersionHistory";

const descriptor = DESCRIPTORS.proposalTemplates;

/** From `program.py` — the placeholders the renderer substitutes. */
const PLACEHOLDERS = [
  "{client_name}",
  "{contact_name}",
  "{sender_name}",
  "{sender_email}",
  "{org_name}",
  "{program_name}",
  "{program_description}",
  "{pricing_table}",
  "{total_amount}",
  "{context_summary}",
];

export function ProposalTemplates({ status }: { status: ItemStatus }) {
  const programs = useList("programs", endpoints.programs, ProgramsRead);
  const active = (programs.data ?? []).filter((p) => p.is_active);
  const [programId, setProgramId] = useState("");
  const chosen = programId || active[0]?.id || "";
  const [promoted, setPromoted] = useState<string | null>(null);
  const [mode, setMode] = useState<WriteMode>(DEFAULT_MODE);
  const [documentType, setDocumentType] = useState<DocumentType>(
    DEFAULT_DOCUMENT_TYPE,
  );
  // An MOU is only ever filled by the assistant, so choosing one settles the
  // flow as well. The mode selector below says so rather than silently
  // disagreeing with what the administrator picked.
  const uploadFlow = forcesSimpleFlow(documentType) ? "simple" : flowOf(mode);

  const templates = useQuery({
    queryKey: ["proposalTemplates", chosen],
    enabled: Boolean(chosen),
    queryFn: () =>
      request(endpoints.proposalTemplates(chosen), { as: "org", shape: ProposalTemplatesRead }),
  });

  const publish = useWrite<Record<string, unknown>>(["proposalTemplates"], (body) =>
    request(endpoints.proposalTemplates(chosen), { as: "org", method: "POST", body }),
  );

  const remove = useWrite<{ id: string; version: number }>(
    ["proposalTemplates"],
    async ({ id, version }) => {
      const reply = await request(endpoints.proposalTemplate(chosen, id), {
        as: "org",
        method: "DELETE",
      });
      const after = await request(endpoints.proposalTemplates(chosen), {
        as: "org",
        shape: ProposalTemplatesRead,
      });
      const current = after.find((t) => t.is_current);
      setPromoted(
        current
          ? `v${version} is gone. “${current.name}” v${current.version} is now current.`
          : `v${version} is gone. This offering now has no proposal template — proposals for it are refused.`,
      );
      return reply;
    },
  );

  if (active.length === 0) {
    return (
      <>
        <ItemHeading item={6} marker={status.marker} caption={status.caption} />
        <Section title="Nothing to write a template for yet" eyebrow="Blocked">
          <Banner tone="note" title="Item 4 comes first">
            <p style={{ margin: 0 }}>
              A proposal template hangs off an offering by foreign key.
            </p>
          </Banner>
        </Section>
        <FormatFor descriptor={descriptor} />
      </>
    );
  }

  return (
    <>
      <ItemHeading item={6} marker={status.marker} caption={status.caption} />

      <Section title="Which offering" eyebrow="Templates are per offering">
        <Field label="Offering" htmlFor="template-program">
          <Select
            id="template-program"
            options={active.map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))}
            value={chosen}
            onChange={(e) => {
              setProgramId(e.target.value);
              setPromoted(null);
            }}
          />
        </Field>
      </Section>

      <Section title="Publish a new version" eyebrow="Create">
        <Banner tone="note" title="Two ways to write a template">
          <p style={{ margin: 0 }}>
            A Markdown body is written here and rendered into a plain document.
            A Word document is uploaded as it is — its cover, images, headers
            and footers are kept exactly, and you mark where the system should
            fill things in. Use the Word document when the proposal has a
            designed look worth keeping.
          </p>
        </Banner>
        <div style={{ margin: "var(--s4) 0" }}>
          <Field label="What this template is" htmlFor="template-doctype">
            <Select
              id="template-doctype"
              options={DOCUMENT_TYPE_OPTIONS}
              value={documentType}
              onChange={(e) =>
                setDocumentType(e.target.value as DocumentType)
              }
            />
            {forcesSimpleFlow(documentType) && (
              <p style={{ marginTop: 4, fontSize: 13, color: "#5f6368" }}>
                An MOU is always filled in by the assistant from the tags its
                author wrote into the Word file, so the choice below does not
                apply to it.
              </p>
            )}
          </Field>
          <Field label="How this version is written" htmlFor="template-mode">
            <Select
              id="template-mode"
              options={MODE_OPTIONS}
              value={mode}
              onChange={(e) => setMode(e.target.value as WriteMode)}
            />
          </Field>
        </div>

        {uploadFlow !== null ? (
          // Keyed by flow so switching between the two document flows
          // starts a fresh form rather than carrying the other one's
          // half-filled name and success panel across.
          <DocxUpload
            key={`${uploadFlow}-${documentType}`}
            programId={chosen}
            flow={uploadFlow}
            documentType={documentType}
          />
        ) : (
        <EntityForm
          descriptor={descriptor}
          submitLabel="Publish new version"
          busy={publish.isPending}
          serverError={asApiError(publish.error)}
          initial={{ make_current: true }}
          onSubmit={(values) =>
            publish.mutate({ ...values, make_current: true } as Record<string, unknown>)
          }
        >
          <Banner tone="warn" title="A new name still supersedes the old one">
            <p style={{ margin: "0 0 var(--s2)" }}>
              Versions are numbered per name, so a name that is already here
              increments its own family. But publishing as current flips{" "}
              <em>every</em> current template for this offering — including one
              with a different name. A fresh name therefore starts at v1 and
              immediately supersedes whatever was current, which looks like data
              loss and is not: the old version is still listed below.
            </p>
          </Banner>
          <p className={s.mono} style={{ fontSize: "var(--text-xs)", margin: "var(--s3) 0 0" }}>
            {`Placeholders: ${PLACEHOLDERS.join("  ")}`}
          </p>
          <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s1) 0 0" }}>
            {"{client_name} also resolves from the older alias {school_name}."}
          </p>
        </EntityForm>
        )}
      </Section>

      <Section title="Versions" eyebrow="History">
        {promoted && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner tone="note" title="Removed">
              <p style={{ margin: 0 }}>{promoted}</p>
            </Banner>
          </div>
        )}
        {templates.isError ? (
          <ReadError error={templates.error} what="the template history" />
        ) : (
          <VersionHistory
            busy={remove.isPending}
            empty="No proposal template. Proposals for this offering are refused: “No proposal template for this offering. Ask your administrator to add one.”"
            versions={(templates.data ?? []).map((t) => ({
              id: t.id,
              version: t.version,
              isCurrent: t.is_current,
              summary: (
                <span>
                  <strong>{t.name}</strong>
                  <span className={s.muted}>
                    {` · ${kindLabel(t.kind, t.body_md.length)}`}
                  </span>
                </span>
              ),
            }))}
            onDelete={(v) => remove.mutate({ id: v.id, version: v.version })}
            deleteHint="Removing the current version promotes the highest remaining one. The reply does not say which, so this screen re-reads and tells you."
          />
        )}
        {remove.error && (
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Banner
              tone="blocked"
              title="That template could not be removed"
              serverMessage={asApiError(remove.error)?.detail ?? String(remove.error)}
            />
          </div>
        )}
      </Section>

      <FormatFor descriptor={descriptor} />
    </>
  );
}
