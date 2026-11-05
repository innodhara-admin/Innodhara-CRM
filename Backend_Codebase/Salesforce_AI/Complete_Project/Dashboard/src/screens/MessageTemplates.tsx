/**
 * Item 7: email templates.
 *
 * Since 28 Oct 2026 this item is mainly the organisation's **Word email
 * templates**: common emails grouped by category, product emails grouped by
 * product, each an uploaded Word file whose blanks Jarvis fills from the
 * client's record or by asking (spec: docs/superpowers/specs/
 * 2026-10-28-email-templates-design.md, section 7).
 *
 * The older text templates live on in one section below, because the business
 * card scan drafts its intro from `intro/email` and `intro/whatsapp`, and a
 * WhatsApp follow-up still starts from `follow_up/whatsapp`. That section is the
 * screen as it was, unchanged.
 *
 * ## The delete in the old section is unguarded, and that is the interesting part
 *
 * `delete_message_template` has no conflict check: it removes the row and
 * promotes a predecessor if there was one. Nothing refuses the removal of the
 * **only** `intro`/`email` template — and without one, the business-card scan
 * that is supposed to draft an introduction produces nothing at all. That
 * failure surfaces as the manual's own troubleshooting line, "A business card
 * scan drafts nothing", days later and far from here.
 *
 * So **the checklist is the guard, not a 409** (§7.2): item 7 turns amber the
 * moment a template it needs loses its last current row, and the delete
 * confirmation says which combination is about to be emptied.
 */
import { useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { EmailTemplatesRead, MessageTemplatesRead } from "../api/reads";
import { VOCAB } from "../api/vocabularies.generated";
import type { ItemStatus } from "../checklist/status";
import { DESCRIPTORS } from "../descriptors";
import { EntityForm } from "../ui/EntityForm";
import {
  FormatFor,
  ItemHeading,
  ReadError,
  Section,
  asApiError,
  useList,
  useWrite,
} from "../ui/ItemScreen";
import {
  Banner,
  Button,
  DataTable,
  StatusMarker,
  styles as s,
} from "../ui/primitives";
import { Attachments } from "./email/Attachments";
import { EmailUpload } from "./email/EmailUpload";
import { groupTemplates } from "./email/email";

const descriptor = DESCRIPTORS.messageTemplates;

/** The four the manual asks for, built from VOCAB and never typed out (A4). */
const COMBINATIONS = VOCAB.template_kind.flatMap((kind) =>
  VOCAB.message_channel.map((channel) => ({ kind, channel })),
);

export function MessageTemplates({ status }: { status: ItemStatus }) {
  return (
    <>
      <ItemHeading item={7} marker={status.marker} caption={status.caption} />

      <Section title="Upload an email template" eyebrow="Create">
        <EmailUpload />
      </Section>

      <EmailTemplateList />

      <CardScanTemplates />

      <FormatFor descriptor={descriptor} />
    </>
  );
}

function EmailTemplateList() {
  const templates = useList("emailTemplates", endpoints.emailTemplates, EmailTemplatesRead);
  const [confirming, setConfirming] = useState<{ id: string; name: string; version: number } | null>(
    null,
  );
  const remove = useWrite<string>(["emailTemplates"], (id) =>
    request(endpoints.emailTemplate(id), { as: "org", method: "DELETE" }),
  );

  const groups = groupTemplates(templates.data ?? []);

  return (
    <Section title="Email templates" eyebrow="Published">
      {templates.isError ? (
        <ReadError error={templates.error} what="the email templates" />
      ) : groups.length === 0 ? (
        <p className={s.muted} style={{ margin: 0 }}>
          No email templates yet. Jarvis writes every email freely until one is uploaded.
        </p>
      ) : (
        groups.map((group) => (
          <div key={group.label} style={{ marginBlockEnd: "var(--s5)" }}>
            <h3 style={{ fontSize: "var(--text-sm)", margin: "0 0 var(--s2)" }}>{group.label}</h3>
            <DataTable
              columns={["", "Name", "Subject", "Tags", "Also attaches", "Default files", "Version", ""]}
              rows={group.rows.map((t) => [
                <StatusMarker
                  key="m"
                  status={t.is_current ? "done" : "none"}
                  label={t.is_current ? "current" : "superseded"}
                />,
                <span key="n">
                  {t.name}
                  {t.when_to_use && (
                    <span className={s.muted} style={{ display: "block", fontSize: "var(--text-xs)" }}>
                      {t.when_to_use}
                    </span>
                  )}
                </span>,
                <span key="s" className={s.mono}>{t.subject}</span>,
                <span key="t" className={s.mono}>
                  {`${t.tags} · ${t.always_asked} asked`}
                </span>,
                t.built_document === "proposal"
                  ? "the built proposal"
                  : t.built_document === "mou"
                    ? "the built MoU"
                    : <span key="b" className={s.muted}>nothing</span>,
                <Attachments key="a" template={t} />,
                <span key="v" className={s.mono}>{`v${t.version}`}</span>,
                <Button
                  key="d"
                  variant="danger"
                  disabled={remove.isPending}
                  onClick={() => setConfirming({ id: t.id, name: t.name, version: t.version })}
                >
                  Remove
                </Button>,
              ])}
            />
          </div>
        ))
      )}

      {confirming && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="note" title={`Remove “${confirming.name}” v${confirming.version}?`}>
            <p style={{ margin: "0 0 var(--s3)" }}>
              If it is the current version, the highest remaining version of the same name
              becomes current. If it is the only one, Jarvis can no longer send this email.
            </p>
            <div style={{ display: "flex", gap: "var(--s3)" }}>
              <Button
                variant="danger"
                onClick={() => {
                  remove.mutate(confirming.id);
                  setConfirming(null);
                }}
              >
                Remove it
              </Button>
              <Button variant="quiet" onClick={() => setConfirming(null)}>
                Keep it
              </Button>
            </div>
          </Banner>
        </div>
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
  );
}

/** The screen as it was before 28 Oct 2026, kept for the card scan and WhatsApp. */
function CardScanTemplates() {
  const templates = useList("messageTemplates", endpoints.messageTemplates, MessageTemplatesRead);
  const [confirming, setConfirming] = useState<{
    id: string;
    name: string;
    kind: string;
    channel: string;
    last: boolean;
  } | null>(null);

  const rows = templates.data ?? [];
  const currentFor = (kind: string, channel: string) =>
    rows.find((r) => r.kind === kind && r.channel === channel && r.is_current);

  const publish = useWrite<Record<string, unknown>>(["messageTemplates"], (body) =>
    request(endpoints.messageTemplates, { as: "org", method: "POST", body }),
  );

  const remove = useWrite<string>(["messageTemplates"], (id) =>
    request(endpoints.messageTemplate(id), { as: "org", method: "DELETE" }),
  );

  return (
    <Section title="Card scan and WhatsApp templates" eyebrow="Older text templates">
      <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "0 0 var(--s3)" }}>
        The business card scan drafts its intro from intro/email and intro/whatsapp, and a
        WhatsApp follow-up starts from follow_up/whatsapp. Email follow-ups now use the Word
        email templates above.
      </p>
      <DataTable
        columns={["", "Kind", "Channel", "Current template"]}
        rows={COMBINATIONS.map(({ kind, channel }) => {
          const current = currentFor(kind, channel);
          return [
            <StatusMarker
              key="m"
              status={current ? "done" : "none"}
              label={current ? "covered" : "missing"}
            />,
            <span key="k" className={s.mono}>
              {kind}
            </span>,
            <span key="c" className={s.mono}>
              {channel}
            </span>,
            current ? (
              <span key="t">
                {current.name}
                <span className={s.muted}>{` · v${current.version}`}</span>
              </span>
            ) : (
              <span key="t" className={s.muted}>
                none — nothing can be drafted for this channel
              </span>
            ),
          ];
        })}
      />

      <div style={{ marginBlockStart: "var(--s5)" }}>
        <EntityForm
          descriptor={descriptor}
          submitLabel="Publish new version"
          busy={publish.isPending}
          serverError={asApiError(publish.error)}
          initial={{ make_current: true }}
          resetSignal={publish.submittedAt}
          onSubmit={(body) =>
            publish.mutate({ ...body, make_current: true } as Record<string, unknown>)
          }
        >
          <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s2) 0 0" }}>
            A subject is required for email and ignored for WhatsApp — the
            server refuses the first case with “Email templates need a subject”,
            and this form says so before the round trip. Versions are numbered
            per kind, channel and name.
          </p>
        </EntityForm>
      </div>

      <div style={{ marginBlockStart: "var(--s5)" }}>
        {templates.isError ? (
          <ReadError error={templates.error} what="the template list" />
        ) : (
          <DataTable
            columns={["", "Kind / channel", "Name", "Subject", "Version", ""]}
            empty="No message templates. A scanned business card cannot draft an introduction at all."
            rows={rows.map((t) => [
              <StatusMarker
                key="m"
                status={t.is_current ? "done" : "none"}
                label={t.is_current ? "current" : "superseded"}
              />,
              <span key="kc" className={s.mono}>
                {`${t.kind} / ${t.channel}`}
              </span>,
              t.name,
              t.subject ?? <span key="s" className={s.muted}>—</span>,
              <span key="v" className={s.mono}>{`v${t.version}`}</span>,
              <Button
                key="d"
                variant="danger"
                disabled={remove.isPending}
                onClick={() =>
                  setConfirming({
                    id: t.id,
                    name: t.name,
                    kind: t.kind,
                    channel: t.channel,
                    // "Last" means: after this delete there is no other version
                    // left for the pair, so nothing can be promoted into it.
                    last:
                      rows.filter((r) => r.kind === t.kind && r.channel === t.channel).length === 1,
                  })
                }
              >
                Remove
              </Button>,
            ])}
          />
        )}
      </div>

      {confirming && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner
            tone={confirming.last ? "warn" : "note"}
            title={`Remove “${confirming.name}”?`}
          >
            {confirming.last ? (
              <p style={{ margin: "0 0 var(--s3)" }}>
                This is the <strong>only</strong> {confirming.kind} template for{" "}
                {confirming.channel}. Nothing will be promoted in its place, and{" "}
                <strong>the server will not refuse this</strong> — there is no
                guard on this delete. Item 7 will turn amber, and that is the
                only warning the system gives.
                {confirming.kind === "intro" && (
                  <>
                    {" "}
                    With no intro template for {confirming.channel}, a scanned
                    business card drafts nothing.
                  </>
                )}
              </p>
            ) : (
              <p style={{ margin: "0 0 var(--s3)" }}>
                Another version exists for {confirming.kind}/{confirming.channel}
                ; if this one was current, the highest remaining version is
                promoted in its place.
              </p>
            )}
            <div style={{ display: "flex", gap: "var(--s3)" }}>
              <Button
                variant="danger"
                onClick={() => {
                  remove.mutate(confirming.id);
                  setConfirming(null);
                }}
              >
                Remove it
              </Button>
              <Button variant="quiet" onClick={() => setConfirming(null)}>
                Keep it
              </Button>
            </div>
          </Banner>
        </div>
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
  );
}
