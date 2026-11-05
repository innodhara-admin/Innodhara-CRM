/**
 * Guards for the two ways a token system fails silently.
 *
 * Neither of these produces an error, a warning, or a build failure. A
 * misspelled CSS-module class renders with no class at all, and a token
 * redefined in light but not in dark renders the light value on a dark
 * background. Both look like "the CSS didn't apply" and both are found by
 * eye, late — which is exactly the kind of thing worth deriving instead of
 * re-checking by hand at every review.
 *
 * These parse the real files rather than importing them: Vitest runs in a node
 * environment (D11 — no component tests), so it does not process CSS Modules,
 * and a runtime import would give an empty object that passes everything.
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = dirname(HERE);

/**
 * Comments are stripped before anything is parsed. The first version of this
 * file did not, and `blockAfter(':root[data-theme="dark"]')` matched the
 * selector where the header comment *describes* it, then read the next `{` —
 * which was the light block. It reported 45 tokens against 14 and looked like a
 * palette bug. A parser that reads its own documentation is worse than no
 * parser.
 */
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

const tokensCss = strip(readFileSync(join(HERE, "tokens.css"), "utf-8"));
const primitivesCss = strip(readFileSync(join(HERE, "primitives.module.css"), "utf-8"));

/** Every `*.module.css` under src/, so a new stylesheet is covered on arrival. */
function cssModules(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = join(dir, e.name);
    if (e.isDirectory()) return cssModules(full);
    return e.isFile() && e.name.endsWith(".module.css") ? [full] : [];
  });
}

/** Every `.name` a stylesheet defines as a class selector. */
function definedClasses(css: string): Set<string> {
  return new Set(
    [...css.matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]),
  );
}

/** Every `--token` a block declares (left-hand side only). */
function declaredTokens(block: string): Set<string> {
  return new Set([...block.matchAll(/^\s*(--[\w-]+)\s*:/gm)].map((m) => m[1]));
}

/** Every `var(--token)` a stylesheet reads. */
function usedTokens(css: string): Set<string> {
  return new Set([...css.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]));
}

function blockAfter(css: string, marker: string): string {
  const start = css.indexOf(marker);
  expect(start, `missing block: ${marker}`).toBeGreaterThan(-1);
  const open = css.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(open, i);
    }
  }
  throw new Error(`unbalanced braces after ${marker}`);
}

/** Every .tsx under src/, so a new screen is covered without editing this file. */
function tsxFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = join(dir, e.name);
    if (e.isDirectory()) return tsxFiles(full);
    return e.isFile() && e.name.endsWith(".tsx") ? [full] : [];
  });
}

describe("css modules", () => {
  it("every class the components reference is actually defined", () => {
    // s.markerDone with no .markerDone renders class="undefined" and no style.
    const defined = definedClasses(primitivesCss);
    const missing: string[] = [];
    for (const file of tsxFiles(SRC)) {
      const source = readFileSync(file, "utf-8");
      for (const m of source.matchAll(/\b(?:s|styles)\.([A-Za-z][\w]*)\b/g)) {
        if (!defined.has(m[1])) missing.push(`${file.replace(SRC, "src")} → ${m[1]}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("finds the classes at all, so the check above cannot pass vacuously", () => {
    const defined = definedClasses(primitivesCss);
    expect(defined.size).toBeGreaterThan(30);
    expect(defined.has("provenanceUiOnly")).toBe(true);
  });

  it("checks components that import a stylesheet of their own, not only the shared one", () => {
    // The check above only knows `s.` and `styles.`, which reach
    // primitives.module.css through the re-export. A component with its own
    // module — Rail.tsx was the first — binds it to some other local name, and
    // a typo there was invisible to this suite until it resolved the import.
    const missing: string[] = [];
    let checked = 0;
    for (const file of tsxFiles(SRC)) {
      const source = readFileSync(file, "utf-8");
      for (const imp of source.matchAll(
        /import\s+(\w+)\s+from\s+"(\.[^"]*\.module\.css)"/g,
      )) {
        const [, local, relative] = imp;
        const defined = definedClasses(
          strip(readFileSync(join(dirname(file), relative), "utf-8")),
        );
        for (const use of source.matchAll(
          new RegExp(String.raw`\b${local}\.([A-Za-z][\w]*)\b`, "g"),
        )) {
          checked += 1;
          if (!defined.has(use[1])) {
            missing.push(`${file.replace(SRC, "src")} → ${local}.${use[1]}`);
          }
        }
      }
    }
    expect(missing).toEqual([]);
    expect(checked, "no component-scoped stylesheet was reached").toBeGreaterThan(0);
  });
});

describe("tokens", () => {
  const light = declaredTokens(blockAfter(tokensCss, "\n:root {"));

  it("defines every token any stylesheet reads", () => {
    // A typo'd var() name is not an error in CSS; the declaration is simply
    // dropped and the element renders unstyled.
    // Every stylesheet, found on disk rather than listed here: a new CSS module
    // that nothing enumerates is a new place for a typo'd var() to hide.
    const sheets = [tokensCss, ...cssModules(SRC).map((f) => strip(readFileSync(f, "utf-8")))];
    const used = new Set(sheets.flatMap((css) => [...usedTokens(css)]));
    const undefinedTokens = [...used].filter((t) => !light.has(t));
    expect(undefinedTokens).toEqual([]);
    expect(used.size).toBeGreaterThan(20);
    expect(cssModules(SRC).length, "no CSS modules found").toBeGreaterThan(1);
  });

  it("redefines the same token set in both dark blocks", () => {
    // System dark and the explicit toggle must not drift: a colour redefined in
    // one and forgotten in the other is a bug that only appears for whichever
    // half of the users takes the other path.
    const systemDark = declaredTokens(
      blockAfter(tokensCss, ':root:not([data-theme="light"])'),
    );
    const explicitDark = declaredTokens(blockAfter(tokensCss, ':root[data-theme="dark"]'));
    expect([...systemDark].sort()).toEqual([...explicitDark].sort());
    expect(systemDark.size).toBeGreaterThan(8);
  });

  it("gives every dark override a light definition to override", () => {
    // §9: light is the base, dark redefines VALUES ONLY. A colour whose only
    // definition lives inside a dark block is undefined for light readers.
    const dark = declaredTokens(blockAfter(tokensCss, ':root[data-theme="dark"]'));
    const orphans = [...dark].filter((t) => !light.has(t));
    expect(orphans).toEqual([]);
  });

  it("keeps the product name in exactly one place (D15)", () => {
    // The name is a token so reversing it to YuviPep is a one-line change.
    expect(light.has("--product-name")).toBe(true);
    const literals = tsxFiles(SRC)
      .map((f) => [f, readFileSync(f, "utf-8")] as const)
      .filter(([, src]) => src.includes("Innodhara"))
      .map(([f]) => f.replace(SRC, "src"));
    expect(literals, "the product name belongs in tokens.css, not in a component")
      .toEqual([]);
  });
});
