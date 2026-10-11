"""Throwaway. Draws the app rail on its own at 2x so the icons, the selected
marker and the hover fill can be judged at the size they are actually drawn.
Reads the colours from tokens.css and the icons from style.css, so it cannot
disagree with the stylesheet. Delete when done."""

import io, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
T = dict(re.findall(r'(--[\w-]+)\s*:\s*([^;]+);',
                    io.open(os.path.join(HERE, "ui", "tokens.css"),
                            encoding="utf-8").read()))
c = lambda k: T["--" + k].strip()

RAW = io.open(os.path.join(HERE, "ui", "style.css"), encoding="utf-8").read()
IC = {}
for k, v in re.findall(r'--ic-([\w-]+):url\("data:image/svg\+xml,([^"]+)"\)', RAW):
    for a, b in (("%3C", "<"), ("%3E", ">"), ("%23", "#"), ("%22", '"'), ("%25", "%")):
        v = v.replace(a, b)
    IC[k] = re.sub(r"^<svg[^>]*>|</svg>$", "", v)

SANS = "Poppins,Inter,Segoe UI,system-ui,sans-serif"
MONO = "ui-monospace,Menlo,monospace"
S = 2.0                      # everything below is in css px, scaled on output
W, H = 232, 470
o = []
add = o.append


def rect(x, y, w, h, fill, r=0, stroke=None):
    add('<rect x="%s" y="%s" width="%s" height="%s" fill="%s" rx="%s"%s/>'
        % (x, y, w, h, fill, r, ' stroke="%s"' % stroke if stroke else ""))


def text(x, y, s, size=12, fill=None, weight=400, mono=False, ls=0, anchor="start"):
    add('<text x="%s" y="%s" font-size="%s" fill="%s" font-weight="%s" '
        'font-family="%s" letter-spacing="%s" text-anchor="%s">%s</text>'
        % (x, y, size, fill or c("ink"), weight, MONO if mono else SANS, ls,
           anchor, s.replace("&", "&amp;").replace("<", "&lt;")))


def icon(name, x, y, px, fill, opacity):
    add('<g transform="translate(%s,%s) scale(%s)" stroke="%s" fill="none" '
        'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
        'opacity="%s">%s</g>' % (x, y, px / 24.0, fill, opacity, IC[name]))


rect(0, 0, W, H, c("surface2"))
rect(W - 1, 0, 1, H, c("border"))

y = 20
text(12, y + 8, "WORKSPACE", 9.5, c("faint"), 700, ls=1.05)
y += 13
rect(12, y, W - 24, 30, c("surface"), 10, c("border"))
icon("folder", 22, y + 8, 14, c("ink2"), .45)
text(43, y + 19, "…\\castlekeep\\workspace", 10.5, c("ink2"), 500, mono=True)
y += 30 + 4

# Assistant, selected: soft fill, a brand bar at the edge, icon at full weight.
rect(12, y, W - 24, 36, c("brand-soft"), 9)
rect(12, y + 8, 3, 20, c("brand-dark"), 1.5)
icon("chat", 24, y + 9.5, 17, c("brand-ink"), 1)
text(52, y + 23, "Assistant", 13, c("brand-ink"), 600)
y += 40

text(12, y + 8, "THIS MACHINE", 9.5, c("faint"), 700, ls=1.05)
y += 11
rows = [("Control Panel", "panel", False), ("Policy", "shield", True),
        ("Run", "terminal", False), ("Settings", "sliders", False)]
for nm, ic, hover in rows:
    if hover:                                  # what the cursor does
        rect(12, y, W - 24, 36, c("surface3"), 9)
    icon(ic, 24, y + 9.5, 17, c("ink2"), .75 if hover else .55)
    text(52, y + 23, nm, 13, c("ink2"), 600)
    y += 40

rect(12, H - 92, W - 24, 1, c("border"))
text(12, H - 68, "THIS CONVERSATION", 9.5, c("faint"), 700, ls=1.05)
text(34, H - 40, "14", 18, c("ink"), 700, anchor="end")
text(43, H - 40, "sandboxes spawned", 11, c("muted"), 600)
text(34, H - 14, "3", 18, c("deny"), 700, anchor="end")
text(43, H - 14, "refused", 11, c("muted"), 600)

svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
       'viewBox="0 0 %d %d" shape-rendering="crispEdges">%s</svg>'
       % (W * S, H * S, W, H, "".join(o)))
io.open(os.path.join(HERE, "_mock_rail.svg"), "w", encoding="utf-8").write(svg)
import cairosvg
cairosvg.svg2png(url=os.path.join(HERE, "_mock_rail.svg"),
                 write_to=os.path.join(HERE, "_mock_rail.png"))
print("wrote _mock_rail.png")
