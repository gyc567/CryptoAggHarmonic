"use client";

import { useEffect, useState, useCallback } from "react";

type Theme = "light" | "dark" | "system";

const STORAGE_KEY = "cryptoagg-theme";

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("light");

  useEffect(() => {
    const stored = (localStorage.getItem(STORAGE_KEY) as Theme) || "system";
    setThemeState(stored);
    applyTheme(stored);
  }, []);

  const applyTheme = useCallback((value: Theme) => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");

    let resolvedValue: "light" | "dark" = "light";
    if (value === "system") {
      resolvedValue = window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    } else {
      resolvedValue = value;
    }

    root.classList.add(resolvedValue);
    setResolved(resolvedValue);
  }, []);

  const setTheme = useCallback(
    (value: Theme) => {
      localStorage.setItem(STORAGE_KEY, value);
      setThemeState(value);
      applyTheme(value);
    },
    [applyTheme]
  );

  useEffect(() => {
    const listener = (e: MediaQueryListEvent) => {
      if (theme === "system") {
        applyTheme("system");
      }
    };
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", listener);
    return () =>
      window
        .matchMedia("(prefers-color-scheme: dark)")
        .removeEventListener("change", listener);
  }, [theme, applyTheme]);

  return { theme, resolved, setTheme };
}
