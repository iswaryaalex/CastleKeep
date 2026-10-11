"""
prototype_agents.py - builds prototype-agents.html.

A standalone, clickable mock of the redesigned main page: four agents in a
bar across the top, each with its own conversation and its own sandbox policy. No server, no
model, no MXC. Open the file by double-clicking it.

It is generated rather than hand-written for one reason. The bar, the Mission
panel and the comparison card all describe what each agent is allowed to do,
and all three are built here from profiles/*.json. A prototype that claims a
boundary the policy does not have is worse than no prototype, because the
argument it is making is exactly that the boundary is real.

The replies are canned. That part is a mock and the page says so on its face.

    python3 prototype_agents.py
"""

import io
import json
import os
import sys

import critters

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["diagnostics", "finance", "health", "paperwork"]
SYS32 = "${windir}\\System32"
WORKSPACE = "${workspace}"


def read(*parts):
    with io.open(os.path.join(HERE, *parts), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Load and check the profiles
# ---------------------------------------------------------------------------

def load_profiles():
    out = []
    for name in ORDER:
        p = json.loads(read("profiles", "%s.json" % name))
        check_boundary(p)
        out.append(p)

    # The pairing is the entire argument, so assert it rather than trusting the
    # four files to stay consistent with each other. Exactly one agent may have
    # a network, and that agent must have nothing to send.
    online = [p for p in out if p["network"]["outbound"] == "allow"]
    assert len(online) == 1, "expected exactly one agent with a network, got %s" % (
        [p["name"] for p in online])
    assert online[0]["boundary"]["files"] == "no files", (
        "%s has a network and file access at the same time" % online[0]["name"])

    # The tool gate is host-side. If it differed between profiles, the four
    # boxes would be enforced by an if statement instead of by the container.
    gates = [{k: v for k, v in p["tools"].items() if k != "_note"} for p in out]
    assert all(g == gates[0] for g in gates), "the tool gate differs between profiles"

    # The bar label says what the agent is for. Policy language there competes
    # with the Mission panel and the comparison card, which say it properly and
    # in full, so keep it out.
    for p in out:
        t = p["task"]
        assert 0 < len(t) <= 26, "%s: task label %r is the wrong length" % (p["name"], t)
        leaked = [w for w in ("file", "folder", "network", "read", "write",
                              "sandbox", "policy", "container") if w in t.lower()]
        assert not leaked, "%s: task label talks about policy (%s)" % (p["name"], leaked)
    return out


def check_boundary(p):
    """The agent bar prints a two-word summary of each agent. This is what stops
    that summary drifting from the policy it summarises: widen a path
    list without updating the label and the build stops here."""
    label = p["boundary"]["files"]
    read_paths = [x for x in p["paths"]["read"] if x != SYS32]
    writes = p["paths"]["write"]
    name = p["name"]

    if label == "no files":
        assert not read_paths and not writes, \
            "%s says 'no files' but grants %s / %s" % (name, read_paths, writes)
    elif label == "one folder":
        assert len(read_paths) == 1 and not writes, \
            "%s says 'one folder' but grants %s / %s" % (name, read_paths, writes)
    elif label == "workspace":
        assert writes == [WORKSPACE] and WORKSPACE in read_paths, \
            "%s says 'workspace' but grants %s / %s" % (name, read_paths, writes)
    else:
        raise AssertionError("%s has an unknown files label %r" % (name, label))

    want = "network" if p["network"]["outbound"] == "allow" else "no network"
    assert p["boundary"]["network"] == want, \
        "%s says %r but outbound is %r" % (name, p["boundary"]["network"],
                                           p["network"]["outbound"])


# ---------------------------------------------------------------------------
# The canned conversations
# ---------------------------------------------------------------------------
#
# One entry per starter, in the same order the starters appear in the profile.
# A reply is a list of blocks: {"tool": ...} renders a tool-call card,
# {"say": ...} renders prose. The last starter of every agent asks it to do
# something outside its box, because that is the thing worth seeing.

CMD = r'"C:\Windows\System32\cmd.exe" /d /c '
PS = r'"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -EncodedCommand '
CURL = r'"C:\Windows\System32\curl.exe" '

NOT_FOUND = "The system cannot find the file specified."

SCRIPTS = {
    "diagnostics": [
        [{"tool": {"name": "device_info", "command": PS + "JABQAFMAVgBl\u2026",
                   "outcome": "ok", "ms": 840,
                   "out": "OS            Windows 11 Pro 24H2 (build 26120.1542)\n"
                          "CPU           AMD Ryzen AI 9 HX 370 w/ Radeon 890M\n"
                          "Cores         12 physical / 24 logical\n"
                          "Memory        64.0 GB total, 38.2 GB available\n"
                          "Uptime        2 days 04:11"}},
         {"say": "Nothing looks wrong. 38.2 GB of 64 GB is free, it has been up "
                 "two days, and you are on build 26120.1542. Ask me about disk or "
                 "memory specifically if you want me to dig."}],

        [{"tool": {"name": "list_processes", "command": PS + "JABwAHIAbwBj\u2026",
                   "outcome": "ok", "ms": 1120,
                   "out": "Name                    Working set\n"
                          "msedge                      1,842 MB\n"
                          "Code                        1,190 MB\n"
                          "lemonade-server               884 MB\n"
                          "python                        412 MB\n"
                          "explorer                      268 MB"}},
         {"say": "Edge is the biggest at 1.84 GB across its whole process tree, "
                 "then VS Code at 1.19 GB. On a 64 GB machine none of that is "
                 "worth acting on."}],

        [{"tool": {"name": "disk_space", "command": PS + "AEcAZQB0AC0A\u2026",
                   "outcome": "ok", "ms": 420,
                   "out": "Drive    Free         Total        Used\n"
                          "C:       412.6 GB     1,862.3 GB   77.8%\n"
                          "D:       1,201.0 GB   1,862.3 GB   35.5%"}},
         {"say": "C: has 412.6 GB free of 1.86 TB, so about 78 percent used. "
                 "D: is barely touched. Nothing needs attention yet."}],

        [{"tool": {"name": "read_file",
                   "command": CMD + r'type "C:\Users\iswaalex\Documents\notes.txt"',
                   "outcome": "blocked", "ms": 260,
                   "reason": "The path is not in this container's read list",
                   "out": NOT_FOUND}},
         {"say": "Refused. My read list is C:\\Windows\\System32 and nothing "
                 "else, so your Documents folder was never mapped into the "
                 "container.\n\nRead what Windows actually said. Not \"access is "
                 "denied\", but \"cannot find the file specified\". The folder is "
                 "not being withheld from me by a permission check. From in here "
                 "it does not exist. That is the same wall every agent on this "
                 "page runs into, and it is why none of us can be talked around "
                 "it.\n\nIf you want me reading that folder, add the path to "
                 "profiles\\diagnostics.json."}],
    ],
    "finance": [
        [{"tool": {"name": "fetch_url",
                   "command": CURL + "-s https://api.frankfurter.app/latest?from=GBP&to=USD",
                   "outcome": "ok", "ms": 410,
                   "out": '{"amount":1.0,"base":"GBP","date":"2026-10-08",'
                          '"rates":{"USD":1.2914}}'}},
         {"say": "1 GBP buys 1.2914 USD. That is the 2026-10-08 reference rate "
                 "from frankfurter.app, which republishes the European Central "
                 "Bank daily fixing, so it is yesterday's close rather than a "
                 "live quote. Your bank will give you a worse number than this "
                 "one."}],

        [{"tool": {"name": "fetch_url",
                   "command": CURL + "-s https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp",
                   "outcome": "ok", "ms": 880,
                   "out": "Date Changed      Rate\n"
                          "07 Aug 2026       3.75\n"
                          "19 Jun 2026       4.00\n"
                          "06 Feb 2026       4.25"}},
         {"say": "Bank Rate is 3.75 percent, set on 07 August 2026. That is the "
                 "third cut this year, down from 4.25 in February. The page I "
                 "read is the Bank's own rate history, so it is the primary "
                 "source rather than somebody reporting on it."}],

        [{"tool": {"name": "fetch_url",
                   "command": CURL + "-s https://api.metals.dev/v1/latest?metal=gold&currency=USD",
                   "outcome": "ok", "ms": 520,
                   "out": '{"metal":"gold","currency":"USD","unit":"toz",'
                          '"price":3412.60,"timestamp":"2026-10-09T09:41:00Z"}'}},
         {"say": "Gold is 3,412.60 USD per troy ounce as of 09:41 UTC today. I "
                 "am reporting the number, not suggesting you do anything with "
                 "it."}],

        [{"tool": {"name": "read_file",
                   "command": CMD + r'type "C:\Users\iswaalex\Documents\statement-sep.pdf"',
                   "outcome": "blocked", "ms": 230,
                   "reason": "This container has no file grants beyond System32",
                   "out": NOT_FOUND}},
         {"say": "Refused, and that is the arrangement rather than an "
                 "oversight.\n\nI am the only one of the four who can reach the "
                 "internet, so I am the one given nothing to take. No read list, "
                 "no write list, no statements, no spreadsheets. If I am ever "
                 "talked into doing something I should not, the worst I can do is "
                 "fetch a page and be wrong about it.\n\nPaperwork can open that "
                 "statement. Paperwork has no network."}],
    ],

    "health": [
        [{"tool": {"name": "list_files",
                   "command": CMD + r'dir /a "C:\Users\iswaalex\ms-ignite\castlekeep\workspace\clinic"',
                   "outcome": "ok", "ms": 310,
                   "out": "README.txt                 452\n"
                          "follow-ups.csv             224\n"
                          "intake-2026-03-11.txt      435\n"
                          "intake-2026-03-19.txt      424\n"
                          "rota-april.txt             331\n"
                          "               5 File(s)  1,866 bytes"}},
         {"say": "Five files: two visit notes, a follow-up list, the April clinic "
                 "rota, and a README saying every name and number in here was "
                 "invented for the workshop."}],

        [{"tool": {"name": "read_file",
                   "command": CMD + r'type "\u2026\workspace\clinic\intake-2026-03-11.txt"',
                   "outcome": "ok", "ms": 180,
                   "out": "NORTHWIND FAMILY PRACTICE - INTAKE NOTE (SAMPLE)\n"
                          "Record: NW-00412   Visit: 2026-03-11   Clinician: R. Okonjo\n"
                          "Patient: Marla Brandt, 41\n"
                          "Reason for visit: persistent cough, four weeks.\n"
                          "  Temperature 37.1 C. Resting pulse 78. Oxygen saturation 97 percent."}},
         {"tool": {"name": "read_file",
                   "command": CMD + r'type "\u2026\workspace\clinic\intake-2026-03-19.txt"',
                   "outcome": "ok", "ms": 170,
                   "out": "NORTHWIND FAMILY PRACTICE - INTAKE NOTE (SAMPLE)\n"
                          "Record: NW-00418   Visit: 2026-03-19   Clinician: R. Okonjo\n"
                          "Patient: Desmond Ilori, 63\n"
                          "Reason for visit: annual review.\n"
                          "  Blood pressure 138/86, down from 146/92 in September."}},
         {"say": "Two visits, both with R. Okonjo.\n\n11 March, record NW-00412: "
                 "four weeks of cough. Temperature 37.1, pulse 78, oxygen 97 "
                 "percent, chest clear. Started on an inhaled steroid with a "
                 "review booked for the 25th.\n\n19 March, record NW-00418: "
                 "annual review. Blood pressure 138/86, down from 146/92 in "
                 "September. Weight and medication unchanged, no follow-up "
                 "needed.\n\nI am reading what the notes say, not interpreting "
                 "it. Anything in here you want explained is a question for the "
                 "practice."}],

        [{"tool": {"name": "read_file",
                   "command": CMD + r'type "\u2026\workspace\clinic\follow-ups.csv"',
                   "outcome": "ok", "ms": 150,
                   "out": "record,patient,booked,clinician,reason\n"
                          "NW-00412,Marla Brandt,2026-03-25,R. Okonjo,review inhaler trial\n"
                          "NW-00431,Priya Raghavan,2026-04-02,T. Lindqvist,repeat bloods\n"
                          "NW-00437,Owen Castellanos,2026-04-09,R. Okonjo,wound check"}},
         {"say": "The next one on record NW-00412 is 25 March 2026 with R. "
                 "Okonjo, to review the inhaler trial. The 11 March note books "
                 "the same appointment, so the two agree.\n\nThe file lists two "
                 "others after that, on 2 April and 9 April, against different "
                 "records."}],

        [{"tool": {"name": "write_file",
                   "command": PS + "AEEAZABkAC0AQwBvAG4\u2026",
                   "outcome": "blocked", "ms": 240,
                   "reason": "This container has no write list",
                   "out": NOT_FOUND}},
         {"say": "Refused. I have no write list at all, so the notes folder came "
                 "into the container read-only and there is no writable path in "
                 "here to append to.\n\nWorth noticing where that no came from. "
                 "write_file is switched on for me, same as for every agent on "
                 "this page. The request was built, it was sent, and the "
                 "container stopped it. I did not decline out of politeness and "
                 "there is no wording of the question that gets a different "
                 "answer.\n\nMedical records are a reasonable thing to want an "
                 "assistant near and an unreasonable thing to let one edit."}],
    ],

    "paperwork": [
        [{"tool": {"name": "list_files",
                   "command": CMD + r'dir /a "C:\Users\iswaalex\ms-ignite\castlekeep\workspace"',
                   "outcome": "ok", "ms": 290,
                   "out": "2026-10-09  <DIR>          clinic\n"
                          "2026-09-28             1,204  aviva-renewal.txt\n"
                          "2026-04-30             4,412  council-tax-2026.txt\n"
                          "2026-10-01               318  broadband-bill-sep.txt\n"
                          "2026-05-22             5,120  p60-2025-26.txt\n"
                          "2026-09-30                 0  placeholder.log\n"
                          "2026-08-14             2,944  sa302-2024-25.txt\n"
                          "2026-10-08                88  scratch.txt"}},
         {"say": "Seven files and one folder. An Aviva renewal, the council tax "
                 "bill, a broadband bill, a P60, an SA302, an empty log from "
                 "September and a scratch file. The clinic folder belongs to "
                 "Health, so I will leave it alone."}],

        [{"say": "Here is what I would do. I will not touch anything until you "
                 "say go.\n\ninsurance\\ for aviva-renewal.txt. tax\\ for "
                 "p60-2025-26.txt, sa302-2024-25.txt and council-tax-2026.txt, "
                 "although council tax is arguably a bill rather than tax. "
                 "bills\\ for broadband-bill-sep.txt.\n\nplaceholder.log is 0 "
                 "bytes and ten days old, so I would rather ask whether to delete "
                 "it than quietly move it. Say go and I will start with "
                 "insurance\\."}],

        [{"tool": {"name": "move_file", "command": PS + "AFIAZQBuAGEAbQBl\u2026",
                   "outcome": "ok", "ms": 510,
                   "out": "aviva-renewal.txt      -> 2026-09-28-aviva-renewal.txt\n"
                          "broadband-bill-sep.txt -> 2026-10-01-broadband-bill.txt\n"
                          "council-tax-2026.txt   -> 2026-04-30-council-tax.txt\n"
                          "p60-2025-26.txt        -> 2026-05-22-p60.txt\n"
                          "sa302-2024-25.txt      -> 2026-08-14-sa302.txt"}},
         {"say": "Done, five renamed. Each is now prefixed with its last modified "
                 "date so they sort in order. I used the file dates rather than "
                 "the dates printed inside the documents, which are not always "
                 "the same thing. Say the word if you would rather I read each "
                 "one and use the date on the paper."}],

        [{"tool": {"name": "list_files",
                   "command": CMD + r'dir /a "C:\Users\iswaalex\Documents"',
                   "outcome": "blocked", "ms": 250,
                   "reason": "The path is not in this container's read list",
                   "out": NOT_FOUND}},
         {"say": "Refused, and I cannot even list that folder to tell you what I "
                 "would have found.\n\nMy read list and my write list are the "
                 "same single folder. That is the thing that makes me safe to "
                 "turn loose on your filing: the only folder I can change is the "
                 "only folder I can see. Move the tax documents into the "
                 "workspace and I will file them.\n\nWidening me to your home "
                 "folder is one line in profiles\\paperwork.json. It is a bigger "
                 "change than it looks, because I am the one agent here that can "
                 "overwrite things."}],
    ],
}

FALLBACK = ("This is a clickable prototype, so the only answers I have are "
            "scripted ones. Try one of the suggested questions and you will get "
            "a real-looking tool call, including the refusals.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

EXTRA_CSS = """
/* ---- the agent bar --------------------------------------------------- */
/* Across the top, not down the side. Four boundaries side by side read as one
   set you compare; stacked in the rail they read as a menu, and a menu invites
   you to pick one rather than to notice that Diagnostics and Finance differ by
   exactly one thing. */
.agentbar{display:flex; gap:10px; padding:14px 16px; background:var(--surface2);
  border-bottom:1px solid var(--border)}
.agent{
  flex:1 1 0; min-width:0; display:flex; align-items:center; gap:11px;
  padding:9px 12px; border:1px solid var(--border); border-radius:11px;
  background:var(--surface); cursor:pointer; text-align:left; color:var(--ink2);
}
.agent:hover{border-color:var(--border2); background:var(--surface2)}
.agent.on{background:var(--brand-soft); border-color:var(--brand-line);
  color:var(--brand-ink)}
.agent .tx{min-width:0}
/* The agent name is the one piece of display type in the bar. It is a name,
   not a control, and setting it in the serif is what stops four buttons in a
   row from reading as a toolbar. 15px against the 13px it replaces, because
   Garamond sits lower on the line than the sans does. */
.agent .nm{display:block; font-family:var(--serif); font-size:15px;
  font-weight:600; line-height:1.15}
.agent .bd{display:block; font-size:10.5px; font-weight:600; color:var(--muted);
  line-height:1.3; margin-top:2px; white-space:nowrap; overflow:hidden;
  text-overflow:ellipsis}
.agent.on .bd{color:#7A6615}

/* ---- the sprites ----------------------------------------------------- */
/* Three frames stacked, one visible at a time. Switching opacity on a
   steps(1,end) timeline rather than cross-fading is what keeps pixel art
   looking like pixel art: a half-faded frame is just a blurry frame. */
.sprite{position:relative; flex:0 0 30px; width:30px; height:30px; --d:0s}
.sprite svg{position:absolute; inset:0; width:100%; height:100%;
  image-rendering:pixelated}
.sprite .f-blink, .sprite .f-move{opacity:0}
.sprite.md{flex:0 0 40px; width:40px; height:40px}
.sprite.lg{flex:0 0 76px; width:76px; height:76px}

@media (prefers-reduced-motion: no-preference){
  .sprite .f-idle {animation:ck-idle  7s var(--d) infinite steps(1,end)}
  .sprite .f-blink{animation:ck-blink 7s var(--d) infinite steps(1,end)}
  .sprite .f-move {animation:ck-move  7s var(--d) infinite steps(1,end)}
}
/* One blink and one small move in seven seconds, and the four agents are
   offset from each other so the rail never moves all at once. Anything
   livelier than this is a thing you have to look away from. */
@keyframes ck-idle{
  0%,60.9%{opacity:1} 61%,64.9%{opacity:0}
  65%,86.9%{opacity:1} 87%,92.9%{opacity:0} 93%,100%{opacity:1}}
@keyframes ck-blink{0%,60.9%{opacity:0} 61%,64.9%{opacity:1} 65%,100%{opacity:0}}
@keyframes ck-move {0%,86.9%{opacity:0} 87%,92.9%{opacity:1} 93%,100%{opacity:0}}

/* ---- the comparison card -------------------------------------------- */
.grid4{display:flex; flex-direction:column; gap:1px; background:var(--hair);
  border:1px solid var(--border); border-radius:9px; overflow:hidden}
.grid4 .g{display:flex; align-items:center; gap:9px; padding:9px 12px;
  background:var(--surface); font-size:11.5px}
.grid4 .g.on{background:var(--brand-soft)}
.grid4 .g .t{font-weight:700; flex:0 0 78px; color:var(--ink2)}
.grid4 .g .f{flex:1; min-width:0; color:var(--muted); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis}
.grid4 .g .n{flex:0 0 66px; text-align:right; font-weight:600; color:var(--muted)}
.grid4 .g .n.yes{color:var(--coral)}

.banner{background:var(--info-soft); border:1px solid var(--info-line);
  color:var(--info); font-size:11.5px; font-weight:600; padding:7px 14px;
  text-align:center}
.pane-head .tag{font-size:10.5px; font-weight:700; color:var(--muted);
  border:1px solid var(--border); border-radius:9px; padding:2px 8px}
.empty .starters{margin-top:20px}
"""

PAGE = u"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CastleKeep agents, prototype</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 22 22'><rect width='22' height='22' rx='5' fill='%%23F5CE3E'/><rect x='6' y='7' width='3' height='9' fill='%%235C4B00'/><rect x='13' y='7' width='3' height='9' fill='%%235C4B00'/><rect x='6' y='5' width='10' height='3' fill='%%235C4B00'/></svg>">
<style>
%(tokens)s
%(style)s
%(extra)s
</style>
</head>
<body>

<div class="banner">Prototype. The policies below are read from
  <code>profiles/</code> and are real. The replies are scripted and no sandbox
  is running.</div>

<header class="titlebar">
  <span class="brand">
    <span class="avatar" id="brandMark"></span>
    <span class="brand-name">CastleKeep</span>
    <span class="brand-sub">four agents, four boxes</span>
  </span>
  <div class="titlebar-right">
    <span class="chip ok">BaseContainer</span>
    <span class="chip">Qwen3-8B-GGUF</span>
  </div>
</header>

<div class="shell">

  <nav class="rail">
    <div class="rail-label">Workspace</div>
    <div class="rail-chip" title="C:\\Users\\iswaalex\\ms-ignite\\castlekeep\\workspace">
      <span>&hellip;\\castlekeep\\workspace</span></div>

    <div class="rail-label">This machine</div>
    <button class="nav"><i data-ic="panel"></i>Control Panel</button>
    <button class="nav"><i data-ic="shield"></i>Policy</button>
    <button class="nav"><i data-ic="terminal"></i>Run</button>
    <button class="nav"><i data-ic="sliders"></i>Settings</button>

    <div class="rail-foot">
      <div class="rail-label" id="footLabel">This conversation</div>
      <div class="rail-stat"><span id="statCalls">0</span><em>sandboxes spawned</em></div>
      <div class="rail-stat"><span id="statRefused" class="deny">0</span><em>refused</em></div>
    </div>
  </nav>

  <main class="tab on">
    <div class="agentbar" id="agents"></div>
    <div class="split">
      <section class="pane chat-pane">
        <div class="pane-head">
          <div>
            <h1 id="headName"></h1>
            <p class="sub" id="headSub"></p>
          </div>
          <span class="tag right" id="headTag"></span>
          <button class="btn ghost" id="clearChat">New conversation</button>
        </div>
        <div class="transcript" id="transcript"></div>
        <form class="composer" id="composer">
          <textarea id="input" rows="1"></textarea>
          <button class="btn primary" type="submit">Send</button>
        </form>
      </section>

      <aside class="pane side">
        <div class="pane-head"><h1>Mission</h1></div>
        <div class="scroll pad">
          <div class="card">
            <div class="card-title">In force right now</div>
            <div id="missionPolicy" class="mini"></div>
            <button class="btn ghost full">Change this agent's policy</button>
          </div>
          <div class="card">
            <div class="card-title">Sandbox activity</div>
            <div id="missionRuns" class="runlist"></div>
          </div>
          <div class="card">
            <div class="card-title">All four</div>
            <p class="card-sub">Same model, same loop, same nine tools. The only
               thing that differs is the box each one's tool calls run inside.</p>
            <div class="grid4" id="grid4"></div>
            <p class="card-sub" style="margin:10px 0 0">Read the last column
               against the middle one. The only agent that can reach the network
               is the only agent with nothing of yours to send.</p>
          </div>
        </div>
      </aside>
    </div>
  </main>

</div>

<script>
const CRITTERS = %(critters)s;
const PROFILES = %(profiles)s;
const SCRIPTS  = %(scripts)s;
const FALLBACK = %(fallback)s;
const DRAGON_MARK = %(mark)s;

const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function sprite(name, cls, delay){
  const f = CRITTERS[name];
  const one = (k, c) =>
    '<svg viewBox="0 0 22 22" class="' + c + '" shape-rendering="crispEdges">' +
    f[k] + '</svg>';
  return '<span class="sprite ' + (cls||'') + '" style="--d:' + (delay||0) + 's">' +
    one('idle','f-idle') + one('blink','f-blink') + one('move','f-move') + '</span>';
}

/* Each agent keeps its own thread. Switching agents swaps the whole
   conversation rather than dropping a divider into a shared one: the policy
   changed, so the transcript above the switch was produced under rules that no
   longer apply, and running the two together invites reading it as one. */
const threads = {};
PROFILES.forEach(p => threads[p.name] = []);
let active = PROFILES[0].name;

const prof = () => PROFILES.find(p => p.name === active);

function paintRail(){
  $('#agents').innerHTML = PROFILES.map((p, i) =>
    '<button class="agent' + (p.name === active ? ' on' : '') +
    '" data-agent="' + p.name + '">' +
      sprite(p.critter, 'md', -1.7 * i) +
      '<span class="tx"><span class="nm">' + esc(p.title) + '</span>' +
      /* The task, not the policy. What an agent is allowed to do belongs in
         Mission and in the comparison card below it. What it is for belongs
         here, because that is the question you are answering when you pick
         one. */
      '<span class="bd">' + esc(p.task) + '</span></span></button>').join('');

  /* No sprites in this card. The four of them are 40px and moving directly
     above it, and a second row of the same animals competes with that. */
  $('#grid4').innerHTML = PROFILES.map(p =>
    '<div class="g' + (p.name === active ? ' on' : '') + '">' +
      '<span class="t">' + esc(p.title) + '</span>' +
      /* Only say "read" or "write" where there is something to read or write.
         "no files, read only" would be a sentence about an ability this agent
         does not have. */
      '<span class="f">' + esc(p.boundary.files) +
        (p.boundary.files === 'no files' ? ''
          : p.paths.write.length ? ', write' : ', read') + '</span>' +
      '<span class="n' + (p.network.outbound === 'allow' ? ' yes' : '') + '">' +
      esc(p.boundary.network) + '</span></div>').join('');
}

function paintHead(){
  const p = prof();
  $('#headName').textContent = p.title;
  $('#headSub').textContent = p.tagline;
  $('#headTag').textContent = p.containment;
  $('#input').placeholder = 'Ask ' + p.title + ' something\\u2026';
}

function paintMission(){
  const p = prof();
  const list = a => a.length ? a.map(x => '<code>' + esc(x) + '</code>').join('<br>')
                             : '<span class="muted">nothing</span>';
  const off = Object.keys(p.tools).filter(k => k !== '_note' && !p.tools[k]);
  $('#missionPolicy').innerHTML = [
    ['Readable',  list(p.paths.read)],
    ['Writable',  list(p.paths.write)],
    ['Network',   p.network.outbound === 'allow'
        ? 'outbound allowed' + (p.network.localNetwork ? ', including localhost' : '')
        : 'no outbound at all'],
    ['Containment', esc(p.containment)],
    ['Timeout',   (p.limits.timeoutMs / 1000) + 's per tool call'],
    ['Tools off', off.length ? off.map(x => '<code>' + x + '</code>').join(' ')
                             : '<span class="muted">none</span>'],
  ].map(r => '<div class="row"><b>' + r[0] + '</b><span>' + r[1] + '</span></div>').join('');

  const runs = threads[active].flatMap(m => m.blocks || [])
    .filter(b => b.tool).map(b => b.tool);
  $('#missionRuns').innerHTML = runs.length ? runs.map(t =>
    '<div class="r"><span class="chip ' + (t.outcome === 'ok' ? 'ok' : 'bad') + '">' +
    t.outcome + '</span><span class="mono">' + esc(t.name) + '</span>' +
    '<span class="right muted">' + t.ms + 'ms</span></div>').join('')
    : '<p class="muted">Nothing has run in this conversation yet.</p>';

  $('#statCalls').textContent = runs.length;
  $('#statRefused').textContent = runs.filter(t => t.outcome !== 'ok').length;
}

function toolCard(t){
  return '<details class="toolcall ' + t.outcome + '">' +
    '<summary><span class="chip ' + (t.outcome === 'ok' ? 'ok' : 'bad') + '">' +
      t.outcome + '</span><span class="tname">' + esc(t.name) + '</span>' +
      '<span class="right muted">' + t.ms + 'ms</span></summary>' +
    '<div class="detail"><pre class="out">' + esc(t.command) + '</pre>' +
      (t.reason ? '<p class="card-sub" style="margin:10px 0 0">' + esc(t.reason) +
                  '</p>' : '') +
      '<pre class="out">' + esc(t.out) + '</pre></div></details>';
}

function paintTranscript(){
  const p = prof(), box = $('#transcript'), msgs = threads[active];
  if (!msgs.length){
    box.innerHTML = '<div class="empty">' + sprite(p.critter, 'lg', 0) +
      '<h2>' + esc(p.title) + '</h2><p>' + esc(p.description) + '</p>' +
      '<div class="starters">' + p.starters.map((s, i) =>
        '<button class="starter" data-i="' + i + '">' + esc(s) + '</button>').join('') +
      '</div></div>';
    return;
  }
  box.innerHTML = msgs.map(m => {
    if (m.role === 'user')
      return '<div class="msg user"><div class="bubble">' + esc(m.text) + '</div></div>';
    return '<div class="msg assistant"><div class="who">' +
      sprite(p.critter, '', 0) + '</div><div class="body">' +
      '<div class="name">' + esc(p.title) + '</div>' +
      m.blocks.map(b => b.tool ? toolCard(b.tool)
        : '<div class="bubble">' + esc(b.say) + '</div>').join('') +
      '</div></div>';
  }).join('');
  box.scrollTop = box.scrollHeight;
}

function paint(){ paintRail(); paintHead(); paintMission(); paintTranscript(); }

function send(text, starterIndex){
  const p = prof();
  threads[active].push({role:'user', text:text});
  const script = (SCRIPTS[active] || [])[starterIndex === undefined ? -1 : starterIndex];
  threads[active].push({role:'assistant',
                        blocks: script || [{say: FALLBACK}]});
  paint();
}

document.addEventListener('click', e => {
  const a = e.target.closest('.agent');
  if (a){ active = a.dataset.agent; paint(); return; }
  const s = e.target.closest('.starter');
  if (s){ send(prof().starters[+s.dataset.i], +s.dataset.i); return; }
  if (e.target.id === 'clearChat'){ threads[active] = []; paint(); }
});

$('#composer').addEventListener('submit', e => {
  e.preventDefault();
  const v = $('#input').value.trim();
  if (!v) return;
  $('#input').value = '';
  send(v);
});

$('#brandMark').innerHTML = DRAGON_MARK;
paint();
</script>
</body>
</html>
"""


def build():
    profiles = load_profiles()
    frames = {n: critters.frames(n) for n in critters.CREATURES}

    # Used in all four profiles, so check the art exists for each.
    for p in profiles:
        assert p["critter"] in frames, "%s wants a %r and there is no such sprite" % (
            p["name"], p["critter"])
    assert len({p["critter"] for p in profiles}) == len(profiles), \
        "two agents share a sprite, which defeats the point of the rail"

    # tokens.css is inlined into a page that sits at the repo root, one level
    # above the stylesheet it came from, so its relative @font-face paths have
    # to move up with it. Nothing visible breaks if this is missed, which is
    # exactly why it is worth doing here rather than remembering to.
    tokens = read("ui", "tokens.css")
    assert 'url("fonts/' in tokens, "tokens.css no longer declares a local font"
    tokens = tokens.replace('url("fonts/', 'url("ui/fonts/')

    html = PAGE % {
        "tokens": tokens,
        "style": read("ui", "style.css"),
        "extra": EXTRA_CSS,
        "critters": json.dumps(frames, sort_keys=True),
        "profiles": json.dumps(profiles, sort_keys=False),
        "scripts": json.dumps(SCRIPTS),
        "fallback": json.dumps(FALLBACK),
        "mark": json.dumps(critters.svg(frames["dragon"]["idle"], 22)),
    }

    # The house style forbids em dashes anywhere in our own prose, and a
    # generated file is the easiest place for one to sneak in unnoticed.
    bad = [c for c in (u"\u2014", "&mdash;") if c in html]
    assert not bad, "em dash in the generated page: %s" % bad

    out = os.path.join(HERE, "prototype-agents.html")
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print("wrote prototype-agents.html  (%d KB, %d agents)"
          % (len(html) / 1024, len(profiles)))
    return out


if __name__ == "__main__":
    build()
