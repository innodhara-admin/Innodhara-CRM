/**
 * Every route this console calls, and which identity it needs.
 *
 * One table so a permission surprise is a one-line correction rather than a
 * hunt through screens. The `identity` column is not a guess: `super` here means
 * the route depends on `get_super_admin`, verified by reading
 * `app/api/organisations.py`, and everything else refuses that token (D1).
 *
 * The console does NOT mirror the permission matrix (§1.1, Q15). It lets the
 * server answer with a 403 rather than pre-judging which org role may call what
 * — this table only distinguishes the two *sessions*, which are genuinely not
 * interchangeable.
 *
 * Checked 2026-09-04 for the six docx proposal-template routes: all six depend
 * on `get_org_context` (five through `require_permission("manage_templates")`,
 * the media read directly), none on `get_super_admin`, so SUPER_ONLY is
 * unchanged.
 */
import type { Identity } from "../session/store";

const V1 = "/api/v1";

export const endpoints = {
  // ── Auth ────────────────────────────────────────────────────────────────
  login: `${V1}/auth/login`,
  me: `${V1}/auth/me`,
  changePassword: `${V1}/auth/change-password`,

  // ── Platform: the only two routes needing the super-admin session ───────
  orgs: `${V1}/orgs`,

  // ── Staff and skills ────────────────────────────────────────────────────
  staff: `${V1}/admin/users`,
  staffMember: (id: string) => `${V1}/admin/users/${id}`,
  staffResetPassword: (id: string) => `${V1}/admin/users/${id}/reset-password`,
  skills: `${V1}/skills`,

  // ── Catalogue ───────────────────────────────────────────────────────────
  programs: `${V1}/admin/programs`,
  program: (id: string) => `${V1}/admin/programs/${id}`,
  pricing: (programId: string) => `${V1}/admin/programs/${programId}/pricing`,
  pricingVersion: (programId: string, version: number) =>
    `${V1}/admin/programs/${programId}/pricing/${version}`,
  proposalTemplates: (programId: string) =>
    `${V1}/admin/programs/${programId}/proposal-templates`,
  proposalTemplate: (programId: string, templateId: string) =>
    `${V1}/admin/programs/${programId}/proposal-templates/${templateId}`,
  proposalTemplatesDocx: (programId: string) =>
    `${V1}/admin/programs/${programId}/proposal-templates/docx`,
  templateDoc: (docId: string) => `${V1}/admin/proposal-template-docs/${docId}`,
  templateDocSuggest: (docId: string) =>
    `${V1}/admin/proposal-template-docs/${docId}/suggest`,
  templateDocPlan: (docId: string) =>
    `${V1}/admin/proposal-template-docs/${docId}/plan`,
  templateDocPreview: (docId: string) =>
    `${V1}/admin/proposal-template-docs/${docId}/preview`,
  templateDocMedia: (docId: string, name: string) =>
    `${V1}/admin/proposal-template-docs/${docId}/media/${encodeURIComponent(name)}`,
  messageTemplates: `${V1}/admin/message-templates`,
  messageTemplate: (id: string) => `${V1}/admin/message-templates/${id}`,
  emailTemplates: `${V1}/admin/email-templates`,
  emailTemplate: (id: string) => `${V1}/admin/email-templates/${id}`,
  emailCategories: `${V1}/admin/email-templates/categories`,
  emailTemplateAttachments: (id: string) =>
    `${V1}/admin/email-templates/${id}/attachments`,
  emailTemplateAttachment: (id: string, attachmentId: string) =>
    `${V1}/admin/email-templates/${id}/attachments/${attachmentId}`,
  playbooks: `${V1}/playbooks`,
  playbook: (id: string) => `${V1}/playbooks/${id}`,

  // ── Governance ──────────────────────────────────────────────────────────
  approvalRules: `${V1}/approval-rules`,
  approvalRule: (id: string) => `${V1}/approval-rules/${id}`,
  settings: `${V1}/admin/settings`,
  emailIntegration: `${V1}/admin/integrations/email`,
  whatsappIntegration: `${V1}/admin/integrations/whatsapp`,
  calendarIntegration: `${V1}/admin/integrations/calendar`,

  // ── Optional tier ───────────────────────────────────────────────────────
  demoTeams: `${V1}/admin/demo-teams`,
  demoTeam: (id: string) => `${V1}/admin/demo-teams/${id}`,
  vendors: `${V1}/vendors`,
  vendor: (id: string) => `${V1}/vendors/${id}`,

  // ── Reset ───────────────────────────────────────────────────────────────
  reset: `${V1}/admin/reset`,
} as const;

/**
 * `GET /orgs` and `POST /orgs` are the only routes this console calls that need
 * the super-admin session, and `GET /orgs` is used solely by the optional org
 * picker (P6/A5). Checklist item 1 derives from `GET /auth/me`, which the
 * org_admin session can read — the design originally said `GET /orgs`, which
 * that session cannot call at all.
 */
export const SUPER_ONLY: ReadonlySet<string> = new Set([endpoints.orgs]);

export function identityFor(path: string): Identity {
  return SUPER_ONLY.has(path) ? "super" : "org";
}
