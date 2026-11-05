/**
 * Regenerate the console's type layer, or verify it is current (`--check`).
 *
 *   openapi.json                    <- Dashboard/tools/dump_openapi.py
 *   vocabularies.generated.ts       <- same script (07_BUILD_PLAN.md A4)
 *   generated.ts                    <- openapi-zod-client, schemas-only
 *   constraints.generated.ts        <- tools/lift_constraints.mjs (A3)
 *
 * One Node process rather than chained npm scripts, so it behaves the same in
 * PowerShell, Git Bash and CI — `cd .. && python ...` in an npm script does not.
 *
 * `--check` regenerates into a temp directory and byte-compares. Wired as
 * `prebuild`, so `npm run build` fails when the backend has moved and the
 * client has not (06_DESIGN.md §3.2, mechanism 1).
 */
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, copyFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { liftFile } from "./lift_constraints.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const DASHBOARD = dirname(HERE);
const REPO = dirname(DASHBOARD);
const API = join(DASHBOARD, "src", "api");

const CHECK = process.argv.includes("--check");

// The four artefacts, in the order they are produced. All are committed.
const ARTEFACTS = [
  "openapi.json",
  "vocabularies.generated.ts",
  "generated.ts",
  "constraints.generated.ts",
];

const GENERATOR_BIN = join(DASHBOARD, "node_modules", "openapi-zod-client", "bin.js");
// schemas-only, not the default template: the default emits a Zodios client and
// pulls @zodios/core + axios in, while §4.1 needs a hand-written client with a
// settable base URL, per-call token choice and retry: 0 anyway. Measured on this
// spec: default 107 KB with a Zodios import, schemas-only 25 KB importing zod.
const TEMPLATE = join(
  DASHBOARD, "node_modules", "openapi-zod-client", "src", "templates", "schemas-only.hbs",
);

function run(label, cmd, args, opts = {}) {
  const res = spawnSync(cmd, args, { stdio: "inherit", ...opts });
  if (res.error) throw res.error;
  if (res.status !== 0) {
    console.error(`\n${label} failed with exit code ${res.status}`);
    process.exit(res.status ?? 1);
  }
}

/** Generate all four artefacts into `outDir`. */
function generate(outDir) {
  mkdirSync(outDir, { recursive: true });

  // 1 + 2 — the dumper writes openapi.json and vocabularies.generated.ts.
  // It imports app.main, so it runs from the repo root and needs no server.
  run("dump_openapi.py", process.env.PYTHON ?? "python",
      [join(HERE, "dump_openapi.py")], { cwd: REPO });

  const spec = join(API, "openapi.json");
  if (!existsSync(spec)) {
    console.error(`the dumper produced no ${spec}`);
    process.exit(1);
  }

  // 3 — Zod schemas from the spec.
  run("openapi-zod-client", process.execPath, [
    GENERATOR_BIN, spec,
    "-o", join(outDir, "generated.ts"),
    "--export-schemas",
    "-t", TEMPLATE,
  ], { cwd: DASHBOARD });

  // 4 — the constraints the generator dropped.
  liftFile(spec, join(outDir, "constraints.generated.ts"));

  // The dumper always writes in place; move its two outputs when generating
  // somewhere else. Nothing reads them from outDir except the comparison.
  if (outDir !== API) {
    for (const name of ["openapi.json", "vocabularies.generated.ts"]) {
      copyFileSync(join(API, name), join(outDir, name));
    }
  }
}

if (!CHECK) {
  generate(API);
  console.log("\ngenerated:");
  for (const name of ARTEFACTS) {
    const bytes = readFileSync(join(API, name), "utf-8").length;
    console.log(`  src/api/${name.padEnd(26)} ${bytes.toLocaleString()} chars`);
  }
  process.exit(0);
}

// ── --check ──────────────────────────────────────────────────────────────────
// The dumper overwrites the committed openapi.json and vocabularies file in
// place, so stash them first and restore whatever happens: a check must never
// mutate the working tree it is judging.
const missing = ARTEFACTS.filter((n) => !existsSync(join(API, n)));
if (missing.length) {
  console.error(`gen:check — never generated. Missing: ${missing.join(", ")}`);
  console.error("Run `npm run gen:api`.");
  process.exit(1);
}

const stash = mkdtempSync(join(tmpdir(), "gen-stash-"));
const fresh = mkdtempSync(join(tmpdir(), "gen-check-"));
let differing = null;
try {
  for (const name of ARTEFACTS) copyFileSync(join(API, name), join(stash, name));
  generate(fresh);
  for (const name of ARTEFACTS) {
    const committed = readFileSync(join(stash, name), "utf-8");
    const regenerated = readFileSync(join(fresh, name), "utf-8");
    if (committed !== regenerated) { differing = name; break; }
  }
} finally {
  for (const name of ARTEFACTS) {
    const stashed = join(stash, name);
    if (existsSync(stashed)) copyFileSync(stashed, join(API, name));
  }
  rmSync(stash, { recursive: true, force: true });
  rmSync(fresh, { recursive: true, force: true });
}

if (differing) {
  console.error(
    `\ngen:check FAILED — src/api/${differing} is not what the backend produces.\n` +
    "The API has moved and the generated client has not. Run `npm run gen:api`\n" +
    "and commit the result; do not edit a generated file by hand.",
  );
  process.exit(1);
}
console.log("gen:check OK — all four generated artefacts match the backend");
