/**
 * Which checklist rows have a screen.
 *
 * One table rather than a switch inside `Checklist.tsx`, so a new screen is one
 * line. **All sixteen are present as of Task 20** — the map stays `Partial`
 * because that is what makes the "no screen yet" branch in `Checklist.tsx`
 * type-check, and a future item added to the manual would arrive without one.
 */
import type { ComponentType } from "react";

import type { ItemStatus } from "./status";
import { ApprovalRules } from "../screens/ApprovalRules";
import { Calendar } from "../screens/Calendar";
import { DemoTeams } from "../screens/DemoTeams";
import { InboundMail } from "../screens/InboundMail";
import { Integrations } from "../screens/Integrations";
import { MessageTemplates } from "../screens/MessageTemplates";
import { Playbooks } from "../screens/Playbooks";
import { Pricing } from "../screens/Pricing";
import { Programs } from "../screens/Programs";
import { ProposalTemplates } from "../screens/ProposalTemplates";
import { Retention } from "../screens/Retention";
import { Settings } from "../screens/Settings";
import { Skills } from "../screens/Skills";
import { Staff } from "../screens/Staff";
import { Vendors } from "../screens/Vendors";

export type ItemScreenProps = { status: ItemStatus };

export const ITEM_SCREENS: Partial<Record<number, ComponentType<ItemScreenProps>>> = {
  // 1 has no screen of its own: the organisation is created by the hand-off
  // (Task 14) and the rail's own overview says everything else there is to say.
  2: Staff,
  3: Skills,
  4: Programs,
  5: Pricing,
  6: ProposalTemplates,
  7: MessageTemplates,
  8: Playbooks,
  9: ApprovalRules,
  10: Settings,
  11: Integrations,
  12: Retention,
  13: DemoTeams,
  14: Calendar,
  15: Vendors,
  16: InboundMail,
};
