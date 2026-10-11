"""
selftest_launch.py - coverage for the launch wizard and the assistant name.

Runs anywhere, including Linux. It stubs the Windows executor and the Lemonade
client, so it tests the Python, the HTTP surface and the shape of the UI files;
it does not and cannot test MXC. `verify.py` is the thing that answers "what
does this machine actually enforce".

Most of what is checked here is not logic, it is the set of promises that are
easy to break by accident and expensive to notice late: that saving a name does
not disturb the Lemonade client, that the dragon can be cut into moving parts
without losing a pixel, that the page never hardcodes a value the host could
have supplied, and the house style rules that nobody should have to eyeball.

    python selftest_launch.py
"""

import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")
sys.path.insert(0, HERE)

PASS = []
FAIL = []


def ok(cond, label):
    (PASS if cond else FAIL).append(label)


def read(*parts):
    with io.open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


# =====================================================================
# 1. the name filter
# =====================================================================

def test_name_filter():
    from core.app import _clean_name, _clean_backdrop, BACKDROP_IDS

    cases = [
        ("Max", "Max"),
        ("  max  ", "max"),
        ("Jean-Luc", "Jean-Luc"),
        ("O'Brien", "O'Brien"),
        ("Max 2.0", "Max 2.0"),
        ("Max\nTwo", "Max Two"),       # a control character is a word break
        ("Jos\u00e9", "Jos\u00e9"),    # not an allow list, so accents survive
        ("\u4e2d\u6587", "\u4e2d\u6587"),
        ("---", ""),
        ("", ""),
        (None, ""),
        (123, ""),
        ("A" * 40, "A" * 24),
    ]
    for given, want in cases:
        ok(_clean_name(given) == want,
           "name %r cleans to %r" % (given, want))

    dirty = _clean_name('<script>x</script>')
    ok("<" not in dirty and ">" not in dirty, "angle brackets never survive a name")
    ok('"' not in _clean_name('a"b'), "double quotes never survive a name")

    for b in BACKDROP_IDS:
        ok(_clean_backdrop(b) == b, "backdrop %s is accepted" % b)
    ok(_clean_backdrop("bogus") == "none", "an unknown backdrop falls back to none")
    ok(_clean_backdrop(None) == "none", "a missing backdrop falls back to none")


# =====================================================================
# 2. save_setup round trip
# =====================================================================

def temp_app():
    """An App built against a throwaway copy of the real config, with the
    Windows parts stubbed out."""
    import core.app as app_mod

    d = tempfile.mkdtemp(prefix="ck-selftest-")
    shutil.copy(os.path.join(HERE, "policy.json"), os.path.join(d, "policy.json"))
    # The real profiles, not fixtures. An agent route tested against invented
    # profiles would pass on a machine where the shipped four are broken.
    shutil.copytree(os.path.join(HERE, "profiles"), os.path.join(d, "profiles"))

    # The real config is the shape under test, but its contents are not: this
    # machine may well have been through the wizard already. Rewinding the two
    # keys the wizard owns is what lets the "an unnamed install" assertions
    # below mean anything on a machine that is already set up.
    cfg = json.load(io.open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    (cfg.get("agent") or {}).pop("assistantName", None)
    (cfg.get("ui") or {}).pop("backdrop", None)
    with io.open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, indent=2) + "\n")

    class _Mxc(object):
        exe = r"C:\stub\wxc-exec.exe"
        exe_error = None
        _probe_cache = None

        def __init__(self, *a, **k):
            pass

        def probe(self):
            return {"available": True, "tier": "stub",
                    "capabilities": {"_tierLabel": "stub"}, "warnings": []}

    class _Lemonade(object):
        model = "stub-model"
        prefix = None

        def __init__(self, cfg):
            self.model = ((cfg or {}).get("lemonade") or {}).get("model") or "stub-model"

        def health(self):
            return {"reachable": True, "modelPresent": True, "model": self.model,
                    "baseUrl": "http://127.0.0.1:0", "routePrefix": "",
                    "note": None, "suggestions": []}

        def warmup(self):
            return {"ok": True, "ms": 1900}

    real_mxc, real_lem = app_mod.Mxc, app_mod.Lemonade
    app_mod.Mxc, app_mod.Lemonade = _Mxc, _Lemonade
    try:
        a = app_mod.App(d)
    finally:
        app_mod.Mxc, app_mod.Lemonade = real_mxc, real_lem
    a.probe = _Mxc().probe()
    a.caps = a.probe["capabilities"]
    a.lemonade_health = a.lemonade.health()
    a.warmup = {"state": "ready", "ms": 1900, "model": a.lemonade.model}
    return a


def test_save_setup():
    import core.app as app_mod

    a = temp_app()
    cfg_before = json.load(io.open(a.config_path, encoding="utf-8"))
    lem_before = json.dumps(cfg_before.get("lemonade"), sort_keys=True)

    s = a.setup()
    ok(s["assistantName"] == app_mod.DEFAULT_ASSISTANT_NAME,
       "an unnamed install reports the default name")
    ok(s["named"] is False, "an unnamed install is not 'named'")
    ok(s["backdrop"] == "none", "an unnamed install has no backdrop")

    saved = a.save_setup(name="  Ember  ", backdrop="parchment")
    ok(saved["assistantName"] == "Ember", "save_setup trims the name")
    ok(saved["backdrop"] == "parchment", "save_setup keeps a known backdrop")
    ok(saved["named"] is True, "a saved name flips 'named'")
    ok(a.assistant_name() == "Ember", "assistant_name agrees with setup")

    cfg_after = json.load(io.open(a.config_path, encoding="utf-8"))
    ok(json.dumps(cfg_after.get("lemonade"), sort_keys=True) == lem_before,
       "saving a name leaves the lemonade subtree byte-identical")
    ok(set(cfg_after) == set(cfg_before),
       "saving a name adds no top-level key and drops none")
    ok("_readme" in cfg_after, "the hand-written _readme key survives the round trip")
    ok(cfg_after["agent"]["assistantName"] == "Ember",
       "the name lands under agent, where config.json already keeps agent settings")
    ok(cfg_after["ui"]["backdrop"] == "parchment", "the backdrop lands under ui")

    # The reason the two writes above are safe: reload_config compares only the
    # lemonade subtree, so a name change cannot tear down the client or throw
    # away a warm model.
    ok(a.reload_config() is False,
       "a setup save does not look like a lemonade change")
    ok(a.warmup.get("state") == "ready", "a setup save does not reset the warm-up")

    a.save_setup(backdrop="bogus")
    ok(a.setup()["backdrop"] == "none", "an unknown backdrop is written back as none")
    ok(a.setup()["assistantName"] == "Ember",
       "saving only a backdrop leaves the name alone")

    for bad in ("", "   ", "---", "\n\t"):
        try:
            a.save_setup(name=bad)
            ok(False, "an empty name %r is refused" % bad)
        except ValueError:
            ok(True, "an empty name %r is refused" % bad)

    # None is not an empty name, it is "leave this one alone" - which is how
    # the backdrop-only save above is able to keep the name.
    a.save_setup(name=None, backdrop="hills")
    ok(a.setup()["assistantName"] == "Ember",
       "a name of None means 'do not touch the name'")

    shutil.rmtree(os.path.dirname(a.config_path), ignore_errors=True)


def test_host_and_workspace():
    a = temp_app()
    h = a.host_info()
    ok(isinstance(h, dict), "host_info returns a dict")
    ok(set(h) == {"cpu", "memoryGB", "arch"}, "host_info has exactly three fields")
    ok(a.host_info() is h, "host_info is cached, so the poll does not re-read it")
    ok(isinstance(a.workspace_count(), int), "workspace_count counts the files")
    shutil.rmtree(os.path.dirname(a.config_path), ignore_errors=True)


# =====================================================================
# 3. the HTTP surface
# =====================================================================

def with_server(fn):
    from core.server import make_server

    a = temp_app()
    httpd = make_server(a, UI, 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = "http://127.0.0.1:%d" % port
    try:
        fn(base, a)
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(os.path.dirname(a.config_path), ignore_errors=True)


def get(base, path):
    req = urllib.request.Request(base + path)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read(), r.headers.get("Content-Type", "")


def post(base, path, obj):
    body = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(base + path, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Origin", base)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_http():
    def body(base, app):
        code, raw, _ = get(base, "/api/state")
        st = json.loads(raw.decode("utf-8"))
        ok(code == 200, "/api/state answers")
        for field in ("setup", "host", "workspaceFiles"):
            ok(field in st, "/api/state carries %s" % field)
        ok(set(st["setup"]) == {"assistantName", "backdrop", "named"},
           "the setup payload is exactly the three fields the page reads")

        code, j = post(base, "/api/setup", {"assistantName": "Scout", "backdrop": "stone"})
        ok(code == 200 and j.get("saved") is True, "POST /api/setup saves")
        ok(j["setup"]["assistantName"] == "Scout", "POST /api/setup echoes the name")

        code, raw, _ = get(base, "/api/state")
        st = json.loads(raw.decode("utf-8"))
        ok(st["setup"]["assistantName"] == "Scout",
           "the saved name shows up on the very next poll")
        ok(st["setup"]["named"] is True, "the saved name flips the resume signal")

        code, j = post(base, "/api/setup", {"assistantName": "   "})
        ok(code == 400 and j.get("saved") is False,
           "POST /api/setup refuses an empty name with a 400")
        ok(j.get("error"), "the refusal says why")

        code, raw, _ = get(base, "/api/state")
        ok(json.loads(raw.decode("utf-8"))["setup"]["assistantName"] == "Scout",
           "a refused save leaves the old name in place")

        # Every static file the page pulls in has to actually be served.
        for path, needle in (("/", b"<title>CastleKeep</title>"),
                             ("/launch", b"Name your assistant"),
                             ("/app", b'id="transcript"'),
                             ("/phase1", b"<!doctype html>"),
                             ("/tokens.css", b"--brand"),
                             ("/style.css", b".titlebar"),
                             ("/dragonwave.js", b"wavingDragon"),
                             ("/dragon.js", b"DRAGON_BODY")):
            try:
                code, raw, _ = get(base, path)
                ok(code == 200 and needle.lower() in raw.lower(),
                   "%s is served and looks right" % path)
            except Exception as e:
                ok(False, "%s is served (%s)" % (path, e))

        _, _, ctype = get(base, "/tokens.css")
        ok(ctype.startswith("text/css"), "tokens.css is served as CSS")
        _, _, ctype = get(base, "/dragonwave.js")
        ok("javascript" in ctype, "dragonwave.js is served as JavaScript")

        # Fonts live in a subfolder, which the static handler has to allow.
        code, raw, _ = get(base, "/fonts/README.md")
        ok(code == 200
           and b"EBGaramond-VariableFont_wght.woff2" in raw
           and b"PlusJakartaSans-VariableFont_wght.woff2" in raw,
           "a file inside ui/fonts/ is served, and the README names the two "
           "files to drop in")

        # Firefox refuses a font served as application/octet-stream, and
        # Python's own table predates woff2 on some builds. Checked against
        # the mapping rather than a scratch file, so this still means
        # something on a machine where the real fonts have not been added.
        from core.server import _EXTRA_TYPES
        ok(_EXTRA_TYPES.get(".woff2") == "font/woff2",
           "woff2 has a font content type regardless of the host's mime table")
        for real in ("EBGaramond-VariableFont_wght.woff2",
                     "PlusJakartaSans-VariableFont_wght.woff2",
                     "EBGaramond-Regular.woff2",
                     "PlusJakartaSans-Regular.woff2"):
            if os.path.isfile(os.path.join(UI, "fonts", real)):
                _, raw, ctype = get(base, "/fonts/" + real)
                ok(ctype.startswith("font/woff2"), "%s is served as a font" % real)
                ok(raw[:4] == b"wOF2", "%s is a real woff2 file" % real)

    with_server(body)


# =====================================================================
# 4. the dragon, cut into moving parts
# =====================================================================

RECT = re.compile(r'<rect x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)"'
                  r' height="([\d.]+)" fill="(#[0-9A-Fa-f]+)"/>')


def _cut(r, box):
    x, y, w, h, f = r
    x0, y0, x1, y1 = box
    ix0, ix1 = max(x, x0), min(x + w, x1)
    iy0, iy1 = max(y, y0), min(y + h, y1)
    if ix0 >= ix1 or iy0 >= iy1:
        return [], [r]
    out = []
    if y < iy0:
        out.append((x, y, w, iy0 - y, f))
    if y + h > iy1:
        out.append((x, iy1, w, y + h - iy1, f))
    if x < ix0:
        out.append((x, iy0, ix0 - x, iy1 - iy0, f))
    if x + w > ix1:
        out.append((ix1, iy0, x + w - ix1, iy1 - iy0, f))
    return [(ix0, iy0, ix1 - ix0, iy1 - iy0, f)], out


def _partition(rects, boxes):
    rest, taken = rects, []
    for b in boxes:
        nxt = []
        for r in rest:
            inside, outside = _cut(r, b)
            taken += inside
            nxt += outside
        rest = nxt
    return taken, rest


def _cells(rects, label):
    g = {}
    for x, y, w, h, f in rects:
        for yy in range(int(y), int(y + h)):
            for xx in range(int(x), int(x + w)):
                if (xx, yy) in g:
                    raise AssertionError("%s: two rects claim %s,%s" % (label, xx, yy))
                g[(xx, yy)] = f
    return g


def test_dragon_slicing():
    """The one way dragonwave.js can fail quietly is by dropping or doubling a
    pixel. This reimplements its rectangle arithmetic and checks the slices add
    back up to the original sprite, for every state, not just the one in use."""
    wave = read(UI, "dragonwave.js")
    boxes = {}
    m = re.search(r"const WING = \{ x0: (\d+), y0: (\d+), x1: (\d+), y1: (\d+) \}", wave)
    ok(bool(m), "dragonwave.js declares the wing box in a readable form")
    if not m:
        return
    wing = tuple(int(g) for g in m.groups())
    eyes = [tuple(int(g) for g in e) for e in
            re.findall(r"\{ x0: (\d+), y0: (\d+), x1: (\d+), y1: (\d+) \}", wave)[1:]]
    ok(len(eyes) == 2, "dragonwave.js declares two eye boxes")

    src = read(UI, "dragon.js")
    bodies = json.loads(re.search(r"export const DRAGON_BODY = (\{.*?\});", src, re.S).group(1))
    ok(len(bodies) >= 6, "dragon.js still ships every state")

    def parse(s):
        return [(float(a), float(b), float(c), float(d), e)
                for a, b, c, d, e in RECT.findall(s)]

    for state, markup in bodies.items():
        orig = parse(markup)
        ok(len(orig) > 0, "dragon.js state %s parses" % state)
        taken_wing, rest = _partition(orig, [wing])
        taken_eyes, rest = _partition(rest, eyes)
        try:
            same = _cells(orig, state) == _cells(rest + taken_eyes + taken_wing, state)
        except AssertionError:
            same = False
        ok(same, "slicing %s loses and duplicates nothing" % state)
        ok(len(taken_wing) > 0, "the wing box catches pixels in %s" % state)

    open_eyes = set(_cells(_partition(parse(bodies["idle"]), eyes)[0], "idle"))
    shut_eyes = set(_cells(_partition(parse(bodies["asleep"]), eyes)[0], "asleep"))
    ok(open_eyes == shut_eyes and len(open_eyes) > 0,
       "the open and shut eye frames cover identical cells, so a blink leaves no hole")

    # The pivot has to sit on the wing's inner edge. Anywhere else and the wing
    # detaches from the body as it swings.
    html = read(UI, "launch.html")
    p = re.search(r"\.d-wing\{[^}]*transform-origin:([\d.]+)px ([\d.]+)px", html)
    ok(bool(p), "launch.html sets a pivot for the wing")
    if p:
        px, py = float(p.group(1)), float(p.group(2))
        ok(px == wing[0], "the pivot sits on the wing's inner edge")
        ok(wing[1] <= py <= wing[3], "the pivot sits within the wing's vertical span")
    ok("transform-box:view-box" in html.replace(" ", ""),
       "the pivot is measured in viewBox units, not in the element's bounding box")

    _run_dragon_in_node(wing)


def _run_dragon_in_node(wing):
    """Everything above is a Python reimplementation of the slicing, which
    proves the arithmetic and not the file. If node is around, run the real
    module and check it agrees. Skipped quietly if it is not: the app does not
    need node, only the Phase 1 driver does."""
    import subprocess

    if not shutil.which("node"):
        return
    d = tempfile.mkdtemp(prefix="ck-dragon-")
    try:
        src = read(UI, "dragonwave.js").replace('from "/dragon.js"', 'from "./dragon.js"')
        io.open(os.path.join(d, "dragonwave.mjs"), "w", encoding="utf-8").write(src)
        shutil.copy(os.path.join(UI, "dragon.js"), os.path.join(d, "dragon.js"))
        io.open(os.path.join(d, "t.mjs"), "w", encoding="utf-8").write(_NODE_HARNESS)
        out = subprocess.run([shutil.which("node"), os.path.join(d, "t.mjs")],
                             capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            ok(False, "dragonwave.js runs under node (%s)" % out.stderr.strip()[:200])
            return
        got = json.loads(out.stdout)
    except Exception as e:
        ok(False, "dragonwave.js runs under node (%s)" % e)
        return
    finally:
        shutil.rmtree(d, ignore_errors=True)

    ok(got["viewBox"], "the real module emits a 22x22 viewBox")
    ok(got["crisp"], "and keeps crispEdges, so the pixels stay pixels")
    ok(got["cls"], "and passes the caller's class through")
    for g in ("d-body", "d-shut", "d-open", "d-wing"):
        ok(got["groups"].get(g, 0) > 0, "the real module emits a %s group" % g)

    want = set()
    for x in range(wing[0], wing[2]):
        for y in range(wing[1], wing[3]):
            want.add("%d,%d" % (x, y))
    ok(set(got["wingCells"]) <= want,
       "the wing group holds nothing from outside the wing box")
    ok(len(got["wingCells"]) == 9,
       "the wing is the nine pixels that should swing (%d)" % len(got["wingCells"]))


_NODE_HARNESS = r"""
import { wavingDragon } from "./dragonwave.mjs";
const svg = wavingDragon("tile");
const RECT = /<rect x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="(#[0-9A-Fa-f]+)"\/>/g;
const grab = g => (svg.match(new RegExp('<g class="' + g + '">([\\s\\S]*?)</g>')) || [,""])[1];
const groups = {};
for (const g of ["d-body", "d-shut", "d-open", "d-wing"]) {
  groups[g] = [...grab(g).matchAll(RECT)].length;
}
const cells = s => { const o = []; for (const m of s.matchAll(RECT)) {
  const [, x, y, w, h] = m.map(Number);
  for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) o.push(xx + "," + yy);
} return o; };
console.log(JSON.stringify({ groups, wingCells: cells(grab("d-wing")),
  viewBox: /viewBox="0 0 22 22"/.test(svg),
  crisp: /shape-rendering="crispEdges"/.test(svg),
  cls: /class="tile"/.test(svg) }));
"""


# =====================================================================
# 5. the launch page
# =====================================================================

OURS = ["ui/launch.html", "ui/dragonwave.js", "ui/tokens.css", "ui/fonts/README.md"]


def test_house_style():
    for rel in OURS + ["ui/style.css", "ui/app.js", "ui/index.html",
                       "core/app.py", "core/server.py", "core/agent.py"]:
        s = read(HERE, *rel.split("/"))
        ok("\u2014" not in s, "no em dash in %s" % rel)

    for rel in OURS:
        s = read(HERE, *rel.split("/"))
        stray = [c for c in s if ord(c) > 127 and c not in "\u00b7"]
        ok(not stray, "no stray non-ascii in %s (%r)" % (rel, stray[:3]))

    html = read(UI, "launch.html")
    low = html.lower()

    # The containment tier is a claim only `wxc-exec --probe` gets to make, and
    # the front door is not the place to make it.
    ok("tier" not in low, "the launch page never mentions a tier")
    ok("appcontainer" not in low, "the launch page never names a backend")

    ok("localstorage" not in low and "sessionstorage" not in low,
       "the launch page keeps no state in the browser")

    # Phase 1 before CastleKeep, every time. Somebody who opens the chat first
    # never finds out what produced the refusal they are about to see.
    doors = re.findall(r'<div class="dtitle"[^>]*>([^<]*)</div>', html)
    ok(len(doors) == 2, "the last step offers exactly two doors")
    ok(doors and "Phase 1" in doors[0],
       "the first door is Phase 1, because somebody who opens the chat first "
       "never finds out what produced the refusal they are about to see")
    ok(len(doors) > 1 and "CastleKeep" in doors[1], "the second door is the app")
    ok(html.find('id="goPhase1"') < html.find('id="goApp"'),
       "the Phase 1 button comes first in the markup, so it is first by keyboard too")
    ok("start with Phase 1" in html, "and the page says so in words")

    # Brand yellow carries accents, not surfaces.
    for mcss in re.finditer(r"([.#][\w\-\[\]=]+[^{]*)\{([^}]*)\}", html):
        sel, decl = mcss.group(1).strip(), mcss.group(2)
        if re.search(r"background(-color)?:\s*var\(--brand\)", decl):
            ok("dot" in sel, "raw --brand fills only the status dot, not %s" % sel)

    ok("fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html,
       "the launch page never reaches out to a font CDN")
    ok('href="/tokens.css"' in html, "the launch page links the shared palette")
    ok('href="/style.css"' not in html,
       "the launch page does not borrow the app shell's layout rules")


def test_launch_page_wiring():
    html = read(UI, "launch.html")

    # Every id the script reaches for has to exist in the markup above it.
    ids = set(re.findall(r'id="([\w\-]+)"', html))
    wanted = set(re.findall(r'getElementById\("([\w\-]+)"\)', html))
    missing = sorted(wanted - ids)
    ok(not missing, "every id the script reads exists in the markup (%s)" % missing)

    # Five panels, four pips.
    panels = re.findall(r'<section class="step[^"]*" data-i="(\d)"', html)
    ok(panels == ["0", "1", "2", "3", "4"], "five steps, numbered in order")
    ok("const LAST = 4;" in html, "the wizard knows where it ends")
    ok(html.count('class="step s0 live"') == 1, "exactly one step starts live")

    # The checks are read, never invented.
    for field in ("st.probe", "st.mxcExe", "st.lemonade", "st.warmup",
                  "st.workspaceFiles", "st.workspace", "st.host", "st.setup"):
        ok(field in html or field.replace("st.", "") in html,
           "the page reads %s from /api/state" % field)

    # Nothing on this page may be the answer written down in advance.
    for forbidden in ("Strix Halo", "128 GB", "Qwen", "13305", "8000",
                      "Ryzen AI Max", "C:\\\\Users"):
        ok(forbidden not in html, "the page does not hardcode %r" % forbidden)
    ok("Ryzen AI" in html,
       "the step is still labelled as the Ryzen AI setup, which is the claim, "
       "not the measurement")

    # The three Lemonade claims stay three claims.
    ok("reachable" in html and "modelPresent" in html,
       "reachable and serving-the-right-model are checked separately")
    ok('"Answering, but not serving "' in html,
       "a reachable server that is serving the wrong model says exactly that")
    ok('warm.state === "ready"' in html,
       "the weights are a third claim, not folded into the second")
    ok(bool(re.search(r'const ready = warm\.state === "ready"[\s\S]{0,400}?'
                      r'goApp\.disabled = !ready', html)),
       "the app door waits on the weights, not on the server being up")

    # Every endpoint named anywhere in the page, checked against the routes the
    # server will actually answer. A typo here is a button that looks fine and
    # silently does nothing, which is the worst kind of bug on a setup screen.
    server = read(HERE, "core", "server.py")
    routes = set(re.findall(r'path == "(/api/[\w/]+)"', server))
    used = set(re.findall(r'"(/api/[\w/]+)"', html))
    ok(used, "the page talks to the server at all")
    unknown = sorted(used - routes)
    ok(not unknown, "every endpoint the page names is a real route (%s)" % unknown)
    for needed in ("/api/setup", "/api/state", "/api/rescan", "/api/warmup"):
        ok(needed in used, "the page uses %s" % needed)
    ok("/api/policy" not in used, "the launch page cannot edit the policy")
    ok(re.search(r'fetch\("/api/setup",\s*\{[^}]*method\s*:\s*"POST"', html),
       "the name is saved with a POST")
    ok(html.count("method") == html.count('method:"POST"') + html.count('method: "POST"'),
       "the only writes this page makes are POSTs it declares")

    # The name has to be on disk before the step after next tries to read it
    # back, which is why the save hangs off leaving the backdrop step rather
    # than off pressing a finish button that does not exist.
    ok(re.search(r"if\(step === 2\) await saveSetup\(\)", html),
       "the name is saved on the way out of the backdrop step")
    ok(re.search(r'skipBtn\.addEventListener[\s\S]{0,160}?saveSetup\(\)', html),
       "and skipping the backdrop still saves the name")

    # The resume rule.
    ok("setup.named" in html, "the page reads the resume signal")
    ok(re.search(r"if\(resumed\)\{[\s\S]{0,300}?show\(3\);", html),
       "a machine that has been through the wizard opens at the checks")
    ok(re.search(r"\}else\{\s*show\(0\);", html),
       "and a fresh one opens at the welcome")
    ok('id="redo"' in html, "and can still walk back to the top")
    ok(re.search(r'redoBtn\.addEventListener[\s\S]{0,300}?resumed = false', html),
       "starting over clears the resume flag, or Back would still be hidden")

    # Accessibility and motion.
    ok("prefers-reduced-motion" in html, "the animation respects reduced motion")
    ok('aria-pressed' in html, "the pickers report their pressed state")

    # Typography: serif on the titles and the main blocks, sans on every control.
    def decl_for(sel):
        m = re.search(re.escape(sel) + r"\{([^}]*)\}", html)
        return m.group(1) if m else ""

    for sel in (".step h2", ".step p.lede", ".dtitle", ".hint", ".who",
                "input[type=text]"):
        ok("var(--serif)" in decl_for(sel), "%s is set in the serif" % sel)
    for sel in (".btn", ".chip", ".rname", ".rnote", ".label", ".progtext",
                ".link", ".dsub"):
        ok("var(--serif)" not in decl_for(sel), "%s stays on the sans" % sel)

    # The backdrop ids on the page and in the server have to be the same set.
    from core.app import BACKDROP_IDS
    page = re.findall(r'\{id:"(\w+)",\s+name:', html)
    ok(sorted(page) == sorted(BACKDROP_IDS),
       "the page and core/app.py agree on the backdrop ids (%s vs %s)"
       % (sorted(page), sorted(BACKDROP_IDS)))
    ok(page[0] == "none", "None is the first and default backdrop")


def test_tokens():
    tokens = read(UI, "tokens.css")
    defined = set(re.findall(r"(--[\w\-]+)\s*:", tokens))
    for rel in ("ui/launch.html", "ui/style.css", "ui/index.html", "ui/phase1.html"):
        s = read(HERE, *rel.split("/"))
        local = set(re.findall(r"(--[\w\-]+)\s*:", s))
        used = set(re.findall(r"var\((--[\w\-]+)", s))
        unknown = sorted(used - defined - local)
        ok(not unknown, "%s uses no undefined custom property (%s)" % (rel, unknown))

    ok("--serif" in defined and "--hair" in defined,
       "the palette carries the launch page's two additions")

    # One file declares the families, and it is the one every page links. A
    # second declaration of "EB Garamond" anywhere else wins for the weights it
    # covers, so a page carrying its own copy ends up on a different fallback
    # from the rest of the app the moment the two name different files.
    ok(len(re.findall(r"@font-face\s*\{", tokens)) == 2 and '"EB Garamond"' in tokens
       and '"Plus Jakarta Sans"' in tokens,
       "tokens.css declares both families")
    for rel in ("ui/launch.html", "ui/style.css", "ui/index.html", "ui/phase1.html"):
        ok(not re.search(r"@font-face\s*\{", read(HERE, *rel.split("/"))),
           "%s does not declare a font family of its own" % rel)
    ok('url("fonts/' in tokens,
       "the font paths are relative to tokens.css, which is what lets a "
       "generator that inlines it rewrite them")
    ok(":root{" in read(UI, "style.css").replace(" ", "") is False or
       "--brand:" not in read(UI, "style.css"),
       "style.css no longer declares its own palette")
    for rel in ("ui/index.html", "ui/phase1.html"):
        s = read(HERE, *rel.split("/"))
        ok(s.index("tokens.css") < s.index("style.css"),
           "%s links the palette before the layout" % rel)


# =====================================================================
# 6. the name, everywhere else
#
# The launch wizard names the dragon and nobody else. The other three answer
# to their job titles, so the thing to check is no longer "is the name on
# every surface" but "is it on exactly the one agent that owns it".
# =====================================================================

def test_the_name_belongs_to_one_agent():
    index = read(UI, "index.html")
    appjs = read(UI, "app.js")
    app_py = read(HERE, "core", "app.py")

    ok("data-who" not in index,
       "no surface in index.html claims the name any more, because three of "
       "the four agents are not called it")
    ok("four agents, one machine" in index,
       "the titlebar says what is behind the door instead")
    ok(re.search(r'data-tab="assistant"[^>]*>(?:<[^>]*>)*Agents', index),
       "and the rail tab is Agents, not one agent's name")

    ok("def agent_label(self, p)" in app_py,
       "one function on the host decides what an agent is called")
    ok("self.assistant_name() if p.named else p.title" in app_py,
       "the wizard name goes to the profile that asked for it, the rest take "
       "their titles")
    ok(app_py.count("self.assistant_name() if p.named") == 1,
       "and it is the only place that rule is written down")

    ok("function label(p)" in appjs,
       "the UI has one answer too, and it is per agent")
    ok("p.label || p.title || p.name" in appjs,
       "which prefers the label the host already worked out")
    ok('el("div", "name", label(p))' in appjs,
       "the transcript labels each message with the agent that said it")
    ok("function who()" in appjs and "setup || {}).assistantName" in appjs,
       "the raw wizard name is still reachable, for the window title")
    ok(appjs.count("who()") <= 4,
       "but it is used sparingly, because it names one agent and not the app")


def test_the_prompt_tells_each_agent_its_own_name():
    agent = read(HERE, "core", "agent.py")

    ok("{name}" in agent, "the system prompt has a slot for the name")
    ok("def display_name(self)" in agent,
       "and the agent knows which name is its own")
    ok("self.app.agent_label(self.profile())" in agent,
       "it asks the host rather than working it out a second way")
    ok('SYSTEM.replace("{name}", self.display_name())' in agent,
       "so the slot is filled per agent, not from the wizard directly")
    ok("SYSTEM.format" not in agent,
       "the prompt is filled with replace, so a stray brace in it is not a crash")
    ok("You are {name}, one of the agents inside CastleKeep" in agent,
       "the model is told it is one of several, which is what stops it "
       "answering for the other three")
    ok("app.agent_label(p)" in agent,
       "the roster each agent is given uses the same labels as the bar, so it "
       "never tells somebody to switch to an agent that is not in it")


def test_agent_prompt_renders():
    import core.agent as agent_mod

    a = temp_app()
    a.save_setup(name="Bramble")
    out = agent_mod.SYSTEM.replace("{name}", a.assistant_name())
    ok("Bramble" in out, "the rendered prompt carries the name")
    ok("{name}" not in out, "and no slot is left unfilled")
    ok("You are Bramble" in out, "the first sentence is the introduction")
    # The other three never see that name. Rendering the same template for a
    # titled agent has to produce a prompt with no trace of it, or the model
    # introduces itself as the dragon.
    other = agent_mod.SYSTEM.replace("{name}", "Paperwork")
    ok("Bramble" not in other,
       "and a titled agent's prompt carries no trace of the dragon's name")
    shutil.rmtree(os.path.dirname(a.config_path), ignore_errors=True)


# =====================================================================
# 7. four agents, four boxes
#
# These load the profiles that ship, not fixtures. The claim the workshop
# makes is about these four files, so a fixture that passed would prove
# nothing about the thing on screen.
# =====================================================================

def _real_app():
    """The real App, pointed at the real project, with nothing started.

    __init__ only reads files. start() is what probes the host and would
    need Windows, so it is deliberately not called.
    """
    import core.app as app_mod
    return app_mod.App(HERE)


def test_every_profile_compiles_to_its_own_box():
    import core.policy as policy_mod
    import core.profiles as profiles_mod

    a = _real_app()
    profs = a.profiles.all()
    ok(len(profs) == 4, "four profiles ship in profiles\\ (found %d)" % len(profs))

    notes = profiles_mod.audit(a.profiles)
    bad = [n for n in notes if n.get("level") == "error"]
    ok(not bad, "and the audit finds nothing wrong with them (%s)"
                % [n.get("message") for n in bad][:2])

    named = [p for p in profs if p.named]
    ok(len(named) == 1,
       "exactly one of them asks for the wizard's name (found %d)" % len(named))
    ok(named and named[0].critter == "dragon",
       "and it is the dragon, which is the one the launch screen draws")

    seen = {}
    for p in profs:
        cfg, cnotes = policy_mod.compile_config(
            p.policy, a.path_ctx(), ["cmd", "/c", "ver"], caps=None)
        ok(isinstance(cfg, dict) and cfg,
           "%s compiles to a wire config" % p.name)
        errs = [n for n in cnotes if n.get("level") == "error"]
        ok(not errs, "%s compiles with no errors (%s)"
                     % (p.name, [n.get("message") for n in errs][:1]))
        seen[p.name] = cfg

    # Four agents that compiled to the same config would be four labels on one
    # box. The demo is that they are not.
    blobs = {n: json.dumps(c, sort_keys=True) for n, c in seen.items()}
    ok(len(set(blobs.values())) == 4,
       "and no two of them compile to the same box")


def test_the_four_boxes_differ_only_where_they_should():
    import core.policy as policy_mod

    a = _real_app()
    gates, files, nets = set(), {}, {}
    for p in a.profiles.all():
        pol = policy_mod.normalise(p.policy)
        # The tools block is a host-side gate, not a sandbox one. Keeping it
        # identical across all four is what makes the four boxes a containment
        # result rather than four if statements in the loop. Only the switches
        # count: each profile's _note explains the gate in its own words, and
        # prose that differs is not a gate that differs.
        switches = {k: v for k, v in (pol.get("tools") or {}).items()
                    if not k.startswith("_")}
        gates.add(json.dumps(switches, sort_keys=True))
        files[p.name] = (tuple(pol["paths"].get("read") or ()),
                         tuple(pol["paths"].get("write") or ()))
        nets[p.name] = pol["network"].get("outbound")

    ok(len(gates) == 1,
       "all four agents are offered the same tools, so a difference in what "
       "they can do is a difference in what the sandbox allows (%d gates)"
       % len(gates))

    ok(len(set(files.values())) == 4 or len(set(files.values())) >= 3,
       "their file grants are not all the same")

    talkers = [n for n, v in nets.items() if v == "allow"]
    ok(len(talkers) == 1,
       "exactly one agent may reach the network (found %s)" % (talkers or "none"))
    if talkers:
        who = talkers[0]
        read, write = files[who]
        user = [x for x in read + write if "${windir}" not in x and "Windows" not in x]
        ok(not user,
           "and it is the one with nothing of yours to send (%s can also "
           "reach %s)" % (who, user[:2]))

    writers = [n for n, v in files.items() if v[1]]
    ok(len(writers) == 1,
       "exactly one agent may write anywhere (found %s)" % (writers or "none"))
    if writers:
        ok(nets[writers[0]] != "allow",
           "and the agent that can write cannot also reach the network")


def test_the_ui_asks_for_ids_that_exist():
    """Every $("id") in app.js has to resolve in index.html.

    There is no browser on this machine to catch a typo here, and a missing
    id throws part-way through hydrate, which blanks whatever had not been
    rendered yet rather than failing where the typo is.
    """
    index = read(UI, "index.html")
    appjs = read(UI, "app.js")

    have = set(re.findall(r'id="([^"]+)"', index))
    want = set(re.findall(r'\$\("([^"]+)"\)', appjs))
    missing = sorted(want - have)
    ok(not missing, "every id app.js reaches for is in index.html (%s)" % missing[:4])

    # The other direction is only a warning in spirit, so it is not asserted:
    # index.html carries ids that only CSS or a human uses.
    ok(len(want) > 20, "and it is reaching for a real page, not two ids")


def test_the_mission_panel_reports_what_is_running():
    """The live bar and the folding strips, checked where they are declared.

    Both of these are HTML and CSS agreeing with JavaScript across three
    files, which is the kind of seam that breaks quietly: a fold control
    pointing at an id that no longer exists just stops working, and a bar
    that ships without its hidden attribute is a permanently empty strip
    sitting above the cards. Neither throws, so neither shows up anywhere
    else.
    """
    index = read(UI, "index.html")
    appjs = read(UI, "app.js")
    css = read(UI, "style.css")
    have = set(re.findall(r'id="([^"]+)"', index))

    # --- the fold control ------------------------------------------------
    targets = re.findall(r'data-fold="([^"]+)"', index)
    ok(targets, "the page carries fold controls at all")
    ok(all(t in have for t in targets),
       "every data-fold names an element that exists (%s)"
       % sorted(set(targets) - have))

    panes = sorted(set(targets))
    ok(len(panes) == 3,
       "all three side panels fold, not just the one that was asked about "
       "(%s)" % panes)
    for pane in panes:
        # Two controls per panel and no more: the button that folds it and
        # the strip that brings it back. One without the other is a panel
        # you can close and not reopen, which is the worst of the three
        # possible states.
        ok(targets.count(pane) == 2,
           "%s has exactly one way out and one way back (%d)"
           % (pane, targets.count(pane)))
    ok(index.count('class="paneflip') == 3 and index.count('class="foldtab"') == 3,
       "and those controls are the flip button and the fold strip")
    ok(index.count('aria-expanded="true"') == 3,
       "each flip button ships its state, so the first press is not also the "
       "first time a screen reader hears about it")

    # --- the panel the folding has to hide -------------------------------
    for pane in panes:
        ok('id="%s"' % pane in index, "%s is a real pane" % pane)
    ok(".pane.side.folded" in css, "the folded width is a CSS rule")
    ok(".foldtab{display:none}" in css.replace(" ", ""),
       "and the strip is out of the way until then")

    # --- the live bar ----------------------------------------------------
    ok('id="liveBar" hidden' in index,
       "the live bar ships hidden, because its resting state is empty and a "
       "bar that is always there is wallpaper")
    ok('id="foldDot" hidden' in index, "so does the dot on the folded strip")

    # Outside the scroller on purpose. Inside it, the one thing you want to
    # read while a sandbox is open is the one thing that can scroll away.
    head, _, rest = index.partition('<div class="live" id="liveBar"')
    ok('id="missionScroll"' in rest and 'id="missionScroll"' not in head,
       "and it sits above the scrolling cards, so it cannot scroll away")

    ok(".live{" in css.replace(" ", "") or ".live {" in css,
       "the bar has a style")
    ok("@media (prefers-reduced-motion:reduce)" in css.replace(" ", "")
       .replace("@media(prefers-reduced-motion:reduce)",
                "@media (prefers-reduced-motion:reduce)")
       or "prefers-reduced-motion" in css,
       "and the pulsing dot stops for anyone who asked motion to stop")

    # --- the four hooks --------------------------------------------------
    # The bar is only as honest as its last call. liveStop missing from the
    # path that runs after an abort or a thrown stream would leave a clock
    # counting next to an agent that stopped working minutes ago, which is
    # worse than no bar at all.
    for fn in ("function liveStart", "function livePhase", "function liveStop",
               "function renderLive", "function foldPane"):
        ok(fn in appjs, "app.js defines %s" % fn.split()[-1])
    ok(appjs.count("liveStart(") == 2, "liveStart is defined once and called once")
    ok(appjs.count("liveStop(") == 2,
       "and so is liveStop, in the finally that also clears S.busy")
    ok(appjs.count("livePhase(") >= 3,
       "the phase moves on a tool call and moves back when the sandbox is gone")
    ok("S.busy = false" in appjs and
       appjs.index("S.busy = false") < appjs.rindex("liveStop("),
       "liveStop sits with the line that ends the turn, not somewhere a "
       "thrown stream could skip")


def test_the_agent_routes_answer_per_agent():
    """Over real HTTP, because the question is whether the agent an editor
    asked about is the agent it gets back."""

    def body(base, app):
        code, raw, _ = get(base, "/api/state")
        st = json.loads(raw.decode("utf-8"))
        ok(code == 200, "/api/state answers")

        profs = st.get("profiles") or []
        ok(len(profs) == 4, "/api/state carries the four agents (%d)" % len(profs))
        ok(st.get("defaultAgent") == "diagnostics",
           "and says which one opens, so the bar is not empty on first paint")
        ok(all(p.get("policy") for p in profs),
           "each one brings its policy body, so the Mission panel does not "
           "need a second request that could land out of order")
        ok(all(p.get("label") for p in profs),
           "and the label the host worked out, so the UI never re-derives it")
        ok("profileNotes" in st, "the audit rides along for the warning dots")

        # The per-agent policy endpoint has to answer about the agent asked
        # for. Health and Paperwork differ on write, so confusing the two is
        # visible rather than subtle.
        code, raw, _ = get(base, "/api/policy?agent=health")
        health = json.loads(raw.decode("utf-8"))
        code2, raw2, _ = get(base, "/api/policy?agent=paperwork")
        paper = json.loads(raw2.decode("utf-8"))
        ok(code == 200 and code2 == 200, "/api/policy answers for a named agent")
        ok(not (health.get("paths") or {}).get("write"),
           "Health's policy comes back with no write grant")
        ok((paper.get("paths") or {}).get("write"),
           "Paperwork's comes back with one, so the two are not the same file")

        code, raw, _ = get(base, "/api/policy")
        host = json.loads(raw.decode("utf-8"))
        ok(host.get("name") == "host-default",
           "/api/policy with no agent is the host's own file, not an agent's")

        # Saving one agent's policy must not touch another's. The save route
        # lints first and refuses a policy with errors in it, and off Windows
        # ${windir} does not resolve to an absolute path, so every shipped
        # profile lints as an error here. That is this machine, not the app,
        # and pretending otherwise would mean weakening the route.
        # The isolation itself is one layer down and does not care what host
        # this is, so it is checked here either way. What the guard below
        # skips is only whether the route gets that far.
        edit = json.loads(json.dumps(health))
        edit.setdefault("limits", {})["timeoutMs"] = 12345
        app.profiles.save("health", edit)
        app.profiles.reload()
        ok(app.policy_for("health")["limits"]["timeoutMs"] == 12345,
           "saving a profile lands on that agent")
        ok(app.policy_for("paperwork") == paper,
           "and leaves every other agent's file alone")
        ok(app.reload_policy().get("name") == "host-default",
           "including policy.json, which an agent save must never reach")
        app.profiles.save("health", health)
        app.profiles.reload()

        import core.policy as policy_mod
        if not os.path.isabs(policy_mod.expand("${windir}", app.path_ctx())):
            ok(True, "the per-agent save is not checked over HTTP on a host "
                     "where ${windir} does not resolve, because the route "
                     "lints first and every shipped profile fails that lint "
                     "here. Run this on Windows for the rest.")
            return

        before = json.loads(json.dumps(paper))
        edited = json.loads(json.dumps(health))
        edited.setdefault("limits", {})["timeoutMs"] = 12345
        code, j = post(base, "/api/policy", {"agent": "health", "policy": edited})
        ok(code == 200 and j.get("saved") is True, "POST /api/policy saves an agent")
        ok(j.get("agent") == "health", "and says whose it saved")

        _, raw, _ = get(base, "/api/policy?agent=health")
        ok(json.loads(raw.decode("utf-8"))["limits"]["timeoutMs"] == 12345,
           "the edit is on disk for that agent")
        _, raw, _ = get(base, "/api/policy?agent=paperwork")
        ok(json.loads(raw.decode("utf-8")) == before,
           "and no other agent's file moved")
        _, raw, _ = get(base, "/api/policy")
        ok(json.loads(raw.decode("utf-8"))["name"] == "host-default",
           "including the host default, which is what the Run tab dry-runs")

        code, j = post(base, "/api/policy", {"agent": "nobody", "policy": edited})
        ok(code == 404, "saving onto an agent that does not exist is a 404, "
                        "not a quiet write to the host default")

    with_server(body)


def test_the_docs_describe_the_app_that_exists():
    """The docs were written when there was one agent and one policy file.

    A doc that names policy.json as the file the agents use sends somebody to
    edit a file that changes nothing they can see, which is a worse failure
    than no doc at all.
    """
    docs = {name: read(HERE, *name.split("/")) for name in
            ("README.md", "WORKSHOP.md", "COMPILED.md", "profiles/_readme.md")}

    for name, text in docs.items():
        ok("profiles\\" in text or "profiles/" in text,
           "%s says where the agents' policies live" % name)

    for name in ("README.md", "COMPILED.md", "profiles/_readme.md"):
        t = docs[name]
        ok(re.search(r"host-wide default", t),
           "%s calls policy.json the host-wide default" % name)
        ok(re.search(r"[Nn]o agent uses (it|this one)", t),
           "%s says no agent uses it, which is the part people get wrong"
           % name)

    # The wizard names one agent. A doc that still tells the room to talk to
    # a single assistant is describing the previous version of the app.
    for name, text in docs.items():
        stray = [ln.strip() for ln in text.splitlines()
                 if re.search(r"\bAssistant\b", ln)]
        ok(not stray, "%s does not still address a single Assistant (%s)"
                      % (name, stray[:1]))

    ok("four agents" in docs["README.md"].lower(),
       "the README opens on four agents rather than one")

    for name, text in docs.items():
        bad = [ln.strip() for ln in text.splitlines() if "—" in ln or "–" in ln]
        ok(not bad, "%s has no dashes we do not use (%s)" % (name, bad[:1]))


# =====================================================================

def test_the_bait_goes_everywhere_it_is_allowed_to():
    """The negative filesystem checks are the ones the whole workshop rests
    on, and they have now been wrong twice, both times because of where the
    bait file sat rather than because of anything the sandbox did. So the
    rules about that location get pinned here."""
    import core.verify as verify

    a = temp_app()
    home = tempfile.mkdtemp(prefix="ck-bait-")
    env = {"PUBLIC": os.path.join(home, "Public"),
           "PROGRAMDATA": os.path.join(home, "ProgramData"),
           "TEMP": os.path.join(home, "Temp"), "TMP": os.path.join(home, "Temp")}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spots, problem = verify._bait_locations(a)
        labels = [s[0] for s in spots]
        ok(problem is None, "somewhere ungranted exists, so the check can run")
        ok(len(spots) >= 3,
           "the bait goes to several ungranted places, not one. One probe "
           "cannot tell 'nothing is enforced' from 'one folder is reachable'")
        ok(len(set(labels)) == len(labels), "every bait location is named once")
        ok(all(os.path.isdir(s[1]) for s in spots),
           "every bait location was actually created")
        ok(all(os.path.basename(s[2]) == verify.BAIT_NAME for s in spots),
           "the bait file has the same name in each")

        # Your own Temp folder is the likeliest thing for a host to map into
        # every sandbox by default, which makes it the worst possible headline
        # and a useful control. It must not be first.
        ok(labels[0] != "your Temp folder",
           "Temp is not the headline location")
        ok("your Temp folder" in labels,
           "but Temp is still tried, because it is the interesting one")

        # The Oct 8 bug: ${project} got added to paths.read and the bait,
        # sitting inside it, came back readable and was reported as a
        # containment failure.
        pol = a.reload_policy()
        pol.setdefault("paths", {})["read"] = [a.project_dir]
        a.save_policy(pol)
        spots2, _ = verify._bait_locations(a)
        ok(all(not verify._under(s[1], a.project_dir) for s in spots2),
           "granting the project folder removes it as a bait location, which "
           "is the 8 Oct false alarm")

        # And if there is nowhere left, that is a refusal to test, not a pass.
        pol["paths"]["read"] = [home, a.project_dir]
        a.save_policy(pol)
        spots3, problem3 = verify._bait_locations(a)
        ok(spots3 == [] and problem3,
           "with everything granted the check says so instead of passing")
        ok("Narrow paths.read" in (problem3 or ""),
           "and it says what to do about it")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(home, ignore_errors=True)

    # The three verdicts are three different instructions, not three
    # intensities of the same one, so each has to say its own thing.
    some = verify._verdict("read", ["your Temp folder"], ["the Public folder"])
    none = verify._verdict("read", [], ["the Public folder"])
    allof = verify._verdict("read", ["the Public folder"], [])
    ok("REFUSED AND WAS NOT" not in none, "a clean sweep does not cry wolf")
    ok("not being enforced on this host at all" in allof,
       "everything leaking is reported as nothing being enforced")
    ok("not being enforced on this host at all" not in some,
       "one location leaking is NOT reported as nothing being enforced")
    ok("gap in the boundary rather than an absent boundary" in some,
       "it is reported as a gap in a working boundary")
    ok("REFUSED AND WAS NOT" in some,
       "but it still fails loudly, because a reachable ungranted folder is "
       "a reachable ungranted folder")
    ok("your Temp folder" in some and "the Public folder" in some,
       "and it names both sides, which is the whole point of sweeping")
    for v in (some, none, allof):
        ok("—" not in v and "–" not in v, "no dashes in the verdict")


def main():
    for fn in (test_name_filter, test_save_setup, test_host_and_workspace,
               test_http, test_dragon_slicing, test_house_style,
               test_launch_page_wiring, test_tokens,
               test_the_name_belongs_to_one_agent,
               test_the_prompt_tells_each_agent_its_own_name,
               test_agent_prompt_renders,
               test_every_profile_compiles_to_its_own_box,
               test_the_four_boxes_differ_only_where_they_should,
               test_the_ui_asks_for_ids_that_exist,
               test_the_mission_panel_reports_what_is_running,
               test_the_agent_routes_answer_per_agent,
               test_the_docs_describe_the_app_that_exists,
               test_the_bait_goes_everywhere_it_is_allowed_to):
        try:
            fn()
        except Exception as e:
            import traceback
            FAIL.append("%s blew up: %s" % (fn.__name__, e))
            traceback.print_exc()

    for f in FAIL:
        print("FAIL  " + f)
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
