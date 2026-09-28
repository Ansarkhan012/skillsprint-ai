"use client";

import { Moon, Sun } from "lucide-react";

/** Presentation preference only; stored per browser. Icons follow the .dark class via CSS. */
export function ThemeToggle() {
  function toggle() {
    const dark = document.documentElement.classList.toggle("dark");
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* storage unavailable */ }
  }
  return <button type="button" onClick={toggle} aria-label="Toggle dark mode" title="Toggle dark mode"
    className="flex size-10 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground hover:text-foreground">
    <Moon size={18} aria-hidden="true" className="dark:hidden" /><Sun size={18} aria-hidden="true" className="hidden dark:block" />
  </button>;
}
