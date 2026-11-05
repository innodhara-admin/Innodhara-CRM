/**
 * The WhatsApp panel's decisions (4 Nov 2026): what state to report and which
 * one thing to warn about. The panel itself only renders these.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { SettingsRead, type Settings } from "../api/reads";
import { kindLabel, whatsappState } from "./whatsappPanel";

const FIXTURE = join(dirname(fileURLToPath(import.meta.url)), "..", "api", "__fixtures__", "settings.json");
const base: Settings = SettingsRead.parse(JSON.parse(readFileSync(FIXTURE, "utf-8")));
const ORIGIN = "https://crm.example";

function settings(over: Partial<Settings>): Settings {
  return { ...base, ...over };
}

describe("whatsappState", () => {
  it("reads an unknown provider as WhatsApp off", () => {
    const st = whatsappState(settings({ whatsapp_provider: "telegram" }), ORIGIN);
    expect(st.provider).toBe("off");
    expect(st.sending).toBe(false);
    expect(st.warning).toMatch(/off/i);
  });

  it("asks for credentials when Wati is chosen without them", () => {
    const st = whatsappState(settings({ whatsapp_provider: "wati", whatsapp_credentials_stored: false }), ORIGIN);
    expect(st.sending).toBe(false);
    expect(st.warning).toMatch(/Wati/);
  });

  it("says messages only go to a file while the server is in dry run", () => {
    const st = whatsappState(
      settings({ whatsapp_provider: "wati", whatsapp_credentials_stored: true, whatsapp_mode: "dry_run" }),
      ORIGIN,
    );
    expect(st.sending).toBe(false);
    expect(st.warning).toMatch(/WHATSAPP_MODE/);
  });

  it("is sending when both halves hold, and warns only about documents", () => {
    const st = whatsappState(
      settings({
        whatsapp_provider: "wati",
        whatsapp_credentials_stored: true,
        whatsapp_mode: "cloud_api",
        public_base_url_set: false,
        whatsapp_webhook_path: "/api/v1/webhooks/wati/abc",
      }),
      ORIGIN,
    );
    expect(st.sending).toBe(true);
    expect(st.warning).toMatch(/PUBLIC_BASE_URL/);
    expect(st.webhookUrl).toBe("https://crm.example/api/v1/webhooks/wati/abc");
  });

  it("has nothing to warn about when everything is set", () => {
    const st = whatsappState(
      settings({
        whatsapp_provider: "meta",
        whatsapp_credentials_stored: true,
        whatsapp_mode: "cloud_api",
        public_base_url_set: true,
      }),
      ORIGIN,
    );
    expect(st.warning).toBeNull();
    expect(st.webhookUrl).toBeNull();
  });

  it("never uses a long dash in what it says", () => {
    for (const over of [
      {},
      { whatsapp_provider: "wati" },
      { whatsapp_provider: "wati", whatsapp_credentials_stored: true },
      { whatsapp_provider: "wati", whatsapp_credentials_stored: true, whatsapp_mode: "cloud_api" },
    ] as Partial<Settings>[]) {
      expect(whatsappState(settings(over), ORIGIN).warning ?? "").not.toMatch(/[–—]/);
    }
  });
});

describe("kindLabel", () => {
  it("reads like words", () => {
    expect(kindLabel("task_assigned")).toBe("Task assigned");
    expect(kindLabel("daily_brief")).toBe("Morning brief");
    expect(kindLabel("approval_waiting")).toBe("Approval waiting");
  });
});
