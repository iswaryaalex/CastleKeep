/*
 * critters.js - the five faces.
 *
 * Same contract as dragon.js: critterSvg(species, state) hands back a 22x22
 * crisp-edges SVG, so everything .avatar already does - the sizes, the radii,
 * the tile backgrounds - keeps working with no CSS changes.
 *
 * Unlike dragon.js, this is NOT a dump from a mockup generator and IS meant to
 * be hand-edited. The art is twenty-two strings of twenty-two characters per
 * species, one character per pixel, over a small named palette. A row is
 * readable as a row, a colour change is one palette entry, and a new species
 * is a palette plus five rows of ears.
 *
 * Only the ears and the palette differ between species, on purpose. Five
 * animals drawn to five different proportions look like five clip-art assets
 * that happen to share a screen; five drawn on one armature look like a set.
 * Signature details - the owl's beak, the axolotl's gill fronds - go in
 * `overlay`, which replaces whole rows by index.
 *
 *   .  transparent      w  eye white       p  pink: nose, inner ear
 *   o  outline          e  pupil           a  accent: fronds, tufts
 *   b  body             s  body shade      l  light: muzzle, chest
 */

const W = 22;

/* Rows 0-4. Everything above the brow: this is the whole silhouette. */
const EARS = {
  // Fox and cat sit next to each other in the picker, so they are drawn
  // against each other rather than in isolation: the fox gets broad, rounded,
  // three-wide ears and the cat gets one-pixel points two rows taller. At
  // 28px in the rail that difference is the whole silhouette.
  fox: [
    "......................",
    "...ooo..........ooo...",
    "..obbbo........obbbo..",
    "..obbpbo......obpbbo..",
    "..obbpbboooooobbpbbo..",
  ],
  cat: [
    "...o..............o...",
    "...oo............oo...",
    "..obpo..........opbo..",
    "..obpbo........obpbo..",
    "..obbpboooooooobpbbo..",
  ],
  owl: [
    "......................",
    "....o............o....",
    "...obo..........obo...",
    "...obbo........obbo...",
    "..obbbboooooooobbbbo..",
  ],
  bunny: [
    "....obbo......obbo....",
    "....obpo......obpo....",
    "....obpo......obpo....",
    "....obbo......obbo....",
    "..oobbboooooooobbboo..",
  ],
  axolotl: [
    "......................",
    "......................",
    "......................",
    ".....oooooooooooo.....",
    "...oobbbbbbbbbbbboo...",
  ],
};

/* Rows 5-21, shared. Rows 9, 10 and 13 are placeholders - the state tables
   below replace them - but they are drawn here anyway so that the armature
   reads as a face on its own when you are editing it. */
const BODY = [
  "..obbbbbbbbbbbbbbbbo..",   //  5
  "..obbbbbbbbbbbbbbbbo..",   //  6
  "..obbbbbbbbbbbbbbbbo..",   //  7
  "..obbbbbbbbbbbbbbbbo..",   //  8
  "..obbwwbbbbbbbbwwbbo..",   //  9  eyes, upper
  "..obbweebbbbbbeewbbo..",   // 10  eyes, pupils
  "..obbbbbbllllbbbbbbo..",   // 11
  "...obbbbllllllbbbbo...",   // 12
  "...obbbllppppllbbbo...",   // 13  muzzle and mouth
  "....obbllllllllbbo....",   // 14
  ".....oobbbbbbbboo.....",   // 15
  ".......oobbbboo.......",   // 16  neck
  "......obbbbbbbbo......",   // 17
  ".....obbllllllbbo.....",   // 18  chest
  ".....obbllllllbbo.....",   // 19
  ".....oobbbbbbbboo.....",   // 20
  ".......oooooooo.......",   // 21
];

const BODY_FROM = 5;
const EYE_UPPER = 9, EYE_LOWER = 10, MOUTH = 13;

/* A state is three rows. Keeping it to three is what stops six states from
   becoming six full redraws that drift apart the first time anybody moves an
   ear. */
const EYES = {
  idle:     ["..obbwwbbbbbbbbwwbbo..", "..obbweebbbbbbeewbbo.."],
  working:  ["..obbwwbbbbbbbbwwbbo..", "..obbweebbbbbbeewbbo.."],
  alert:    ["..obbwwbbbbbbbbwwbbo..", "..obbweebbbbbbeewbbo.."],
  thinking: ["..obbwwbbbbbbbbwwbbo..", "..obbeewbbbbbbweebbo.."],
  happy:    ["..obbeebbbbbbbbeebbo..", "..obbbbbbbbbbbbbbbbo.."],
  asleep:   ["..obbbbbbbbbbbbbbbbo..", "..obbooobbbbbbooobbo.."],
};

const MOUTHS = {
  idle:     "...obbbllppppllbbbo...",
  working:  "...obbbllooppllbbbo...",
  alert:    "...obbbllboobllbbbo...",
  thinking: "...obbbllppbbllbbbo...",
  happy:    "...obbblloooollbbbo...",
  asleep:   "...obbbllbppbllbbbo...",
};

/* Signature details, by row index. */
const OVERLAY = {
  owl: {
    // A beak where the muzzle would be. An owl without one reads as a cat.
    11: "..obbbbbbppppbbbbbbo..",
    12: "...obbbbbppppbbbbbo...",
  },
  axolotl: {
    // Gill fronds, outside the head outline. The only species that uses the
    // two outermost columns, which is exactly why it is recognisable at 28px.
    6: ".aobbbbbbbbbbbbbbbboa.",
    7: "aaobbbbbbbbbbbbbbbboaa",
    8: ".aobbbbbbbbbbbbbbbboa.",
  },
};

const PALETTE = {
  fox:     { o: "#5A2E12", b: "#E8834A", s: "#C9663A", l: "#FFF1E2",
             w: "#FFFFFF", e: "#3A2415", p: "#F2A9A0", a: "#FFD9A8" },
  cat:     { o: "#2E2A38", b: "#8D93A8", s: "#6E7489", l: "#F3F1F8",
             w: "#FFFFFF", e: "#2A2636", p: "#EFA8B8", a: "#C9CEDD" },
  owl:     { o: "#1F3348", b: "#5A86A8", s: "#44688A", l: "#FDF3DC",
             w: "#FFFFFF", e: "#1B2A3A", p: "#F0B254", a: "#9CC2DC" },
  bunny:   { o: "#5B4436", b: "#EFDCC4", s: "#D8C0A6", l: "#FFFBF5",
             w: "#FFFFFF", e: "#4A382C", p: "#F2A7B8", a: "#FFD5DF" },
  axolotl: { o: "#6E2F4E", b: "#F7A8C9", s: "#E184AE", l: "#FFF0F6",
             w: "#FFFFFF", e: "#4F2038", p: "#E0527F", a: "#FF8FC0" },
};

/* What onboarding draws the cards from. Order is the order of the picker. */
export const CRITTERS = [
  { id: "fox",     name: "Fox",     blurb: "Quick, nosy, good at finding things." },
  { id: "cat",     name: "Cat",     blurb: "Precise. Will not be hurried." },
  { id: "owl",     name: "Owl",     blurb: "Up all night, sees the whole field." },
  { id: "bunny",   name: "Bunny",   blurb: "Twitchy ears. Notices everything." },
  { id: "axolotl", name: "Axolotl", blurb: "Unbothered. Faintly amused." },
];

export const CRITTER_IDS = CRITTERS.map((c) => c.id);
export const CRITTER_STATES =
  ["idle", "thinking", "working", "alert", "happy", "asleep"];

export function critterName(species) {
  const c = CRITTERS.find((x) => x.id === species);
  return c ? c.name : "Fox";
}

/* The body colour, for borders and glows that want to match the avatar. */
export function critterColor(species, key) {
  return (PALETTE[species] || PALETTE.fox)[key || "b"];
}

function rows(species, state) {
  const ears = EARS[species] || EARS.fox;
  const out = ears.concat(BODY);
  const [upper, lower] = EYES[state] || EYES.idle;
  out[EYE_UPPER] = upper;
  out[EYE_LOWER] = lower;
  out[MOUTH] = MOUTHS[state] || MOUTHS.idle;
  // Last, so a species detail wins over the shared armature AND over the
  // state - the owl's beak must survive every expression it can wear.
  const over = OVERLAY[species] || {};
  for (const i of Object.keys(over)) out[i] = over[i];
  return out;
}

/* Run-length, not one rect per pixel. A 22x22 grid is 484 cells and roughly
   90 runs, and this gets rebuilt on every avatar on every hydrate. */
function paint(grid, pal) {
  let svg = "";
  for (let y = 0; y < grid.length; y++) {
    const row = grid[y];
    let x = 0;
    while (x < W) {
      const ch = row[x];
      if (ch === "." || ch === undefined) { x++; continue; }
      let run = 1;
      while (x + run < W && row[x + run] === ch) run++;
      const fill = pal[ch];
      if (fill) {
        svg += `<rect x="${x}" y="${y}" width="${run}" height="1" fill="${fill}"/>`;
      }
      x += run;
    }
  }
  return svg;
}

export function critterSvg(species, state, cls) {
  const pal = PALETTE[species] || PALETTE.fox;
  const body = paint(rows(PALETTE[species] ? species : "fox", state), pal);
  return `<svg class="${cls || ""}" viewBox="0 0 22 22" ` +
         `shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg">` +
         `${body}</svg>`;
}
