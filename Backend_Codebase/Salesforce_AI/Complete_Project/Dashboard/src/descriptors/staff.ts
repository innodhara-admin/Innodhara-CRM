import { CONSTRAINTS } from "../api/constraints.generated";
import { VOCAB } from "../api/vocabularies.generated";
import type { Descriptor } from "./types";

const C = CONSTRAINTS.CreateUserRequest;

export const staff: Descriptor = {
  key: "staff",
  item: 2,
  title: "Staff accounts, with the right role",
  writeSchema: "CreateUserRequest",
  // GET /admin/users declares UserResponse — one of the only two typed reads.
  read: null,
  quote:
    "Email is the identity and decides the organisation; the role decides the " +
    "navigation and the permissions. Set each person's department too — it " +
    "decides who receives their escalations.",
  ifSkipped: "People either cannot sign in, or see the wrong app.",
  manualRef: "Product manual, p. 6 · item 2",
  dependsOn: [],
  // §5.8: users can never be wiped, so there is nothing to restore.
  inBundle: false,
  reimport: "fails on a duplicate email — email is globally unique, not per-organisation",
  fields: [
    {
      field: "email",
      label: "Email",
      control: "text",
      enforcement: { kind: "backend-undeclared", source: "admin.py · register_staff" },
      caption: "must end with the organisation's own domain, and be unused everywhere",
    },
    {
      field: "name",
      label: "Full name",
      control: "text",
      enforcement: { kind: "schema" },
      caption: "at least 2 characters",
    },
    {
      field: "role",
      label: "Role",
      control: "select",
      options: VOCAB.org_role,
      enforcement: { kind: "backend-undeclared", source: "admin.py · register_staff" },
      caption:
        "decides the navigation and the permissions · super_admin cannot be assigned here",
    },
    {
      field: "department",
      label: "Department",
      control: "select",
      options: VOCAB.department,
      enforcement: {
        kind: "backend-undeclared",
        source: "admin.py · _validated_department",
      },
      caption:
        "decides who receives escalations · accounts is a department but not a role",
    },
    {
      field: "designation",
      label: "Designation",
      control: "text",
      enforcement: { kind: "ui-only", why: "stored as free text and never validated" },
      caption: "job title, shown on proposals and invites",
    },
    {
      field: "phone",
      label: "Phone",
      control: "text",
      enforcement: { kind: "ui-only", why: "stored as free text and never validated" },
      caption: "optional",
    },
    {
      field: "whatsapp_number",
      label: "WhatsApp number",
      control: "text",
      enforcement: { kind: "ui-only", why: "stored as free text and never validated" },
      caption: "optional · used only when WhatsApp sending is on",
    },
    {
      field: "max_open_tasks",
      label: "Max open tasks",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · CreateUserRequest" },
      caption: `${C.max_open_tasks.minimum}–${C.max_open_tasks.maximum} · the assignment engine weighs this against workload`,
    },
    {
      field: "working_days",
      label: "Working days",
      control: "json",
      enforcement: {
        kind: "ui-only",
        why: "Pydantic says list[str]; a value the scheduler does not recognise silently never matches",
      },
      caption: "e.g. mon, tue, wed, thu, fri · overrides the organisation default",
    },
  ],
  csv: {
    columns: [
      "email",
      "name",
      "role",
      "department",
      "designation",
      "phone",
      "whatsapp_number",
      "max_open_tasks",
      "working_days",
    ],
    example: {
      email: "ravi@your-domain.com",
      name: "Ravi Menon",
      role: "operations_lead",
      department: "operations",
      designation: "Commissioning lead",
      phone: "+919000000001",
      whatsapp_number: "+919000000001",
      max_open_tasks: "12",
      working_days: "mon|tue|wed|thu|fri",
    },
  },
};
