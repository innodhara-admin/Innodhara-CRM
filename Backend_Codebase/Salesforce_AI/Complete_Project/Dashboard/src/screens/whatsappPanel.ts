/**
 * What the WhatsApp panel reports (4 Nov 2026). Pure, so it is tested without
 * a browser: `WhatsAppPanel.tsx` only renders it.
 *
 * Like every integration on item 11, nothing leaves unless BOTH halves hold:
 * the chosen provider's credentials (stored here) and `WHATSAPP_MODE=cloud_api`
 * on the server (which this console cannot change). Documents need a third
 * thing, `PUBLIC_BASE_URL`, because the provider fetches the PDF from us.
 */
import { z } from "zod";

import type { Settings } from "../api/reads";

export type Provider = "off" | "meta" | "wati";

export const PROVIDER_OPTIONS = [
  { value: "off", label: "Off" },
  { value: "wati", label: "Wati" },
  { value: "meta", label: "Meta (WhatsApp Cloud API)" },
] as const;

const NAME: Record<Provider, string> = { off: "Off", meta: "Meta", wati: "Wati" };

export type WhatsAppState = {
  provider: Provider;
  sending: boolean;
  warning: string | null;
  webhookUrl: string | null;
};

function asProvider(value: string): Provider {
  return value === "meta" || value === "wati" ? value : "off";
}

export function whatsappState(s: Settings, origin: string): WhatsAppState {
  const provider = asProvider(s.whatsapp_provider);
  const sending = provider !== "off" && s.whatsapp_credentials_stored && s.whatsapp_mode === "cloud_api";
  let warning: string | null = null;
  if (provider === "off") {
    warning = "WhatsApp is off for this organisation. Nothing is sent on WhatsApp.";
  } else if (!s.whatsapp_credentials_stored) {
    warning = `${NAME[provider]} is chosen but its credentials are not stored yet. Store them below; until then nothing is sent.`;
  } else if (s.whatsapp_mode !== "cloud_api") {
    warning = `Credentials are stored, but WHATSAPP_MODE=${s.whatsapp_mode} on this server, so messages are only written to a file. Only the server's settings can change that.`;
  } else if (!s.public_base_url_set) {
    warning = "PUBLIC_BASE_URL is not set on the server, so proposals and meeting transcripts cannot be attached. Text messages still go.";
  }
  const webhookUrl =
    provider === "wati" && s.whatsapp_webhook_path ? `${origin.replace(/\/$/, "")}${s.whatsapp_webhook_path}` : null;
  return { provider, sending, warning, webhookUrl };
}

const LABELS: Record<string, string> = {
  daily_brief: "Morning brief",
  general: "General updates",
  blocked_on_you: "Someone is waiting on you",
};

export function kindLabel(kind: string): string {
  if (LABELS[kind]) return LABELS[kind];
  const words = kind.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// ── admin.py · check_whatsapp_templates ──────────────────────────────────
export const TemplatesRead = z.object({
  provider: z.string(),
  checked: z.boolean(),
  error: z.string().nullable(),
  templates: z.array(
    z.object({
      name: z.string(),
      category: z.string(),
      document: z.boolean(),
      values: z.array(z.string()),
      found: z.boolean().nullable(),
      status: z.string().nullable(),
      values_match: z.boolean().nullable(),
    }),
  ),
});
export type TemplatesCheck = z.infer<typeof TemplatesRead>;

// ── admin.py · send_whatsapp_test ────────────────────────────────────────
export const TestRead = z.object({
  ok: z.boolean(),
  provider_id: z.string(),
  error: z.string().nullable(),
  to: z.string(),
  dry_run: z.boolean(),
});
export type TestResult = z.infer<typeof TestRead>;

export function testOutcome(r: TestResult): string {
  if (!r.ok) return `Not sent to ${r.to}. ${r.error ?? "The provider gave no reason."}`;
  if (r.dry_run) return `Written to the outbox file for ${r.to}, not sent: the server is in dry run.`;
  return `Sent to ${r.to}. Check that phone.`;
}
