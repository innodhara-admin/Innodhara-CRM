/**
 * Theme selection. Three states, matching how the tokens are written:
 * "system" stamps nothing and lets `prefers-color-scheme` decide, while an
 * explicit choice stamps `data-theme` on the root so it wins in both
 * directions.
 *
 * Kept in `sessionStorage` alongside the two tokens (§4.2) rather than
 * `localStorage`, so nothing this console stores survives the tab.
 */
import { useCallback, useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark";

const KEY = "innodhara.theme";

function read(): Theme {
  const stored = sessionStorage.getItem(KEY);
  return stored === "light" || stored === "dark" ? stored : "system";
}

function apply(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(read);

  useEffect(() => {
    apply(theme);
  }, [theme]);

  const choose = useCallback((next: Theme) => {
    sessionStorage.setItem(KEY, next);
    setTheme(next);
  }, []);

  return [theme, choose];
}
