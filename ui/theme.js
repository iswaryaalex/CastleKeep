/*
 * theme.js - which of the three token tables is in force.
 *
 * The theme lives in two places and that is deliberate, not an oversight:
 *
 *   profile.json  is the truth. It is what the participant chose, it survives
 *                 a new browser, and it is what the server hands back.
 *   localStorage  is a cache, read by an inline script in the <head> of every
 *                 page BEFORE the stylesheet is applied.
 *
 * Without the second one every page would paint parchment first and then flip
 * to moonlit when the first fetch came back - a white flash on a dark theme,
 * on every single navigation. The inline snippet below is small enough to
 * duplicate into each page's head, and it has to be inline: a module script
 * is deferred by definition, which is exactly too late.
 */

export const THEMES = [
  {
    id: "parchment",
    name: "Parchment",
    blurb: "Warm paper and ink. The original.",
    swatch: ["#FAF8F1", "#F5CE3E", "#3C6531"],
  },
  {
    id: "moonlit",
    name: "Moonlit Keep",
    blurb: "Deep indigo, lamplight, and the gold left on.",
    swatch: ["#11141E", "#F5CE3E", "#63AAE2"],
  },
  {
    id: "sakura",
    name: "Sakura Dawn",
    blurb: "Blush and lavender, first thing in the morning.",
    swatch: ["#FDF4F8", "#E7A2C4", "#6B5FA8"],
  },
];

export const THEME_IDS = THEMES.map((t) => t.id);
export const DEFAULT_THEME = "parchment";

const KEY = "castlekeep-theme";

export function themeName(id) {
  const t = THEMES.find((x) => x.id === id);
  return t ? t.name : THEMES[0].name;
}

/** Paint it. Safe to call on every hydrate - setting the same value twice
 *  does not repaint, and guessing wrong once is cheaper than tracking it. */
export function applyTheme(id) {
  const theme = THEME_IDS.includes(id) ? id : DEFAULT_THEME;
  if (document.documentElement.dataset.theme !== theme) {
    document.documentElement.dataset.theme = theme;
  }
  try { localStorage.setItem(KEY, theme); } catch (_) { /* private mode */ }
  return theme;
}

export function storedTheme() {
  try {
    const t = localStorage.getItem(KEY);
    return THEME_IDS.includes(t) ? t : DEFAULT_THEME;
  } catch (_) {
    return DEFAULT_THEME;
  }
}

/** Build the three swatch buttons. `onPick` gets the id; applying it is left
 *  to the caller, because onboarding also has to remember the choice for the
 *  profile it is about to POST and Settings has to save it straight away. */
export function themePicker(container, current, onPick) {
  container.innerHTML = "";
  for (const t of THEMES) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "themeswatch" + (t.id === current ? " on" : "");
    b.title = t.blurb;
    b.setAttribute("aria-label", t.name + " - " + t.blurb);

    const dots = document.createElement("span");
    dots.className = "themedots";
    for (const c of t.swatch) {
      const d = document.createElement("i");
      d.style.background = c;
      dots.appendChild(d);
    }
    b.appendChild(dots);

    const label = document.createElement("span");
    label.className = "themename";
    label.textContent = t.name;
    b.appendChild(label);

    b.addEventListener("click", () => {
      container.querySelectorAll(".themeswatch")
        .forEach((n) => n.classList.toggle("on", n === b));
      applyTheme(t.id);
      if (onPick) onPick(t.id);
    });
    container.appendChild(b);
  }
}

// Apply whatever the cache holds the moment this module runs, so a page that
// forgot the inline snippet still ends up on the right theme - a beat late,
// but right.
applyTheme(storedTheme());
