import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // node, not jsdom: D11 rules out component tests, so nothing here needs a
    // DOM. The suites are generation, drift, import and status derivation.
    environment: "node",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.ts"],
  },
});
