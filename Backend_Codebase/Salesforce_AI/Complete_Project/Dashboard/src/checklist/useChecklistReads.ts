/**
 * The reads behind the rail — everything §5.2 derives a status from.
 *
 * `status.ts` is pure and takes its inputs as an argument; this is the only
 * place that goes and gets them. Keeping the two apart is what lets the
 * derivation be tested against recorded payloads instead of a running server.
 *
 * **Every list read is parsed through its shape from `reads.ts`.** A response
 * that no longer matches becomes a `DriftError` in `client.ts`, which arrives
 * here as an error and turns that item's status into `—` with the reason,
 * never `○` (A1).
 *
 * Items 5 and 6 are per-programme, so the two catalogue reads fan out over
 * `GET /admin/programs`. They are declared with `useQueries` and stay disabled
 * until the programme list has arrived — a fan-out over `[]` would resolve
 * instantly and report full coverage of nothing.
 */
import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { schemas } from "../api/generated";
import {
  ApprovalRulesRead,
  DemoTeamsRead,
  EmailTemplatesRead,
  MessageTemplatesRead,
  PlaybooksRead,
  PricingRead,
  ProgramsRead,
  ProposalTemplatesRead,
  SettingsRead,
  SkillsRead,
  VendorsRead,
  type Pricing,
  type ProposalTemplates,
} from "../api/reads";
import { isApiError } from "../api/errors";
import type { ChecklistReads, Read } from "./status";

const StaffRead = schemas.UserResponse.array();

/** The server's own words where there are any, and never an invented reason. */
function reason(error: unknown): string {
  if (isApiError(error)) return error.detail;
  if (error instanceof Error) return error.message;
  return "This read failed for a reason the console could not describe.";
}

function toRead<T>(query: UseQueryResult<T>): Read<T> {
  if (query.isError) return { state: "unreadable", why: reason(query.error) };
  if (query.data === undefined) return { state: "pending" };
  return { state: "ok", value: query.data };
}

/**
 * A fan-out is only as good as its worst leaf. One failing programme means the
 * coverage answer is unknown, not "partial" — reporting a partial would be an
 * invented fact about the programmes that did load.
 */
function toKeyedRead<T>(
  ids: string[],
  queries: Array<UseQueryResult<T>>,
  parent: Read<unknown>,
): Read<Record<string, T>> {
  if (parent.state !== "ok") return parent as Read<Record<string, T>>;
  const failed = queries.find((q) => q.isError);
  if (failed) return { state: "unreadable", why: reason(failed.error) };
  if (queries.some((q) => q.data === undefined)) return { state: "pending" };
  return {
    state: "ok",
    value: Object.fromEntries(ids.map((id, i) => [id, queries[i].data as T])),
  };
}

/**
 * `enabled` is the org session's existence. Every read below needs the
 * organisation token, so firing them without one produces twelve identical
 * "No org session is active" errors and twelve `—` rows, which reads as a
 * broken API rather than as "you are not signed in".
 */
export function useChecklistReads(enabled: boolean): ChecklistReads {
  const me = useQuery({
    queryKey: ["me"],
    enabled,
    queryFn: () => request(endpoints.me, { as: "org", shape: schemas.MeResponse }),
  });
  const staff = useQuery({
    queryKey: ["staff"],
    enabled,
    queryFn: () => request(endpoints.staff, { as: "org", shape: StaffRead }),
  });
  const skills = useQuery({
    queryKey: ["skills"],
    enabled,
    queryFn: () => request(endpoints.skills, { as: "org", shape: SkillsRead }),
  });
  const programs = useQuery({
    queryKey: ["programs"],
    enabled,
    queryFn: () => request(endpoints.programs, { as: "org", shape: ProgramsRead }),
  });
  const messageTemplates = useQuery({
    queryKey: ["messageTemplates"],
    enabled,
    queryFn: () =>
      request(endpoints.messageTemplates, { as: "org", shape: MessageTemplatesRead }),
  });
  const emailTemplates = useQuery({
    queryKey: ["emailTemplates"],
    enabled,
    queryFn: () =>
      request(endpoints.emailTemplates, { as: "org", shape: EmailTemplatesRead }),
  });
  const playbooks = useQuery({
    queryKey: ["playbooks"],
    enabled,
    queryFn: () => request(endpoints.playbooks, { as: "org", shape: PlaybooksRead }),
  });
  const approvalRules = useQuery({
    queryKey: ["approvalRules"],
    enabled,
    queryFn: () => request(endpoints.approvalRules, { as: "org", shape: ApprovalRulesRead }),
  });
  const settings = useQuery({
    queryKey: ["settings"],
    enabled,
    queryFn: () => request(endpoints.settings, { as: "org", shape: SettingsRead }),
  });
  const demoTeams = useQuery({
    queryKey: ["demoTeams"],
    enabled,
    queryFn: () => request(endpoints.demoTeams, { as: "org", shape: DemoTeamsRead }),
  });
  const vendors = useQuery({
    queryKey: ["vendors"],
    enabled,
    queryFn: () => request(endpoints.vendors, { as: "org", shape: VendorsRead }),
  });

  // Only active programmes are fanned out over: §5.2 items 5, 6 and 8 all ask
  // "every ACTIVE programme", and an archived one having no current rate card
  // is not a gap.
  const programIds = (programs.data ?? []).filter((p) => p.is_active).map((p) => p.id);

  const pricingQueries = useQueries({
    queries: programIds.map((id) => ({
      queryKey: ["pricing", id],
      queryFn: () => request(endpoints.pricing(id), { as: "org", shape: PricingRead }),
    })),
  });
  const templateQueries = useQueries({
    queries: programIds.map((id) => ({
      queryKey: ["proposalTemplates", id],
      queryFn: () =>
        request(endpoints.proposalTemplates(id), {
          as: "org",
          shape: ProposalTemplatesRead,
        }),
    })),
  });

  const programsRead = toRead(programs);

  return {
    me: toRead(me),
    staff: toRead(staff),
    skills: toRead(skills),
    programs: programsRead,
    pricing: toKeyedRead<Pricing>(programIds, pricingQueries, programsRead),
    proposalTemplates: toKeyedRead<ProposalTemplates>(
      programIds,
      templateQueries,
      programsRead,
    ),
    messageTemplates: toRead(messageTemplates),
    emailTemplates: toRead(emailTemplates),
    playbooks: toRead(playbooks),
    approvalRules: toRead(approvalRules),
    settings: toRead(settings),
    demoTeams: toRead(demoTeams),
    vendors: toRead(vendors),
  };
}
