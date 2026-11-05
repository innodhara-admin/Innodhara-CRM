import { describe, expect, it } from "vitest";

import { CONFIG_DEFAULT_BASE_URL, defaultBaseUrl } from "./baseUrl";

/**
 * The console is served by the backend it talks to (`app/main.py` mounts the
 * bundle at `/dashboard`), so when it is running from there the address of the
 * API is already known: it is this page's own origin. Shipping
 * `127.0.0.1:8000` as the answer meant every deployment that was not a laptop
 * pointed the console at the operator's own machine — and on a machine where
 * something else answers on 8000, at that instead.
 */
describe("the default backend address", () => {
  it("is this page's own origin when the backend is serving the console", () => {
    expect(
      defaultBaseUrl({ origin: "https://setup.example.com", pathname: "/dashboard/" }),
    ).toBe("https://setup.example.com");
  });

  it("keeps a non-default port, which is how the backend is usually run", () => {
    expect(
      defaultBaseUrl({ origin: "http://10.0.0.4:9010", pathname: "/dashboard/" }),
    ).toBe("http://10.0.0.4:9010");
  });

  it("recognises the mount from a deep link inside it", () => {
    expect(
      defaultBaseUrl({ origin: "https://setup.example.com", pathname: "/dashboard/index.html" }),
    ).toBe("https://setup.example.com");
  });

  it("recognises the mount with no trailing slash", () => {
    expect(
      defaultBaseUrl({ origin: "https://setup.example.com", pathname: "/dashboard" }),
    ).toBe("https://setup.example.com");
  });

  /**
   * A path segment, not a string prefix — the same distinction the storage
   * traversal fix turns on. `/dashboardish` is a different application.
   */
  it("does not match a path that merely starts with the same letters", () => {
    expect(
      defaultBaseUrl({ origin: "https://setup.example.com", pathname: "/dashboardish/" }),
    ).toBe(CONFIG_DEFAULT_BASE_URL);
  });

  it("falls back to config.py's own default on the vite dev server", () => {
    expect(defaultBaseUrl({ origin: "http://localhost:5173", pathname: "/" })).toBe(
      CONFIG_DEFAULT_BASE_URL,
    );
  });

  it("falls back when opened from the filesystem, where origin is null", () => {
    expect(defaultBaseUrl({ origin: "null", pathname: "/dashboard/" })).toBe(
      CONFIG_DEFAULT_BASE_URL,
    );
  });

  it("falls back when there is no location at all", () => {
    expect(defaultBaseUrl(undefined)).toBe(CONFIG_DEFAULT_BASE_URL);
  });
});
