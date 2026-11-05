/**
 * Delete this organisation — the typed confirmation. The rule must be the
 * server's (`app/services/org_delete.py::confirmation_matches`): the same
 * cases as `tests/test_org_delete.py::test_confirmation_matching`.
 */
import { describe, expect, it } from "vitest";

import { confirmationMatches, deletedMessage, expectedConfirmation } from "./orgDelete";

describe("expectedConfirmation", () => {
  it("is DELETE followed by the organisation's name", () => {
    expect(expectedConfirmation("YuviPep")).toBe("DELETE YuviPep");
  });
});

describe("confirmationMatches", () => {
  it.each([
    ["DELETE YuviPep", "YuviPep"],
    ["delete yuvipep", "YuviPep"],
    ["  DELETE   YuviPep ", "YuviPep"],
    ["delete northwind learning (DEMO)", "Northwind Learning (demo)"],
  ])("accepts %j for %j", (typed, name) => {
    expect(confirmationMatches(typed, name)).toBe(true);
  });

  it.each([
    ["DELETE Yuvip", "YuviPep"],
    ["DELETE YuviPep!", "YuviPep"],
    ["YuviPep", "YuviPep"],
    ["", "YuviPep"],
  ])("refuses %j for %j", (typed, name) => {
    expect(confirmationMatches(typed, name)).toBe(false);
  });
});

describe("deletedMessage", () => {
  it("says nothing is left only when the server found nothing left and compacted", () => {
    expect(deletedMessage("YuviPep", { remaining: {}, compacted: true })).toEqual({
      tone: "note",
      text: "YuviPep has been deleted. Nothing of it is left in the system.",
    });
  });

  it("says what is still there when the server's last count was not empty", () => {
    const m = deletedMessage("YuviPep", { remaining: { llm_usage: 2 }, compacted: true });
    expect(m.tone).toBe("blocked");
    expect(m.text).toContain("2 records");
    expect(m.text).not.toContain("Nothing of it is left");
  });

  it("says the database file was not cleaned when compaction did not finish", () => {
    const m = deletedMessage("YuviPep", { remaining: {}, compacted: false });
    expect(m.tone).toBe("warn");
    expect(m.text).not.toContain("Nothing of it is left");
  });
});
