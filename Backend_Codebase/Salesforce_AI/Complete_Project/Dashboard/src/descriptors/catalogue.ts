/**
 * Skills, programs, pricing, proposal templates and message templates.
 *
 * Grouped in one module because they are the dependency chain of
 * `02_SEEDING_PREREQUISITES.md` §0 tiers 1–2 and are read together by the
 * go-live check. Each is still its own `Descriptor`.
 */
import { CONSTRAINTS } from "../api/constraints.generated";
import { VOCAB } from "../api/vocabularies.generated";
import type { Descriptor } from "./types";

export const skills: Descriptor = {
  key: "skills",
  item: 3,
  title: "A skill on every person's record",
  writeSchema: "SkillRequest",
  read: "skills",
  quote:
    "This is the single highest-value entry in this list. Tasks are matched to " +
    "people by skill, weighed against workload and leave. Give everyone the " +
    "neutral skill general plus their real specialisms, at basic, good or expert.",
  ifSkipped:
    'Every task falls to the phase lead flagged "no skill match", at low ' +
    "confidence, and is routed to a human instead of being assigned.",
  manualRef: "Product manual, p. 6 · item 3",
  dependsOn: ["staff"],
  inBundle: true, // cleared by wipe_org_config; round-trips on user_id (§5.8)
  reimport: "upserts — the level is overwritten and the row is not duplicated",
  fields: [
    {
      field: "user_id",
      label: "Person",
      control: "select",
      enforcement: { kind: "backend-undeclared", source: "ops.py · set_skill" },
      caption: "must be a user in this organisation",
    },
    {
      field: "skill",
      label: "Skill",
      control: "text",
      enforcement: {
        kind: "ui-only",
        why: "free text by decision (Q12) — a hard-coded taxonomy would be rejected by the genericity guards",
      },
      caption:
        "matched against a playbook entry's required_skill exactly · autocomplete offers skills already held here",
    },
    {
      field: "level",
      label: "Level",
      control: "select",
      options: VOCAB.skill_level,
      enforcement: {
        kind: "ui-only",
        why: "ops.py · set_skill stores whatever string it is sent; these three are the engine's vocabulary, not a validation",
      },
      caption: "basic, good or expert",
    },
  ],
  csv: {
    columns: ["user_id", "skill", "level"],
    example: {
      user_id: "<a user id from Staff>",
      skill: "rack-and-stack",
      level: "expert",
    },
  },
};

export const programs: Descriptor = {
  key: "programs",
  item: 4,
  title: "What you sell — one entry per offering",
  writeSchema: "ProgramRequest",
  read: "programs",
  quote:
    "Named and described. The description is what the AI reads when it decides " +
    "which of your offerings a conversation was about.",
  ifSkipped:
    "Conversations cannot be matched to an offering, and no proposal can be built.",
  manualRef: "Product manual, p. 6 · item 4",
  dependsOn: [],
  inBundle: true,
  reimport:
    "fails on a duplicate code — unique per organisation, compared case-insensitively",
  fields: [
    {
      field: "name",
      label: "Name",
      control: "text",
      enforcement: { kind: "ui-only", why: "an unconstrained string on the wire" },
      caption: "what your team calls this offering",
    },
    {
      field: "code",
      label: "Code",
      control: "text",
      enforcement: { kind: "schema" },
      caption: `${CONSTRAINTS.ProgramRequest.code.minLength}–${CONSTRAINTS.ProgramRequest.code.maxLength} characters · upper-cased on write, so what you type comes back changed`,
    },
    {
      field: "description",
      label: "Description",
      control: "textarea",
      enforcement: {
        kind: "ui-only",
        why: "unconstrained — but the matcher reads it, so an empty description makes every conversation ambiguous",
      },
      caption:
        "this is what the AI reads to decide which offering a conversation was about",
    },
  ],
  csv: {
    columns: ["name", "code", "description"],
    example: {
      name: "Datacentre commissioning",
      code: "DC-COMMISSION",
      description:
        "Commissioning and handover of capacity, including power and cooling sign-off.",
    },
  },
};

export const pricing: Descriptor = {
  key: "pricing",
  item: 5,
  title: "A rate card for each offering",
  writeSchema: "PricingRequest",
  read: "pricing",
  quote:
    'Every line: code, label, unit ("per rack", "per seat", "per site"), unit ' +
    "price, and a default quantity where one is sensible. Rate cards are " +
    "versioned — editing prices creates a new version and never alters a " +
    "proposal already sent.",
  ifSkipped:
    '"No pricing table for this offering. Ask your administrator to add one." ' +
    "No proposal can be created.",
  manualRef: "Product manual, p. 6 · item 5",
  dependsOn: ["programs"],
  inBundle: true,
  reimport:
    "creates a NEW version and supersedes the current one — a careless re-import silently inflates version numbers",
  fields: [
    {
      field: "currency",
      label: "Currency",
      control: "text",
      enforcement: { kind: "ui-only", why: "an unconstrained string; defaults to INR" },
      caption: "applies to every line on this card",
    },
    {
      field: "items",
      label: "Lines",
      control: "json",
      enforcement: { kind: "schema" },
      caption: "at least one line · each needs code, label and unit_price",
    },
  ],
  csv: {
    // One CSV row per line; the applier groups rows into one versioned card.
    linesOf: "items",
    columns: ["code", "label", "unit", "unit_price", "default_quantity", "notes"],
    example: {
      code: "RACK",
      label: "Rack commissioning",
      unit: "per rack",
      unit_price: "45000",
      // Empty means "this org did not say how many" — NOT one of them (§3.3).
      default_quantity: "",
      notes: "Includes power and cooling sign-off",
    },
  },
};

export const proposalTemplates: Descriptor = {
  key: "proposalTemplates",
  item: 6,
  title: "A proposal template for each offering",
  writeSchema: "ProposalTemplateRequest",
  read: "proposalTemplates",
  quote:
    "Your document, with placeholders the system fills in — client name, " +
    "contact, the rate table, the total, and a one-line summary of the engagement.",
  ifSkipped:
    '"No proposal template for this offering. Ask your administrator to add one."',
  manualRef: "Product manual, p. 6 · item 6",
  dependsOn: ["programs"],
  inBundle: true,
  writeOnly: ["make_current"],
  reimport:
    "creates a NEW version and supersedes the current one; " +
    "Word-document templates are not carried in a bundle and must be re-uploaded",
  fields: [
    {
      field: "name",
      label: "Name",
      control: "text",
      enforcement: {
        kind: "backend-undeclared",
        source: "admin.py · add_proposal_template",
      },
      caption: "versions are numbered per name, so reusing a name supersedes that family",
    },
    {
      field: "body_md",
      label: "Body",
      control: "textarea",
      enforcement: { kind: "schema" },
      caption: `at least ${CONSTRAINTS.ProposalTemplateRequest.body_md.minLength} characters · Markdown with placeholders`,
    },
  ],
  csv: {
    columns: ["name", "body_md"],
    example: {
      name: "Standard commissioning",
      // Pre-quoted: template bodies contain newlines, which survive CSV only
      // under correct quoting (§5.5). JSON is recommended for this entity.
      body_md: "## Scope\n\nCommissioning and handover for {{client_name}}.\n",
    },
  },
};

export const messageTemplates: Descriptor = {
  key: "messageTemplates",
  item: 7,
  // Renamed 28 Oct 2026: the item is mainly the Word email templates now.
  title: "Email templates",
  writeSchema: "MessageTemplateRequest",
  read: "messageTemplates",
  quote:
    "One of each, for email and for WhatsApp. These are the words a new contact " +
    "first reads, so they should sound like your organisation.",
  ifSkipped:
    "The introduction that a scanned business card is supposed to draft cannot " +
    "be produced at all.",
  manualRef: "Product manual, p. 6 · item 7",
  dependsOn: [],
  inBundle: true,
  writeOnly: ["make_current"],
  reimport: "creates a NEW version and supersedes the current one for that kind and channel",
  // `admin.py · add_message_template` refuses an email template with no
  // subject — "Email templates need a subject". Declared here so the operator
  // learns it before the round trip, and so the import preview can refuse the
  // row rather than discovering it half way through applying a file.
  crossFieldRules: [
    {
      field: "subject",
      says: "required when the channel is email; ignored for WhatsApp",
      enforcement: {
        kind: "backend-undeclared",
        source: "admin.py · add_message_template",
      },
      check: (row) =>
        row.channel === "email" && !String(row.subject ?? "").trim()
          ? "Email templates need a subject"
          : null,
    },
  ],
  fields: [
    {
      field: "kind",
      label: "Kind",
      control: "select",
      options: VOCAB.template_kind,
      enforcement: {
        kind: "backend-undeclared",
        source: "admin.py · add_message_template",
      },
      caption: "intro or follow_up",
    },
    {
      field: "channel",
      label: "Channel",
      control: "select",
      options: VOCAB.message_channel,
      enforcement: {
        kind: "backend-undeclared",
        source: "admin.py · add_message_template",
      },
      caption: "email or whatsapp · the card scan and WhatsApp still use three of the four",
    },
    {
      field: "name",
      label: "Name",
      control: "text",
      enforcement: {
        kind: "backend-undeclared",
        source: "admin.py · add_message_template",
      },
      caption: "versions are numbered per kind, channel and name",
    },
    {
      field: "subject",
      label: "Subject",
      control: "text",
      enforcement: {
        kind: "backend-undeclared",
        source: "admin.py · add_message_template",
      },
      caption: "required for email, ignored for WhatsApp",
    },
    {
      field: "body",
      label: "Body",
      control: "textarea",
      enforcement: { kind: "schema" },
      caption: `at least ${CONSTRAINTS.MessageTemplateRequest.body.minLength} characters`,
    },
  ],
  csv: {
    columns: ["kind", "channel", "name", "subject", "body"],
    example: {
      kind: "intro",
      channel: "email",
      name: "Introduction",
      subject: "Introduction from our team",
      body: "Hello {{contact_name}},\n\nThank you for your time today.\n",
    },
  },
};
