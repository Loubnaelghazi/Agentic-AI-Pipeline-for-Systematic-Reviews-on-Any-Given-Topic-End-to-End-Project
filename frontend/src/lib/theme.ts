export type Theme = "light" | "dark";

export function preferredTheme(): Theme {
  try {
    const saved = localStorage.getItem("folio-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Browser storage may be unavailable in private or restricted sessions.
  }
  return typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#141b18" : "#ffffff");
}

export function saveTheme(theme: Theme) {
  applyTheme(theme);
  try {
    localStorage.setItem("folio-theme", theme);
  } catch {
    // The current session can still use the selected theme without persistence.
  }
}
