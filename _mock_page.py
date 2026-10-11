"""Throwaway. Renders a scale picture of prototype-agents.html so the layout can
be looked at rather than imagined. Uses the real token colours and the real
sprite rects, so what it gets right is proportion, density and colour balance.
It is not a browser and nothing ships from here. Delete when done."""

import io, os, re, critters

HERE = os.path.dirname(os.path.abspath(__file__))
T = dict(re.findall(r'(--[\w-]+)\s*:\s*([^;]+);',
                    io.open(os.path.join(HERE, "ui", "tokens.css"), encoding="utf-8").read()))
c = lambda k: T["--" + k].strip()

F = {n: critters.frames(n) for n in critters.CREATURES}
W, H = 1280, 800
RAIL, TITLE = 232, 46
o = []
add = o.append


def rect(x, y, w, h, fill, r=0, stroke=None):
    add('<rect x="%s" y="%s" width="%s" height="%s" fill="%s" rx="%s"%s/>'
        % (x, y, w, h, fill, r, ' stroke="%s"' % stroke if stroke else ""))


# Neither real face is installed here and neither can be fetched, so the
# renderer uses the nearest thing on the box: Poppins for Plus Jakarta Sans,
# both geometric sans with a tall x-height, and Palladio for EB Garamond, both
# old-style serifs. Palladio runs a little larger on the body than Garamond
# does, so read the serif in this picture as the generous case: if a heading
# looks balanced here it will sit slightly smaller and lighter in the browser.
SANS = "Poppins,Inter,Segoe UI,system-ui,sans-serif"
SERIF = "URW Palladio L,P052,Palatino,Georgia,serif"
MONO = "ui-monospace,Menlo,monospace"


def text(x, y, s, size=12, fill=None, weight=400, anchor="start", mono=False,
         serif=False):
    add('<text x="%s" y="%s" font-size="%s" fill="%s" font-weight="%s" '
        'text-anchor="%s" font-family="%s">%s</text>'
        % (x, y, size, fill or c("ink"), weight, anchor,
           MONO if mono else SERIF if serif else SANS,
           s.replace("&", "&amp;").replace("<", "&lt;")))


# The rail icons, read back out of style.css so this picture cannot drift from
# the stylesheet. Each token is a percent-escaped svg; unescape it and drop the
# inner drawing into place at the size the rail uses.
_RAW = io.open(os.path.join(HERE, "ui", "style.css"), encoding="utf-8").read()
IC = {}
for _k, _v in re.findall(r'--ic-([\w-]+):url\("data:image/svg\+xml,([^"]+)"\)', _RAW):
    for _a, _b in (("%3C", "<"), ("%3E", ">"), ("%23", "#"), ("%22", '"'),
                   ("%25", "%")):
        _v = _v.replace(_a, _b)
    IC[_k] = re.sub(r"^<svg[^>]*>|</svg>$", "", _v)


def icon(name, x, y, px, fill=None, opacity=1.0):
    sc = px / 24.0
    add('<g transform="translate(%s,%s) scale(%s)" stroke="%s" fill="none" '
        'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
        'opacity="%s" shape-rendering="geometricPrecision">%s</g>'
        % (x, y, sc, fill or c("ink2"), opacity, IC[name]))


def critter(name, x, y, px, frame="idle"):
    s = px / 22.0
    add('<g transform="translate(%s,%s) scale(%s)">%s</g>'
        % (x, y, s, F[name][frame]))


rect(0, 0, W, H, c("bg"))

# banner
rect(0, 0, W, 26, c("info-soft"))
text(W / 2, 17, "Prototype. The policies below are read from profiles/ and are real. "
                "The replies are scripted and no sandbox is running.",
     11.5, c("info"), 600, "middle")

# titlebar
rect(0, 26, W, TITLE, c("surface"))
rect(0, 26 + TITLE - 1, W, 1, c("border"))
rect(16, 26 + 9, 28, 28, c("brand-soft"), 9)
critter("dragon", 19, 26 + 12, 22)
text(54, 26 + 30, "CastleKeep", 16, c("ink"), 600, serif=True)
text(132, 26 + 29, "four agents, four boxes", 11.5, c("muted"), 500)
rect(W - 118, 26 + 15, 102, 17, c("primary-soft"), 6)
text(W - 67, 26 + 27, "BaseContainer", 10, c("primary"), 700, "middle")

TOP = 26 + TITLE

# ---------------------------------------------------------------- rail
rect(0, TOP, RAIL, H - TOP, c("surface2"))
rect(RAIL - 1, TOP, 1, H - TOP, c("border"))
y = TOP + 20
text(16, y, "WORKSPACE", 9.5, c("faint"), 700)
y += 13
rect(12, y, RAIL - 24, 30, c("surface"), 10, c("border"))
icon("folder", 22, y + 8, 14, c("ink2"), .45)
text(43, y + 19, "...\\castlekeep\\workspace", 10.5, c("ink2"), 500, mono=True)
y += 30 + 24

text(16, y, "THIS MACHINE", 9.5, c("faint"), 700)
y += 11
for nm, ic in [("Control Panel", "panel"), ("Policy", "shield"),
               ("Run", "terminal"), ("Settings", "sliders")]:
    icon(ic, 24, y + 9.5, 17, c("ink2"), .55)
    text(52, y + 23, nm, 13, c("ink2"), 600)
    y += 40

rect(12, H - 100, RAIL - 24, 1, c("border"))
text(16, H - 80, "THIS CONVERSATION", 9.5, c("faint"), 700)
text(38, H - 52, "0", 18, c("ink"), 700, "end")
text(47, H - 52, "sandboxes spawned", 11, c("muted"), 600)
text(38, H - 26, "0", 18, c("deny"), 700, "end")
text(47, H - 26, "refused", 11, c("muted"), 600)

# ---------------------------------------------------------------- agent bar
AG = [("Diagnostics", "dragon", "How this machine is doing", "no files", "no network"),
      ("Finance", "bird", "Rates and prices", "no files", "network"),
      ("Health", "owl", "Your clinic notes", "one folder", "no network"),
      ("Paperwork", "cat", "Forms, bills and filing", "workspace", "no network")]
FR = ["idle", "blink", "idle", "move"]
BAR = 82
rect(RAIL, TOP, W - RAIL, BAR, c("surface2"))
rect(RAIL, TOP + BAR - 1, W - RAIL, 1, c("border"))
bw = (W - RAIL - 32 - 30) / 4.0
for i, (nm, cr, tk, f, n) in enumerate(AG):
    bx = RAIL + 16 + i * (bw + 10)
    on = i == 0
    rect(bx, TOP + 14, bw, 54, c("brand-soft") if on else c("surface"), 11,
         c("brand-line") if on else c("border"))
    critter(cr, bx + 12, TOP + 21, 40, FR[i])
    text(bx + 63, TOP + 38, nm, 15, c("brand-ink") if on else c("ink2"),
         600, serif=True)
    text(bx + 63, TOP + 52, tk, 10.5,
         "#7A6615" if on else c("muted"), 600)

TOP = TOP + BAR

# ---------------------------------------------------------------- chat pane
CX, CW = RAIL, W - RAIL - 400
rect(CX, TOP, CW, H - TOP, c("surface"))

rect(CX, TOP + 63, CW, 1, c("border"))
text(CX + 22, TOP + 31, "Diagnostics", 18, c("ink"), 600, serif=True)
text(CX + 22, TOP + 48, "Checks the device. Reads no files, sends nothing.",
     11.5, c("muted"), 500)
rect(CX + CW - 300, TOP + 23, 124, 19, c("surface"), 9, c("border"))
text(CX + CW - 238, TOP + 36, "processcontainer", 10, c("muted"), 700, "middle")

# empty state
critter("dragon", CX + CW / 2 - 38, TOP + 150, 76)
text(CX + CW / 2, TOP + 266, "Diagnostics", 27, c("ink"), 600, "middle",
     serif=True)
for i, line in enumerate([
        "Read-only device check-up. It can ask Windows about itself and report",
        "what it finds. It cannot read or change a single file of yours, and it",
        "has no network at all."]):
    text(CX + CW / 2, TOP + 286 + i * 17, line, 12.5, c("muted"), 400, "middle")

sy = TOP + 360
for s in ["How is this machine doing?", "What is using the most memory right now?",
          "How much disk space is left?", "Try to read a file in my Documents folder"]:
    w = 11 + len(s) * 6.4
    rect(CX + CW / 2 - w / 2, sy, w, 30, c("surface2"), 9, c("border"))
    text(CX + CW / 2, sy + 20, s, 12, c("ink2"), 500, "middle")
    sy += 38

# composer
rect(CX + 14, H - 78, CW - 28, 44, c("surface2"), 11, c("border2"))
text(CX + 28, H - 50, "Ask Diagnostics something...", 13, c("faint"), 400)
rect(CX + CW - 92, H - 68, 64, 26, c("primary"), 8)
text(CX + CW - 60, H - 51, "Send", 12, "#fff", 700, "middle")

# ---------------------------------------------------------------- side pane
SX, SW = W - 400, 400
rect(SX, TOP, SW, H - TOP, c("surface2"))
rect(SX, TOP, 1, H - TOP, c("border"))

rect(SX, TOP + 63, SW, 1, c("border"))
text(SX + 22, TOP + 41, "Mission", 18, c("ink"), 600, serif=True)

cy = TOP + 80
rect(SX + 14, cy, SW - 28, 186, c("surface2"), 10, c("border"))
text(SX + 28, cy + 21, "IN FORCE RIGHT NOW", 9.5, c("faint"), 700)
rows = [("Readable", "${windir}\\System32"), ("Writable", "nothing"),
        ("Network", "no outbound at all"), ("Containment", "processcontainer"),
        ("Timeout", "30s per tool call"), ("Tools off", "run_command")]
ry = cy + 44
for k, v in rows:
    text(SX + 28, ry, k, 11, c("ink2"), 700)
    text(SX + 124, ry, v, 11, c("muted"), 500, mono=True)
    ry += 19
rect(SX + 28, cy + 150, SW - 56, 26, c("surface"), 8, c("border2"))
text(SX + SW / 2, cy + 167, "Change this agent's policy", 11.5, c("ink2"), 600, "middle")

cy += 200
rect(SX + 14, cy, SW - 28, 66, c("surface2"), 10, c("border"))
text(SX + 28, cy + 21, "SANDBOX ACTIVITY", 9.5, c("faint"), 700)
text(SX + 28, cy + 44, "Nothing has run in this conversation yet.", 11, c("muted"), 400)

cy += 80
rect(SX + 14, cy, SW - 28, 232, c("surface2"), 10, c("border"))
text(SX + 28, cy + 21, "ALL FOUR", 9.5, c("faint"), 700)
for i, line in enumerate(["Same model, same loop, same nine tools. The only thing",
                          "that differs is the box each one's tool calls run inside."]):
    text(SX + 28, cy + 40 + i * 14, line, 10.5, c("muted"), 400)
gy = cy + 68
rect(SX + 28, gy, SW - 56, 4 * 31, c("hair"), 9, c("border"))
for i, (nm, cr, tk, f, n) in enumerate(AG):
    ry = gy + i * 31
    rect(SX + 29, ry + 1, SW - 58, 29, c("brand-soft") if i == 0 else c("surface"))
    text(SX + 42, ry + 19, nm, 11.5, c("ink2"), 700)
    text(SX + 142, ry + 19,
         f + ("" if f == "no files" else ", write" if nm == "Paperwork" else ", read"), 11, c("muted"), 400)
    text(SX + SW - 40, ry + 19, n, 11,
         c("coral") if n == "network" else c("muted"), 600, "end")
text(SX + 28, gy + 4 * 31 + 20, "Read the last column against the middle one.",
     10.5, c("muted"), 400)
text(SX + 28, gy + 4 * 31 + 34, "The only agent that can reach the network is the",
     10.5, c("muted"), 400)
text(SX + 28, gy + 4 * 31 + 48, "only agent with nothing of yours to send.",
     10.5, c("muted"), 400)

svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
       'viewBox="0 0 %d %d" shape-rendering="crispEdges">%s</svg>'
       % (W, H, W, H, "".join(o)))
io.open(os.path.join(HERE, "_mock_page.svg"), "w", encoding="utf-8").write(svg)
import cairosvg
cairosvg.svg2png(url=os.path.join(HERE, "_mock_page.svg"),
                 write_to=os.path.join(HERE, "_mock_page.png"))
print("wrote _mock_page.png")
