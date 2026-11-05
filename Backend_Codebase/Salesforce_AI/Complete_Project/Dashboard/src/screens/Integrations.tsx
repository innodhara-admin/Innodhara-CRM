/**
 * Item 11 — email sending. **The single most important screen in this console.**
 *
 * The manual warns about this failure twice — p.7 *"otherwise approved messages
 * are written to a file and everyone believes they were sent"* and p.16
 * *"Approved messages never arrive"* — and before backend change #2 the API
 * actively encouraged it: `email_integration_configured` was `bool(smtp_username)`,
 * so it read `true` the moment credentials were stored, whatever `EMAIL_MODE`
 * said. Change #2 made that boolean honest; this screen still derives from the
 * two halves separately, because the operator needs to know *which* one is
 * missing and a single boolean cannot say.
 *
 * WhatsApp is shown alongside for the same reason: it is the same split
 * (`WHATSAPP_MODE`, org credentials) and is not a checklist item, so it has
 * nowhere else to be reported at all. Since 4 Nov 2026 it has its own panel
 * (`WhatsAppPanel.tsx`): a choice of provider (Wati or Meta), staff updates,
 * a test message and a template check.
 */
import { endpoints } from "../api/endpoints";
import type { ItemStatus } from "../checklist/status";
import { ITEM_BY_NUMBER } from "../checklist/items";
import { IntegrationPanel } from "../ui/Integration";
import { ItemHeading, Section } from "../ui/ItemScreen";
import { Banner, Quote } from "../ui/primitives";
import { WhatsAppPanel } from "./WhatsAppPanel";

export function Integrations({ status }: { status: ItemStatus }) {
  const row = ITEM_BY_NUMBER.get(11)!;

  return (
    <>
      <ItemHeading item={11} marker={status.marker} caption={status.caption} />

      <Section title="The manual on this item" eyebrow="Verbatim">
        <Quote source={row.manualRef}>{row.quote}</Quote>
        <p style={{ maxInlineSize: "var(--measure)" }}>
          <strong>If you skip it: </strong>
          {row.ifSkipped}
        </p>
      </Section>

      <IntegrationPanel
        title="Email"
        route={endpoints.emailIntegration}
        modeVar="EMAIL_MODE"
        credentialsStored={(live) => live.email_credentials_stored}
        configured={(live) => live.email_credentials_stored && live.email_mode === "smtp"}
        modeValue={(live) => live.email_mode}
        fields={[
          {
            name: "smtp_username",
            label: "SMTP username",
            caption: "the sending address · stored per organisation, encrypted at rest",
          },
          {
            name: "smtp_app_password",
            label: "App password",
            caption: "an application password, not the account password · encrypted with Fernet before it is written",
          },
        ]}
        note={
          <Banner tone="note" title="There is a better option than this one">
            <p style={{ margin: 0 }}>
              The manual prefers <strong>each salesperson's own account</strong>,
              so the client always sees a real person's address. That is set by
              each person for themselves at{" "}
              <code>POST /auth/email-app-password</code> — <strong>there is no
              admin route to set it for somebody else</strong>, so it cannot be
              done from this console for anyone but the signed-in user. What is
              below is the organisation-wide fallback.
            </p>
          </Banner>
        }
      />

      <WhatsAppPanel />
    </>
  );
}
