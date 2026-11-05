/**
 * Item 14 — calendar. The same compound status as item 11, with two facts that
 * are specific to this one and both worth stating at the field.
 *
 *  1. **`credentials_file` is a path on the server, not an upload.** The
 *     console cannot put a file anywhere; it records a path that must already
 *     exist and be readable by the API process. A path that is merely typed
 *     correctly and does not exist stores fine and fails at the first booking.
 *  2. **Nothing here is encrypted.** `admin.py · set_calendar_integration`
 *     makes no `encrypt_secret` call, unlike the email and WhatsApp
 *     integrations — because the secret lives in a file the server must already
 *     be able to read, so encrypting the path would protect nothing. Worth
 *     saying anyway: an operator who assumes symmetry with the other two would
 *     assume wrongly.
 */
import { endpoints } from "../api/endpoints";
import { ITEM_BY_NUMBER } from "../checklist/items";
import type { ItemStatus } from "../checklist/status";
import { IntegrationPanel } from "../ui/Integration";
import { ItemHeading, Section } from "../ui/ItemScreen";
import { Banner, Quote } from "../ui/primitives";

export function Calendar({ status }: { status: ItemStatus }) {
  const row = ITEM_BY_NUMBER.get(14)!;

  return (
    <>
      <ItemHeading item={14} marker={status.marker} caption={status.caption} />

      <Section title="The manual on this item" eyebrow="Verbatim">
        <Quote source={row.manualRef}>{row.quote}</Quote>
        <p style={{ maxInlineSize: "var(--measure)" }}>
          <strong>If you skip it: </strong>
          {row.ifSkipped}
        </p>
      </Section>

      <IntegrationPanel
        title="Google Calendar"
        route={endpoints.calendarIntegration}
        modeVar="CALENDAR_MODE"
        credentialsStored={(live) => live.calendar_credentials_stored}
        configured={(live) => live.calendar_credentials_stored && live.calendar_mode === "google"}
        modeValue={(live) => live.calendar_mode}
        fields={[
          {
            name: "calendar_id",
            label: "Calendar id",
            caption: "the calendar confirmed demos are mirrored into",
          },
          {
            name: "credentials_file",
            label: "Credentials file",
            caption:
              "a path on the SERVER to a service-account JSON · this console cannot upload one, and a path that does not exist stores fine and fails at the first booking",
          },
          {
            name: "meet_link",
            label: "Meet link",
            caption:
              "optional · a reusable link stamped into demo invites — create one at meet.google.com, “Create a meeting for later”",
          },
        ]}
        note={
          <Banner tone="warn" title="This one is stored unencrypted">
            <p style={{ margin: 0 }}>
              Unlike the email and WhatsApp integrations, nothing on this panel
              is encrypted — <code>set_calendar_integration</code> makes no
              <code> encrypt_secret</code> call. That is defensible, because the
              value is a path and the secret it points at is a file the server
              must already be able to read. It is stated here so nobody assumes
              symmetry with the other two.
            </p>
          </Banner>
        }
      />

      <Section title="The system's calendar is still the source of truth" eyebrow="Either way">
        <p style={{ margin: 0, maxInlineSize: "var(--measure)" }}>
          Mirroring is a convenience. Demos are booked, clashes are detected and
          invitations are sent from the system's own calendar whether this is
          connected or not — which is why item 14 is in the optional tier and why
          leaving it amber costs nothing but the mirror.
        </p>
      </Section>
    </>
  );
}
