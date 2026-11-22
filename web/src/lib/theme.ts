// Theme choice (dark, light or follow the device) and the chart palette read from the CSS
// tokens in globals.css, so canvas drawing uses the same colours as the rest of the page.

export type ThemeChoice = "system" | "dark" | "light";

export const THEME_KEY = "tl-theme";

/** Runs in <head> before first paint so the saved theme never flashes the wrong colours. */
export const THEME_INIT_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}`;

export function getThemeChoice(): ThemeChoice {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "dark" || t === "light" ? t : "system";
  } catch {
    return "system";
  }
}

export function setThemeChoice(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
  try {
    if (choice === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Storage blocked: the choice lasts for this page only.
  }
}

/** Calls `cb` when the theme in effect changes (user choice or the device setting). */
export function onThemeChange(cb: () => void): () => void {
  const observer = new MutationObserver(cb);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", cb);
  return () => {
    observer.disconnect();
    media.removeEventListener("change", cb);
  };
}

export type ChartPalette = {
  background: string;
  grid: string;
  text: string;
  bull: string;
  bear: string;
  primary: string;
  warn: string;
  muted: string;
  ink: string;
  raised: string;
  /** "r,g,b" for building rgba() fills. */
  rgb: { bull: string; bear: string; primary: string; warn: string; muted: string };
};

function toRgb(color: string): string {
  const hex = color.trim().replace("#", "");
  if (/^[0-9a-f]{6}$/i.test(hex)) {
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(",");
  }
  const m = color.match(/[\d.]+/g);
  return m ? m.slice(0, 3).join(",") : "128,128,128";
}

export function readChartPalette(): ChartPalette {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  const p = {
    background: v("--surface"),
    grid: v("--line"),
    text: v("--text-2"),
    bull: v("--bull"),
    bear: v("--bear"),
    primary: v("--primary"),
    warn: v("--warn"),
    muted: v("--text-2"),
    ink: v("--text"),
    raised: v("--surface-2"),
  };
  return {
    ...p,
    rgb: {
      bull: toRgb(p.bull),
      bear: toRgb(p.bear),
      primary: toRgb(p.primary),
      warn: toRgb(p.warn),
      muted: toRgb(p.muted),
    },
  };
}
