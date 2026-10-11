"""
critters.py - the four CastleKeep agent sprites, 22x22 pixel art.

Same conventions as the dragon already in ui/dragon.js: a 22x22 grid, one dark
outline tone, three body tones, a warm accent pair and a cream. Flat <rect>
only, run-length merged along x, shape-rendering crispEdges, no groups, so the
result survives being rendered anywhere.

Each creature declares one grid and two small deltas rather than three full
frames: the eye band it swaps in to blink, and a box it nudges for its one
signature move. Hand-maintaining three 22-line grids per creature is how the
frames drift apart.

    python3 critters.py          # writes critters.js and the preview PNGs
"""

import io
import json
import os
import re
import subprocess
import sys

# --------------------------------------------------------------- palettes
#
# Four hues far enough apart to tell apart at 30px in a vertical list, all at
# roughly the dragon's saturation so the rail does not look like a carnival.
# Letters mean the same thing in every palette: G outline, D/L/K body dark to
# light, R/W/Y accent dark to light, M cream.

PALETTES = {
    "dragon": dict(G="#13342B", D="#2C7E60", L="#41A77D", K="#6FC79C",
                   R="#CC6044", W="#E8795A", Y="#F4A089", M="#FBE6C8"),
    "owl":    dict(G="#33241A", D="#8A5F33", L="#B07F45", K="#D2A163",
                   R="#C9802A", W="#E8A24A", Y="#EFC894", M="#FBECD2"),
    "cat":    dict(G="#1D2A36", D="#44627E", L="#5E86A6", K="#8CB3D0",
                   R="#C96B7A", W="#E88B99", Y="#F2B2BB", M="#F6F0E4"),
    "bird":   dict(G="#2B1B36", D="#6B4080", L="#8E5EA6", K="#B68ACB",
                   R="#D9922C", W="#F2B33D", Y="#F7D083", M="#F7EAD6"),
}

# ------------------------------------------------------------------ grids

DRAGON = """
......................
....W............W....
....WW..........WW....
.....WGGGGGGGGGGW.....
.....GKKKKLLLLLDG.....
....GK.GGLLLL.GGLG....
....GL.GGLLLL.GGLG....
....GLGGGLLLLGGGLG....
....GLGGGLLLLGGGLG....
....GYYLMMMMMMLYYG....
....GLLLMGMMGMLLLG....
.....GDDMMGGMMDDG.....
......GGGGGGGGGG......
.......GGGGGGGG.......
.....WWGLMMMMLGWW.....
...RWWWGLMMMMLGWWWR...
....RWWGLMMMMLGWWR....
.......GLMMMMLGLLG....
.......GGGGGGGG.LLG...
......GMMG..GMMG.LLG..
......GGGG..GGGG..WW..
...................R..
"""

# The dragon's shut eyes come straight from the asleep frame already shipped in
# ui/dragon.js, so the blink here and the blink on the launch screen agree.
DRAGON_SHUT = {
    5: "....GKLLLLLLLLLLLG....",
    6: "....GLLLLLLLLLLLLG....",
    8: "....GLLLLLLLLLLLLG....",
}

OWL = """
......................
......................
....GG........GG......
...GKKG......GKKG.....
...GKLLGGGGGGLLKG.....
..GKLLLLLLLLLLLLKG....
..GLLMMMMLLMMMMLLG....
..GLMMGGMMMMGGMMLG....
..GLMMGGMWWMGGMMLG....
..GLLMMMMWWMMMMLLG....
..GLLLLLMWWMLLLLLG....
..GLLLMMMMMMMMLLLG....
..GLLMMMMMMMMMMLLG....
..GLLMMMMMMMMMMLLG....
..GLLMMMMMMMMMMLLG....
...GLMMMMMMMMMMLG.....
...GGLLMMMMMMLLGG.....
.....GGLLLLLLGG.......
.......GWWWWG.........
......GWWGGWWG........
......GGG..GGG........
......................
"""

OWL_SHUT = {
    7: "..GLMMMMMMMMMMMMLG....",
    8: "..GLMGGMMWWMMGGMLG....",
}

CAT = """
......................
....G........G........
....GG......GG........
...GKLG....GLKG.......
...GLLLGGGGLLLG.......
..GLLLLLLLLLLLLG......
..GLGMLLLLLLMGLG......
..GLGGLLLLLLGGLG......
..GLLLLLWWLLLLLG......
..GLLLMMMMMMLLLG......
...GGLMMMMMMLGG.......
....GLLMMMMLLG........
....GLLMMMMLLG..GGGG..
....GLLMMMMLLG..GKLG..
....GLLMMMMLLG..GLLG..
....GLLMMMMLLG.GLLG...
....GLLMMMMLLGGLLG....
....GLLLLLLLLG........
....GGLLGGLLGG........
.....GMMG.GMMG........
.....GGGG.GGGG........
......................
"""

CAT_SHUT = {
    6: "..GLLLLLLLLLLLLG......",
    7: "..GLGGLLLLLLGGLG......",
}

# Narrow and upright, where the owl is wide and squat. At 30px in a list the
# silhouette is the only thing doing the work, so two round birds in warm
# colours would read as the same creature twice.
BIRD = """
......................
.........G............
........GKG...........
.......GLLLG..........
......GKLLLLKG........
.....GLLLLLLLLG.......
.....GLMGLLGMLG.......
.....GLMGLLGMLG.......
.....GLLLWWLLLG.......
......GLLWWLLG........
......GLLLLLG.........
.....GLLLLLLLLG.......
....GDGLMMMMLGDG......
...GDDGMMMMMMGDDG.....
...GDDGMMMMMMGDDG.....
....GDGLMMMMLGDG......
.....GGLLMMLLGG.......
.......GGLLGG.........
.......GWG.GWG........
.......GWG.GWG........
......GWWG.GWWG.......
......................
"""

BIRD_SHUT = {
    6: ".....GLLLLLLLLG.......",
    7: ".....GLGGLLGGLG.......",
}

# ------------------------------------------------------------------ moves
#
# One small nudge each, and the same nudge every time. A rail of four avatars
# all doing something different every few seconds is a distraction; a rail of
# four avatars each doing one familiar thing is furniture you stop noticing,
# which is the point.

CREATURES = {
    "dragon": dict(
        grid=DRAGON, shut=DRAGON_SHUT, says="wings lift",
        # Both wings, not one. Lifting a single wing reads as a glitch.
        move={"shift": [((3, 14, 7, 18), 0, -1), ((15, 14, 19, 18), 0, -1)]},
    ),
    "owl": dict(
        grid=OWL, shut=OWL_SHUT, says="eyes slide",
        # Written as rows, not a shift: sliding the pupils has to backfill the
        # cream they came off, and a shift only ever moves cells.
        move={"rows": {7: "..GLMGGMMMMGGMMMLG....",
                       8: "..GLMGGMMWWGGMMMLG...."}},
    ),
    "cat": dict(
        grid=CAT, shut=CAT_SHUT, says="tail flicks",
        # Only the upper tail swings. The root stays put, so the bend reads as
        # a joint rather than the whole tail sliding off the cat.
        move={"shift": [((16, 11, 21, 15), 1, 0)]},
    ),
    "bird": dict(
        grid=BIRD, shut=BIRD_SHUT, says="hops",
        move={"shift": [((0, 0, 22, 22), 0, -1)]},
    ),
}

SIZE = 22


# ------------------------------------------------------------------- build

def parse(grid):
    """Grid text to {(x, y): letter}. Blank-tolerant, so the literals above can
    keep their leading newline and stay readable in the source."""
    rows = [r for r in grid.splitlines() if r.strip()]
    if len(rows) != SIZE:
        raise ValueError("grid has %d rows, want %d" % (len(rows), SIZE))
    cells = {}
    for y, row in enumerate(rows):
        if len(row) > SIZE:
            raise ValueError("row %d is %d wide, want %d" % (y, len(row), SIZE))
        for x, ch in enumerate(row.ljust(SIZE, ".")):
            if ch != ".":
                cells[(x, y)] = ch
    return cells


def apply_rows(cells, patch):
    """Overwrite whole rows. Used for the shut-eye frames, where redrawing the
    two or three affected lines is clearer than describing a diff."""
    out = {k: v for k, v in cells.items() if k[1] not in patch}
    for y, row in patch.items():
        for x, ch in enumerate(row.ljust(SIZE, ".")[:SIZE]):
            if ch != ".":
                out[(x, y)] = ch
    return out


def shift(cells, box, dx, dy):
    """Move everything inside box by (dx, dy). Anything pushed off the canvas is
    dropped rather than wrapped, which is what you want for a hop."""
    x0, y0, x1, y1 = box
    out, moving = {}, {}
    for (x, y), ch in cells.items():
        if x0 <= x < x1 and y0 <= y < y1:
            moving[(x, y)] = ch
        else:
            out[(x, y)] = ch
    for (x, y), ch in moving.items():
        nx, ny = x + dx, y + dy
        if 0 <= nx < SIZE and 0 <= ny < SIZE:
            out[(nx, ny)] = ch
    return out


def to_rects(cells, palette):
    """Run-length merge along x, then emit flat rects. Merging cuts the rect
    count by roughly two thirds, which matters when four of these are animating
    at once in a sidebar."""
    out = []
    for y in range(SIZE):
        x = 0
        while x < SIZE:
            ch = cells.get((x, y))
            if not ch:
                x += 1
                continue
            run = 1
            while x + run < SIZE and cells.get((x + run, y)) == ch:
                run += 1
            out.append('<rect x="%d" y="%d" width="%d" height="1" fill="%s"/>'
                       % (x, y, run, palette[ch]))
            x += run
    return "".join(out)


def frames(name):
    spec = CREATURES[name]
    pal = PALETTES[name]
    base = parse(spec["grid"])
    unknown = sorted(set(base.values()) - set(pal))
    if unknown:
        raise ValueError("%s uses undeclared letters %s" % (name, unknown))

    moved = base
    for box, dx, dy in spec["move"].get("shift", []):
        moved = shift(moved, box, dx, dy)
    if spec["move"].get("rows"):
        moved = apply_rows(moved, spec["move"]["rows"])

    blinked = apply_rows(base, spec["shut"])
    if blinked == base:
        raise ValueError("%s blink frame is identical to idle" % name)
    if moved == base:
        raise ValueError("%s move frame is identical to idle" % name)
    return {
        "idle": to_rects(base, pal),
        "blink": to_rects(blinked, pal),
        "move": to_rects(moved, pal),
    }


def svg(body, px=22, cls=""):
    return ('<svg viewBox="0 0 22 22" width="%d" height="%d" %s '
            'shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg">'
            '%s</svg>' % (px, px, ('class="%s"' % cls) if cls else "", body))


# ------------------------------------------------------------------ output

def write_js(path):
    data = {n: frames(n) for n in CREATURES}
    meta = {n: {"move": CREATURES[n]["says"]} for n in CREATURES}
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("// Pixel grids generated by workshop tooling. Do not "
                "hand-edit: run critters.py.\n")
        f.write("// Each creature has three frames. idle is the resting pose, "
                "blink shuts the\n// eyes for a few hundred ms, move is the one "
                "small thing it does.\n")
        f.write("export const CRITTERS = %s;\n\n"
                % json.dumps(data, indent=0, sort_keys=True))
        f.write("export const CRITTER_MOVES = %s;\n\n"
                % json.dumps(meta, sort_keys=True))
        f.write('''export function critterSvg(name, frame, px, cls) {
  const body = (CRITTERS[name] || CRITTERS.dragon)[frame || "idle"];
  return '<svg viewBox="0 0 22 22" width="' + (px || 22) + '" height="' +
    (px || 22) + '" class="' + (cls || "") +
    '" shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg">' +
    body + '</svg>';
}
''')
    return data


def preview(data, path, scale=7):
    """One sheet: every creature, every frame, on the app background. Looking at
    this is the only way to catch a misplaced pixel; the grids read fine in
    source and still come out cross-eyed."""
    names = list(CREATURES)
    cols = ["idle", "blink", "move"]
    pad, cell = 10, SIZE * scale
    w = pad + len(cols) * (cell + pad)
    h = pad + 18 + len(names) * (cell + pad + 16)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
             'shape-rendering="crispEdges">' % (w, h),
             '<rect width="%d" height="%d" fill="#FAF8F1"/>' % (w, h)]
    for ci, c in enumerate(cols):
        parts.append('<text x="%d" y="16" font-family="monospace" '
                     'font-size="12" fill="#6B6358">%s</text>'
                     % (pad + ci * (cell + pad), c))
    for ri, n in enumerate(names):
        top = 24 + ri * (cell + pad + 16)
        parts.append('<text x="%d" y="%d" font-family="monospace" '
                     'font-size="12" fill="#2A2721">%s  (%s)</text>'
                     % (pad, top + cell + 13, n, CREATURES[n]["says"]))
        for ci, c in enumerate(cols):
            x = pad + ci * (cell + pad)
            parts.append('<g transform="translate(%d,%d) scale(%d)">%s</g>'
                         % (x, top, scale, data[n][c]))
            parts.append('<rect x="%d" y="%d" width="%d" height="%d" fill="none" '
                         'stroke="#EDE7D8"/>' % (x, top, cell, cell))
    parts.append("</svg>")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "ui", "critters.js")
    data = write_js(out)
    print("wrote ui/critters.js")

    # --preview writes a contact sheet next to the script. It is not part of
    # the app and nothing links to it: it exists so that whoever edits a grid
    # can look at the result, which is the only way these ever get fixed.
    if "--preview" in sys.argv:
        preview(data, os.path.join(here, "_critters.svg"))
        try:
            import cairosvg
            cairosvg.svg2png(url=os.path.join(here, "_critters.svg"),
                             write_to=os.path.join(here, "_critters.png"))
            print("wrote _critters.svg and _critters.png")
        except ImportError:
            print("wrote _critters.svg (install cairosvg for the PNG)")
