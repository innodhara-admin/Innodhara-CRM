/**
 * Delete this organisation — the typed confirmation.
 *
 * Spec: docs/superpowers/specs/2026-10-28-org-delete-design.md (decision 2:
 * upper or lower case both accepted). The server decides; this only keeps the
 * button disabled until the server would agree. Same rule as
 * `app/services/org_delete.py::confirmation_matches`: any case, extra spaces
 * ignored, every other character must match.
 */

export function expectedConfirmation(orgName: string): string {
  return `DELETE ${orgName}`;
}

function normalised(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
}

export function confirmationMatches(typed: string, orgName: string): boolean {
  if (!typed || !orgName) return false;
  return normalised(typed) === normalised(expectedConfirmation(orgName));
}

export type DeletedMessage = { tone: "note" | "warn" | "blocked"; text: string };

/**
 * What the page says after a delete. "Nothing of it is left" only when the
 * server's last count found nothing AND the database file was compacted; a
 * claim the server did not make is never shown.
 */
export function deletedMessage(
  orgName: string,
  result: { remaining: Record<string, number>; compacted: boolean },
): DeletedMessage {
  const left = Object.values(result.remaining).reduce((a, b) => a + b, 0);
  if (left > 0) {
    return {
      tone: "blocked",
      text:
        `${orgName} was deleted, but ${left} record${left === 1 ? " was" : "s were"} ` +
        "still there at the end. Ask the developer to finish it with the delete script.",
    };
  }
  if (!result.compacted) {
    return {
      tone: "warn",
      text:
        `${orgName} has been deleted, but the server could not finish cleaning the ` +
        "database file. Ask the developer to check it.",
    };
  }
  return { tone: "note", text: `${orgName} has been deleted. Nothing of it is left in the system.` };
}
