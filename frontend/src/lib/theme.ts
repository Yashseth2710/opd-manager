/**
 * Light, dark, or whatever the device is set to.
 *
 * The choice lives in this browser only. It is a preference about a screen,
 * not about the person, and a clinic's shared front-desk computer should not
 * follow one receptionist's taste onto everybody else's phone.
 */
export type Theme = "light" | "dark" | "system";

export const THEMES: Theme[] = ["light", "dark", "system"];

const KEY = "opd.theme";

export function storedTheme(): Theme {
  try {
    const saved = window.localStorage.getItem(KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

export function chooseTheme(theme: Theme) {
  try {
    if (theme === "system") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, theme);
  } catch {
    // A browser that refuses storage still gets the change for this visit.
  }
  applyTheme(theme);
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: theme }));
}

export const CHANGED = "opd:theme";

/**
 * Runs before the page paints, so a dark choice never flashes light first.
 * Kept tiny and free of imports: it is inlined into the document head.
 */
export const EARLY_THEME = `try{var t=localStorage.getItem("${KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export { KEY as THEME_KEY };
