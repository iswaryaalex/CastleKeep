/*
 * CastleKeep UI.
 *
 * One rule runs through this file: nothing here decides anything. Every tier,
 * every capability, every refusal on screen came from the host - from
 * `wxc-exec --probe`, from a --dry-run, or from a sandbox that really ran and
 * really failed. If the server did not say it, this file does not draw it.
 */

import { dragonSvg } from "/dragon.js";
import { CRITTERS } from "/critters.js";

const $  = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const esc = (s) => String(s == null ? "" : s);

const S = {
  state: null,
  agent: null,       // id of the agent on screen
  threads: {},       // per agent: { el, history, calls, refused }
  policy: null,      // working copy for policyAgent, may be dirty
  policyAgent: null, // whose policy the Policy tab is editing; "" is the host
  dirty: false,
  busy: false,
  abort: null,
  warmPoll: null,    // interval id while the model's weights load
  folded: {},        // pane id -> true while that side panel is a strip
};

/* ====================================================================== */
/* the agents                                                              */
/* ====================================================================== */

/* Everything about the four comes from /api/state, which read it from
 * profiles\. Nothing in this file knows how many there are, what they are
 * called, or what any of them may reach. */
function profiles() {
  return (S.state || {}).profiles || [];
}

/* Falls back to the first agent rather than returning null, because an
 * unknown id is a bug in the caller and the honest failure for it is
 * "you got Diagnostics", not a blank page. Use known() to ask whether an id
 * is real - this function cannot answer that. */
function profile(name) {
  const all = profiles();
  return all.find((p) => p.name === name) || all[0] || null;
}

function known(name) {
  return !!name && profiles().some((p) => p.name === name);
}

function active() {
  return profile(S.agent);
}

/* The label is the server's, not ours. One agent answers to the name typed on
 * the launch screen and the other three go by their job title, and that
 * decision is made in one place in Python so the bar, the transcript, the
 * roster in the system prompt and the Control Panel cannot disagree. */
function label(p) {
  return p ? (p.label || p.title || p.name) : "the agent";
}

/* Whatever the person called their assistant on the launch screen. It names
 * exactly one of the four. */
function who() {
  return ((S.state || {}).setup || {}).assistantName || "Assistant";
}

/* Three frames stacked, one visible at a time, driven entirely by CSS. The
 * delay is passed in so the four in the bar never blink together. */
function sprite(name, cls, delay) {
  const f = CRITTERS[name] || CRITTERS.dragon;
  const one = (k, c) =>
    '<svg viewBox="0 0 22 22" class="' + c + '" shape-rendering="crispEdges">' +
    f[k] + "</svg>";
  const n = el("span", "sprite " + (cls || ""));
  n.style.setProperty("--d", (delay || 0) + "s");
  n.innerHTML = one("idle", "f-idle") + one("blink", "f-blink") + one("move", "f-move");
  return n;
}

/* ====================================================================== */
/* dragon                                                                  */
/* ====================================================================== */

/* The mark in the titlebar, and the only thing left that uses the six-state
 * dragon. It is CastleKeep's own mark rather than any one agent's, which is
 * why it still reacts while an owl or a cat is the one talking. */
function setDragon(state) {
  const n = $("brandDragon");
  if (n) n.innerHTML = dragonSvg(state);
}

/* ====================================================================== */
/* chrome                                                                  */
/* ====================================================================== */

function toast(msg, bad) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast on" + (bad ? " bad" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = "toast"), 3200);
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("on", t.id === "tab-" + name));
  document.querySelectorAll(".nav").forEach((b) =>
    b.classList.toggle("on", b.dataset.tab === name));
  location.hash = name;
}

document.querySelectorAll(".nav").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));
document.body.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) showTab(g.dataset.goto);
});

/* ====================================================================== */
/* http                                                                    */
/* ====================================================================== */

async function getJSON(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  const body = await r.json();
  if (!r.ok && body.error) throw new Error(body.error);
  return body;
}

async function postJSON(url, obj) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(obj || {}),
  });
  const body = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, body };
}

/* Server-sent events over POST. fetch + a ReadableStream, because EventSource
 * is GET-only and these endpoints all take a body. */
async function sse(url, payload, onEvent, signal) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
    signal,
  });
  if (!r.ok || !r.body) throw new Error("stream failed: HTTP " + r.status);

  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try { onEvent(JSON.parse(line.slice(5).trim())); }
        catch (_) { /* a half-written frame; the next read completes it */ }
      }
    }
  }
}

/* ====================================================================== */
/* hydrate                                                                 */
/* ====================================================================== */

async function hydrate() {
  const st = await getJSON("/api/state");
  S.state = st;

  // Settle who is on screen before anything draws. defaultAgent is the first
  // profile in profiles\, in the order the server lists them.
  if (!known(S.agent)) S.agent = st.defaultAgent || (profiles()[0] || {}).name || null;
  if (S.policyAgent == null) S.policyAgent = S.agent;
  if (S.policyAgent && !known(S.policyAgent)) S.policyAgent = "";
  if (!S.dirty) S.policy = JSON.parse(JSON.stringify(policySource()));

  document.title = "Keeper · " + who();
  renderChrome();
  renderAgents();
  renderRailMissions();
  renderHead();
  showThread();
  renderMission();
  renderSandboxPanel();
  renderControl();
  renderPolicy();
  renderRunTab();
  renderSettings();
}

/* ------------------------------------------------------------ agent bar */

/* Why the bar is empty, which is two very different problems.
 *
 * ui\ is read off disk on every request, so a server started before the
 * four-agent build serves this page quite happily and then answers /api/state
 * without a profiles key at all. That looks identical to an empty profiles\
 * folder and is fixed by restarting rather than by going to look at files
 * that are sitting there perfectly intact. Telling them apart costs one
 * check, and the key being absent is the tell. */
function noAgentsReason() {
  const st = S.state || {};
  if (!("profiles" in st)) {
    return "This page is newer than the server answering it: /api/state came " +
           "back without an agent list at all. Stop run.py and start it again. " +
           "Nothing is wrong with profiles\\.";
  }
  return "No agent profiles were found. Expected profiles\\diagnostics.json " +
         "and three more beside it.";
}

function renderAgents() {
  const bar = $("agents");
  bar.innerHTML = "";
  const list = profiles();

  if (!list.length) {
    bar.appendChild(el("p", "muted", noAgentsReason()));
  }

  list.forEach((p, i) => {
    const b = el("button", "agent" + (p.name === S.agent ? " on" : ""));
    b.type = "button";
    b.dataset.agent = p.name;
    b.appendChild(sprite(p.critter, "md", -1.7 * i));
    const tx = el("span", "tx");
    /* Show the role title (e.g. "System") in the bar, not the personal name
     * the launch wizard assigned — that name belongs in the chat head. */
    tx.appendChild(el("span", "nm", p.title || p.name));
    tx.appendChild(el("span", "bd", p.task));
    b.appendChild(tx);
    if ((p.notes || []).length) {
      b.appendChild(el("span", "warn-dot"));
      b.title = p.notes.map((n) => n.message).join("\n");
    }
    bar.appendChild(b);
  });

  /* Drift between what a profile says about itself and what it grants. The
   * app keeps running on it - widening a grant and watching a refusal stop
   * happening is the whole demo - so the drift has to say so instead. */
  const notes = (S.state.profileNotes || []);
  const box = $("agentNotes");
  box.innerHTML = "";
  box.classList.toggle("hidden", !notes.length);
  for (const n of notes) {
    const p = profile(n.profile);
    const line = el("div", "l " + (n.level === "error" ? "error" : "warn"));
    line.appendChild(el("b", null, (n.profile ? label(p) : "profiles") + " · " + n.field));
    line.appendChild(el("span", null, n.message));
    box.appendChild(line);
  }

  renderGrid4();
}

function renderGrid4() {
  const box = $("grid4");
  box.innerHTML = "";
  /* No sprites in this card. The four of them are 40px and moving directly
   * above it, and a second row of the same animals competes with that. */
  for (const p of profiles()) {
    const pol = p.policy || {};
    const writes = ((pol.paths || {}).write || []).length;
    const files = (p.boundary || {}).files || "";
    const row = el("div", "g" + (p.name === S.agent ? " on" : ""));
    row.appendChild(el("span", "t", label(p)));
    /* Only say "read" or "write" where there is something to read or write.
     * "no files, read only" would be a sentence about an ability this agent
     * does not have. */
    row.appendChild(el("span", "f",
      files + (files === "no files" ? "" : (writes ? ", write" : ", read"))));
    const online = (pol.network || {}).outbound === "allow";
    row.appendChild(el("span", "n" + (online ? " yes" : ""),
      (p.boundary || {}).network || ""));
    box.appendChild(row);
  }
}

function renderHead() {
  const p = active();
  const mark = $("chatSprite");
  mark.innerHTML = "";
  if (p) mark.appendChild(sprite(p.critter, "md", 0));
  $("headName").textContent = label(p);
  $("headSub").textContent = p ? p.tagline : "";
  $("headTag").textContent = p ? ((p.policy || {}).containment || "") : "";
  $("input").placeholder = "Ask " + label(p) + " something…";
  $("footLabel").textContent = "This conversation";
}

function switchAgent(name) {
  if (name === S.agent) return;
  S.agent = name;
  /* The Policy tab follows unless you were part-way through an edit, because
   * walking back to it and finding a different agent's grants in the form is
   * how you save one agent's policy onto another. */
  if (!S.dirty) {
    S.policyAgent = name;
    S.policy = JSON.parse(JSON.stringify(policySource()));
    renderPolicy();
  }
  renderAgents();
  renderRailMissions();
  renderHead();
  showThread();
  renderMission();
  renderSandboxPanel();
  if (S.state) renderSetupSteps();
}

document.body.addEventListener("click", (e) => {
  const a = e.target.closest(".agent");
  if (a) switchAgent(a.dataset.agent);
});

function renderChrome() {
  const st = S.state;
  const caps = st.capabilities || {};
  const probe = st.probe || {};
  const tier = $("tierChip");

  if (!probe.available) {
    tier.className = "chip bad";
    tier.textContent = "no sandbox";
    tier.title = probe.error || "wxc-exec --probe did not succeed";
  } else {
    tier.className = "chip ok";
    tier.textContent = caps._tierLabel || probe.tier || "unknown tier";
    tier.title = "Reported by wxc-exec --probe on this machine.";
  }

  /* The model chip reports three different things and they are not the same
   * thing: is Lemonade up, is it serving the model we asked for, and are the
   * weights resident yet. "Lemonade is up" is the one that means least, and
   * showing it as a green tick is how a preflight ends up lying. A named
   * model that is not loaded is a hard failure here, not a warning. */
  const lem = st.lemonade || {};
  const warm = st.warmup || {};
  const m = $("modelChip");
  if (!lem.reachable) {
    m.className = "chip bad";
    m.textContent = "Lemonade down";
  } else if (!lem.modelPresent) {
    m.className = "chip bad";
    m.textContent = "not serving " + (lem.model || "the model");
  } else if (warm.state === "warming") {
    m.className = "chip info";
    m.textContent = "warming " + (lem.model || "");
  } else if (warm.state === "failed") {
    m.className = "chip bad";
    m.textContent = "model failed to load";
  } else if (warm.state === "ready") {
    m.className = "chip ok";
    m.textContent = lem.model + "  ready";
  } else {
    m.className = "chip ok";
    m.textContent = lem.model;
  }
  m.title = warm.error || lem.note ||
            (warm.state === "ready"
             ? "Warmed in " + ((warm.ms || 0) / 1000).toFixed(1) +
               "s, so the first message will not stall."
             : (lem.baseUrl || "") + (lem.routePrefix || ""));

  /* Keep polling while the weights load so the chip flips to ready on its
   * own. Nobody should have to refresh the page to find out. */
  if (warm.state === "warming" && !S.warmPoll) {
    S.warmPoll = setInterval(async () => {
      try {
        const h = await (await fetch("/api/health")).json();
        if ((h.warmup || {}).state !== "warming") {
          clearInterval(S.warmPoll);
          S.warmPoll = null;
          hydrate();
        }
      } catch (e) { /* server restarting; try again on the next tick */ }
    }, 2000);
  }

  // The rail is 232px wide and a project path is not, so show the tail and
  // keep the whole thing on the tooltip. The tail is the part that tells you
  // which folder you are in; the head is the same on every machine.
  var dir = st.projectDir || "";
  var seg = dir.split("\\").filter(Boolean);
  $("hostPath").textContent =
    seg.length > 2 ? "\u2026\\" + seg.slice(-2).join("\\") : dir;
  $("hostChip").title = dir;
}

/* ---------------------------------------------------------------- mission */

function policySummary(p) {
  const n = (a) => (a && a.length) || 0;
  const paths = p.paths || {};
  const net = p.network || {};

  /* Report what is ENFORCED, not what was asked for. If dialect negotiation
   * came back "none" the network block never reaches wxc-exec, and printing
   * "denied" here because policy.json says "deny" would be a lie on the one
   * line most likely to be read aloud in a room. */
  const netDead = S.state && S.state.dialect === "none";
  const outbound = netDead
    ? "not enforced on this host"
    : (net.outbound === "allow" ? "allowed" : "denied");

  return [
    ["Containment", p.containment || "processcontainer"],
    ["Readable", n(paths.read) + " path" + (n(paths.read) === 1 ? "" : "s")],
    ["Writable", n(paths.write) + " path" + (n(paths.write) === 1 ? "" : "s")],
    ["Outbound", outbound],
    ["Local network", netDead ? "not enforced on this host"
                              : (net.localNetwork ? "allowed" : "denied")],
    ["Windows/UI", (p.ui || {}).allowWindows ? "allowed" : "blocked"],
    ["Timeout", Math.round(((p.limits || {}).timeoutMs || 30000) / 1000) + "s"],
  ];
}

/* The active agent's own policy, out of its own file. Not st.policy - that is
 * the host-wide default and no agent uses it. */
function missionPolicy() {
  const a = active();
  return (a && a.policy) || S.state.policy || {};
}

function renderMission() {
  const box = $("missionPolicy");
  box.innerHTML = "";
  const p = missionPolicy();
  for (const [k, v] of policySummary(p)) {
    const row = el("div", "row");
    row.appendChild(el("b", null, k));
    row.appendChild(el("span", null, v));
    box.appendChild(row);
  }
  const off = Object.entries(p.tools || {})
    .filter(([n, on]) => !n.startsWith("_") && !on).map(([n]) => n);
  if (off.length) {
    const row = el("div", "row");
    row.appendChild(el("b", null, "Tools off"));
    row.appendChild(el("span", null, off.join(", ")));
    box.appendChild(row);
  }
  /* This agent's runs, not the machine's. The rail foot counts this
   * conversation; this counts everything the agent has done since CastleKeep
   * started, which is a different claim and is labelled as one. */
  renderMissionRuns((S.state.runs || []).filter((r) => !S.agent || r.agent === S.agent));
}

function renderMissionRuns(runs) {
  const box = $("missionRuns");
  box.innerHTML = "";
  if (!runs.length) {
    box.appendChild(el("p", "muted",
      "Nothing has run in " + label(active()) + "'s sandbox yet."));
    return;
  }
  for (const r of runs.slice(0, 14)) {
    const row = el("div", "r");
    row.appendChild(outcomeChip(r.outcome));
    row.appendChild(el("span", null, r.tool || r.label || "run"));
    const t = el("span", "mono right", r.durationMs != null ? r.durationMs + " ms" : "");
    row.appendChild(t);
    box.appendChild(row);
  }
}

/* ----------------------------------------------------------- live sessions */

/* What is running right now, and deliberately nothing else. "Sandbox
 * activity" below this bar already keeps the list of what has happened, and a
 * second widget answering the same question in a different shape is how a
 * panel stops being read at all. This one answers "is anything happening",
 * which has a different lifetime and a different reader: it is empty most of
 * the time, and the moment it is not is the moment a sandbox is open.
 *
 * Keyed by agent. The host loop takes one turn at a time, so there is one row
 * today, but that is a fact about the loop rather than about this bar, and a
 * map costs nothing while a hardcoded single row would have to be rewritten
 * the day anything fans out. */
const LIVE = new Map();   // agent id -> { phase, since, elNode }
let liveTimer = null;

function liveStart(agent) {
  LIVE.set(agent, { phase: "thinking", since: Date.now(), elNode: null });
  renderLive();
}

/* A new phase restarts the clock on purpose. The useful number while a
 * sandbox is open is how long that sandbox has been open, not how long the
 * whole turn has been going, because the first is the one that tells you
 * whether to wait or whether something is stuck. */
function livePhase(agent, phase) {
  const s = LIVE.get(agent);
  if (!s) return;
  s.phase = phase;
  s.since = Date.now();
  renderLive();
}

function liveStop(agent) {
  LIVE.delete(agent);
  renderLive();
}

function since(ms) {
  const s = (Date.now() - ms) / 1000;
  return (s < 10 ? s.toFixed(1) : Math.round(s)) + "s";
}

function renderLive() {
  const bar = $("liveBar");
  if (!bar) return;
  bar.innerHTML = "";
  const rows = Array.from(LIVE.entries());
  bar.hidden = !rows.length;
  renderRailMissions();

  /* The same truth on the folded strip. A panel that hides a running sandbox
   * to buy back some width has made the wrong trade, so the dot outlives the
   * panel it came from. */
  const dot = $("foldDot");
  if (dot) dot.hidden = !rows.length;

  for (const [name, s] of rows) {
    const p = profile(name);
    const row = el("div", "s");
    row.setAttribute("data-a", name);
    row.appendChild(el("span", "livedot"));
    row.appendChild(sprite(p ? p.critter : "dragon", "", 0));
    /* The agent's own label, never "the agent". The whole point of four of
     * them is that you can be reading one while another is still working. */
    row.appendChild(el("b", null, label(p)));
    row.appendChild(el("span", "what", s.phase));
    s.elNode = el("span", "el", since(s.since));
    row.appendChild(s.elNode);
    bar.appendChild(row);
  }

  /* One timer for the whole bar, and only while there is something to count.
   * It writes into a node it already holds rather than re-rendering, so the
   * sprite does not restart its blink ten times a second. */
  if (rows.length && !liveTimer) {
    liveTimer = setInterval(() => {
      for (const [, s] of LIVE) if (s.elNode) s.elNode.textContent = since(s.since);
    }, 100);
  } else if (!rows.length && liveTimer) {
    clearInterval(liveTimer);
    liveTimer = null;
  }
}

/* ------------------------------------------------------------ folding panes */

/* Whole panel, not per card. What runs out on this screen is width, and the
 * only two things that can use width back are the chat and the policy editor,
 * so folding a card would cost a click and return nothing. */
function foldPane(id, on) {
  const pane = $(id);
  if (!pane) return;
  S.folded[id] = !!on;
  pane.classList.toggle("folded", !!on);
  const btn = pane.querySelector(".paneflip");
  if (btn) btn.setAttribute("aria-expanded", String(!on));
}

document.body.addEventListener("click", (e) => {
  const t = e.target.closest("[data-fold]");
  if (!t) return;
  const id = t.getAttribute("data-fold");
  foldPane(id, !S.folded[id]);
});

const OUTCOME = {
  "ok":               ["ok",    "allowed"],
  "blocked":          ["bad",   "blocked by policy"],
  "refused-to-start": ["warn",  "sandbox refused to start"],
  "host-gate":        ["info",  "stopped on the host"],
  "failed":           ["coral", "failed"],
  "unknown-tool":     ["warn",  "unknown tool"],
};

function outcomeChip(outcome) {
  const [cls, label] = OUTCOME[outcome] || ["plain", outcome || "?"];
  return el("span", "chip " + cls, label);
}

/* ------------------------------------------------------ rail missions widget */

/* Compact inline list in the left rail under "Your Work". One row per agent:
 * a small sprite, the agent name, and a live pulse dot if its sandbox is open.
 * Clicking a row switches to that agent and shows the Agents tab. */
function renderRailMissions() {
  const box = $("railMissions");
  if (!box) return;
  box.innerHTML = "";

  const anyLive = LIVE.size > 0;
  const globalDot = $("rmGlobalDot");
  if (globalDot) globalDot.hidden = !anyLive;

  const list = profiles();
  for (let i = 0; i < list.length; i++) {
    const p = list[i];
    const live = LIVE.get(p.name);
    const row = el("button", "rail-mission-row" + (p.name === S.agent ? " on" : ""));
    row.type = "button";
    row.appendChild(sprite(p.critter, "", -0.9 * i));
    const nameEl = el("span", "rm-name", p.title || p.name);
    row.appendChild(nameEl);
    if (live) {
      row.appendChild(el("span", "livedot rm-dot"));
    } else {
      row.appendChild(el("span", "rm-status", p.task || "Waiting"));
    }
    row.addEventListener("click", () => { switchAgent(p.name); showTab("assistant"); });
    box.appendChild(row);
  }
}

/* -------------------------------------------------------- sandbox panel */

/* Sandbox status for the currently active agent: compact badge + policy grid
 * + activity log. Mirrors the reference image "Sandbox & Policy" card. */
const SANDBOX_ICONS = {
  Containment:     '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4v5c0 5-4 8-8 10C8 20 4 17 4 12V7z"/></svg>',
  Readable:        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>',
  Writable:        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4z"/></svg>',
  Outbound:        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 8 16 12 12 16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>',
  "Local network": '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
  "Windows/UI":    '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>',
  Timeout:         '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  "Tools off":     '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="1" y1="1" x2="23" y2="23"/><path d="M15 5.2A7 7 0 017.1 13M12 19a7 7 0 01-5-11.95"/></svg>',
};

function renderSandboxPanel() {
  const rows = $("sandboxGrid");
  const badge = $("sandboxOnBadge");
  if (!rows) return;

  const p = missionPolicy();
  const probe = (S.state || {}).probe || {};
  const sandboxOn = probe.available;

  if (badge) {
    badge.className = "sandbox-on-badge" + (sandboxOn ? "" : " off");
    badge.innerHTML =
      (sandboxOn
        ? '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.4l7.1 2.8v5.4c0 4.3-2.9 7.6-7.1 9.2-4.2-1.6-7.1-4.9-7.1-9.2V6.2z"/><path d="M9.2 12.1l2 2 3.6-3.8"/></svg> ON'
        : '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.9" y1="4.9" x2="19.1" y2="19.1"/></svg> OFF');
  }

  rows.innerHTML = "";
  const policyRows = policySummary(p);
  const off = Object.entries(p.tools || {})
    .filter(([n, on]) => !n.startsWith("_") && !on).map(([n]) => n);
  if (off.length) policyRows.push(["Tools off", off.join(", ")]);

  const DENIED = ["denied", "blocked", "not enforced on this host"];
  for (const [key, val] of policyRows) {
    const row = el("div", "sb-row");
    row.appendChild(el("span", "sb-key", key));
    const isDenied = DENIED.some((d) => String(val).includes(d));
    row.appendChild(el("span", "sb-val" + (isDenied ? " deny" : ""), String(val)));
    rows.appendChild(row);
  }
}

/* ---------------------------------------------------------- control panel */

function renderControl() {
  const st = S.state;
  const caps = st.capabilities || {};
  const probe = st.probe || {};
  const runs = st.runs || [];
  const refused = st.refusals || [];

  const tiles = $("tiles");
  tiles.innerHTML = "";
  const add = (k, v, n) => {
    const t = el("div", "tile");
    t.appendChild(el("div", "k", k));
    t.appendChild(el("div", "v", v));
    t.appendChild(el("div", "n", n));
    tiles.appendChild(t);
  };
  add("Containment", probe.available ? (probe.tier || "unknown") : "none",
      probe.available ? (caps._tierLabel || "") : (probe.error || "wxc-exec not usable"));
  add("Agents", String(profiles().length),
      "one policy each, discovered in profiles\\");
  add("Sandboxes spawned", String(runs.length), "since CastleKeep started");
  add("Refused", String(refused.length), "host gates, policy blocks, bad configs");
  add("Network dialect", st.dialect || "?",
      st.dialect === "none" ? "neither dialect was accepted" : "negotiated with --dry-run");
  add("Model", (st.lemonade || {}).reachable ? "up" : "down",
      (st.lemonade || {}).baseUrl || "");

  /* refused feed */
  const feed = $("refusedFeed");
  feed.innerHTML = "";
  if (!refused.length) {
    feed.appendChild(el("p", "muted", "Nothing refused yet. Ask " +
      label(active()) + " to read something outside its granted paths."));
  } else {
    for (const r of refused) {
      const item = el("div", "item " + (r.outcome || ""));
      const body = el("div");
      body.appendChild(el("b", null,
        (r.agent ? label(profile(r.agent)) + " · " : "") +
        (r.tool || r.label || "run") + " - " + (OUTCOME[r.outcome] || ["", r.outcome])[1]));
      body.appendChild(el("span", null, r.reason || r.detail || ""));
      if (r.offendingField) body.appendChild(el("div", "muted", "field: " + r.offendingField));
      item.appendChild(body);
      item.appendChild(el("span", "t", "#" + r.seq));
      feed.appendChild(item);
    }
  }

  /* run table */
  const tb = $("runsTable").querySelector("tbody");
  tb.innerHTML = "";
  for (const r of runs) {
    const tr = el("tr");
    tr.appendChild(el("td", null, "#" + r.seq));
    tr.appendChild(el("td", null, r.agent ? label(profile(r.agent)) : "-"));
    tr.appendChild(el("td", null, r.tool || r.label || ""));
    const td = el("td"); td.appendChild(outcomeChip(r.outcome)); tr.appendChild(td);
    tr.appendChild(el("td", null, r.durationMs != null ? r.durationMs + " ms" : ""));
    const c = el("td", "cmd", r.command || "");
    c.title = r.command || "";
    tr.appendChild(c);
    tb.appendChild(tr);
  }
  if (!runs.length) {
    const tr = el("tr");
    const td = el("td", "muted", "No sandbox has been spawned yet.");
    td.colSpan = 6;
    tr.appendChild(td);
    tb.appendChild(tr);
  }

  /* reachable paths, one block per agent. A single list here would have to
   * pick one agent's grants and label them as the machine's, which is the
   * one thing four separate boxes are meant to stop anybody doing. */
  const pc = $("pathsCard");
  pc.innerHTML = "";
  const ctx = st.paths || {};
  const expand = (v) => String(v).replace(/\$\{(\w+)\}/g, (m, k) =>
    ctx[k.toLowerCase()] != null ? ctx[k.toLowerCase()] : m);
  const section = (title, arr) => {
    const row = el("div", "row");
    row.appendChild(el("b", null, title));
    const s = el("span");
    if (!arr || !arr.length) s.appendChild(el("span", "muted", "nothing"));
    else arr.forEach((v) => {
      const c = el("code", null, expand(v));
      c.style.display = "block";
      s.appendChild(c);
    });
    row.appendChild(s);
    pc.appendChild(row);
  };
  for (const p of profiles()) {
    const paths = (p.policy || {}).paths || {};
    pc.appendChild(el("div", "card-title", label(p)));
    section("Read", paths.read);
    section("Write", paths.write);
    if ((paths.deny || []).length) section("Denied", paths.deny);
  }
  if (!profiles().length) {
    const paths = (st.policy || {}).paths || {};
    section("Read", paths.read);
    section("Write", paths.write);
    section("Denied", paths.deny);
  }

  /* capabilities */
  const cc = $("capsCard");
  cc.innerHTML = "";
  const LABEL = {
    readPaths: "Grant read paths",
    writePaths: "Grant write paths",
    denyPaths: "Explicit deny paths",
    outboundToggle: "Block outbound network",
    perHostRules: "Per-host allow/block",
    hostLoopback: "Reach the host's loopback",
    ui: "Lock down windows and clipboard",
    leastPrivilege: "Least-privilege mode",
    captureDenials: "Record what was denied",
    daclMutation: "Change real ACLs (tier 3)",
  };
  for (const [key, text] of Object.entries(LABEL)) {
    const c = caps[key];
    if (!c) continue;
    const row = el("div", "row");
    row.appendChild(el("b", null, text));
    const s = el("span");
    s.appendChild(el("span", "chip " + (c.supported ? "ok" : "bad"),
                     c.supported ? "enforced here" : "not available"));
    if (c.why) s.appendChild(el("div", "muted", c.why));
    row.appendChild(s);
    cc.appendChild(row);
  }
  if (!cc.children.length)
    cc.appendChild(el("p", "muted", "The host has not been probed yet. Settings -> Re-scan."));

  /* tools. The gate shown is the active agent's, and it is the same gate in
   * all four profiles on purpose: a tool switched off here never reaches a
   * sandbox, so leaving them all open is what makes the difference between
   * the agents a containment result rather than an if statement. */
  const gate = (missionPolicy().tools || {});
  const tc = $("toolsCard");
  tc.innerHTML = "";
  for (const t of st.tools || []) {
    const on = t.name in gate ? !!gate[t.name] : !!t.enabled;
    const n = el("div", "t" + (on ? "" : " off"));
    const head = el("div");
    head.appendChild(el("b", null, t.name));
    head.appendChild(el("span", "chip " + (on ? "ok" : "bad") + " right",
                        on ? "on" : "off"));
    head.style.display = "flex";
    head.style.gap = "8px";
    head.style.alignItems = "center";
    n.appendChild(head);
    n.appendChild(el("p", null, t.description));
    if (t.needs && t.needs.length)
      n.appendChild(el("p", null, "needs " + t.needs.join("; ")));
    tc.appendChild(n);
  }
}

/* ====================================================================== */
/* chat                                                                    */
/* ====================================================================== */

/* Each agent keeps its own thread, as a detached element. Switching agents
 * swaps the whole conversation rather than dropping a divider into a shared
 * one: the policy changed, so the transcript above the switch was produced
 * under rules that no longer apply, and running the two together invites
 * reading it as one. It is also what the model is sent - the history that
 * goes with a turn is always that agent's own. */
function thread(name) {
  let t = S.threads[name];
  if (!t) {
    t = S.threads[name] = { el: el("div", "thread"), history: [], calls: 0, refused: 0, lastUserIdx: -1, lastTtftMs: null };
  }
  return t;
}

function emptyState() {
  const p = active();
  const box = el("div", "empty");
  if (!p) {
    const stale = S.state && !("profiles" in S.state);
    box.appendChild(el("h2", null, stale ? "Restart the server." : "No agents."));
    box.appendChild(el("p", null, noAgentsReason()));
    return box;
  }
  box.appendChild(sprite(p.critter, "lg", 0));
  box.appendChild(el("h2", null, label(p)));
  box.appendChild(el("p", null, p.description));
  const st = el("div", "starters");
  for (const s of p.starters || []) {
    const b = el("button", "starter", s);
    b.type = "button";
    b.addEventListener("click", () => send(s));
    st.appendChild(b);
  }
  box.appendChild(st);
  return box;
}

function showThread() {
  const t = thread(S.agent);
  const box = $("transcript");
  box.innerHTML = "";
  box.appendChild(t.el);
  if (!t.el.children.length) t.el.appendChild(emptyState());
  $("statCalls").textContent = String(t.calls);
  $("statRefused").textContent = String(t.refused);
  box.scrollTop = box.scrollHeight;
}

function transcriptClear() {
  const t = thread(S.agent);
  t.el.innerHTML = "";
  t.history = [];
  t.calls = 0;
  t.refused = 0;
  showThread();
}

function msgNode(into, role, p) {
  const wrap = el("div", "msg " + role);
  if (role === "assistant") {
    const avatar = el("div", "who");
    avatar.appendChild(sprite(p ? p.critter : "dragon", "md", 0));
    wrap.appendChild(avatar);
  }
  const body = el("div", "body");
  if (role === "assistant") body.appendChild(el("div", "name", label(p)));
  wrap.appendChild(body);
  into.appendChild(wrap);
  return body;
}

function scrollChat() {
  const t = $("transcript");
  t.scrollTop = t.scrollHeight;
}

/* ====================================================================== */
/* miniMd — minimal markdown → HTML                                        */
/* ====================================================================== */

function miniMd(text) {
  if (!text) return "";

  // Escape HTML entities first — mandatory before any innerHTML assignment.
  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Inline transforms (applied to already-escaped text).
  function inline(s) {
    return s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/_([^_]+)_/g, "<em>$1</em>");
  }

  // Extract fenced code blocks before line processing.
  const codeBlocks = [];
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push("<pre><code" + (lang ? " class=\"language-" + esc(lang) + "\"" : "") +
                    ">" + esc(code.replace(/\n$/, "")) + "</code></pre>");
    return "\x00CODE" + idx + "\x00";
  });

  const lines = text.split("\n");
  const out = [];
  let inUl = false, inOl = false, inTable = false;

  function closeList() {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  }
  function closeTable() {
    if (inTable) { out.push("</tbody></table>"); inTable = false; }
  }

  lines.forEach((line, i) => {
    // Code block placeholder.
    if (/^\x00CODE\d+\x00$/.test(line.trim())) {
      closeList(); closeTable();
      out.push(codeBlocks[parseInt(line.match(/\d+/)[0])]);
      return;
    }
    // Headings.
    const hm = line.match(/^(#{1,3})\s+(.*)/);
    if (hm) {
      closeList(); closeTable();
      const lvl = hm[1].length;
      out.push("<h" + lvl + ">" + inline(esc(hm[2])) + "</h" + lvl + ">");
      return;
    }
    // Unordered list.
    const ulm = line.match(/^[-*]\s+(.*)/);
    if (ulm) {
      closeTable();
      if (!inUl) { if (inOl) { out.push("</ol>"); inOl = false; } out.push("<ul>"); inUl = true; }
      out.push("<li>" + inline(esc(ulm[1])) + "</li>");
      return;
    }
    // Ordered list.
    const olm = line.match(/^\d+\.\s+(.*)/);
    if (olm) {
      closeTable();
      if (!inOl) { if (inUl) { out.push("</ul>"); inUl = false; } out.push("<ol>"); inOl = true; }
      out.push("<li>" + inline(esc(olm[1])) + "</li>");
      return;
    }
    // Table row.
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      closeList();
      const cells = line.trim().slice(1, -1).split("|").map(c => c.trim());
      // Skip separator rows (---|---).
      if (cells.every(c => /^[-: ]+$/.test(c))) return;
      if (!inTable) {
        out.push("<table><thead><tr>" +
                 cells.map(c => "<th>" + inline(esc(c)) + "</th>").join("") +
                 "</tr></thead><tbody>");
        inTable = true;
      } else {
        out.push("<tr>" + cells.map(c => "<td>" + inline(esc(c)) + "</td>").join("") + "</tr>");
      }
      return;
    }
    closeTable();
    // Blank line → paragraph break.
    if (!line.trim()) {
      closeList();
      out.push("<br>");
      return;
    }
    closeList();
    out.push("<p>" + inline(esc(line)) + "</p>");
  });

  closeList();
  closeTable();
  return out.join("");
}

/* ====================================================================== */
/* retryLast — replay last user message with failed turn stripped          */
/* ====================================================================== */

function retryLast(agentName) {
  const t = thread(agentName);
  const idx = t.lastUserIdx;
  if (idx < 0 || !t.history[idx] || t.history[idx].role !== "user") return;
  const msg = t.history[idx].content;
  t.history = t.history.slice(0, idx);
  t.lastUserIdx = -1;
  S.agent = agentName;
  send(msg);
}

/* ====================================================================== */
/* chat                                                                    */
/* ====================================================================== */

async function send(text) {
  if (!text.trim()) return;
  if (S.busy) {
    toast("Still answering. One model, one turn at a time.", true);
    return;
  }

  /* Pinned for the whole turn. Switching agents mid-answer is allowed - the
   * stream keeps writing into this thread's element whether it is on screen
   * or not - so nothing below may read S.agent again. */
  const me = S.agent;
  const p = active();
  const t = thread(me);

  const empty = t.el.querySelector(".empty");
  if (empty) empty.remove();

  const ub = msgNode(t.el, "user");
  ub.appendChild(el("div", "bubble", text));

  const body = msgNode(t.el, "assistant", p);
  let bubble = null, thinkBox = null, thinkText = null;
  const calls = new Map();

  S.busy = true;
  liveStart(me);
  setDragon("thinking");
  $("send").classList.add("hidden");
  $("stop").classList.remove("hidden");
  S.abort = new AbortController();

  const history = t.history.slice();
  let finalText = "";

  // The rail counts the conversation on screen. If the person has walked over
  // to another agent while this one thinks, its numbers must not move.
  const bump = () => {
    if (S.agent !== me) return;
    $("statCalls").textContent = String(t.calls);
    $("statRefused").textContent = String(t.refused);
  };

  const onEvent = (ev) => {
    switch (ev.type) {
      case "thinking": {
        if (!thinkBox) {
          thinkBox = el("details", "think");
          thinkBox.appendChild(el("summary", null, "Thinking"));
          thinkText = el("div");
          thinkBox.appendChild(thinkText);
          body.appendChild(thinkBox);
        }
        thinkText.textContent += ev.text;
        break;
      }
      case "token": {
        if (!bubble) { bubble = el("div", "bubble"); body.appendChild(bubble); }
        bubble.textContent += ev.text;
        break;
      }
      case "tool_call": {
        setDragon("working");
        livePhase(me, ev.name);
        const d = el("details", "toolcall");
        const sum = el("summary");
        sum.appendChild(el("span", "chip info plain", "sandbox"));
        sum.appendChild(el("span", "tname", ev.name));
        sum.appendChild(el("span", "muted right", "starting"));
        d.appendChild(sum);
        const detail = el("div", "detail");
        detail.appendChild(el("div", "card-title", "command"));
        detail.appendChild(el("pre", "out", ev.command || ""));
        detail.appendChild(el("div", "card-title", "config sent to wxc-exec"));
        detail.appendChild(el("pre", "out", JSON.stringify(ev.config, null, 2)));
        for (const n of ev.notes || [])
          detail.appendChild(el("div", "lint", "")).appendChild(
            el("div", "l " + n.level, n.message));
        d.appendChild(detail);
        body.appendChild(d);
        calls.set(ev.name, { node: d, summary: sum, detail });
        t.calls += 1;
        bump();
        break;
      }
      case "sandbox": {
        const r = ev.run || {};
        /* The sandbox is gone by the time this arrives, so the bar goes back
         * to reporting the model rather than leaving a tool name standing
         * next to a clock that is still counting. */
        livePhase(me, "thinking");
        const slot = calls.get(r.tool || r.label);
        if (slot) {
          slot.node.className = "toolcall " + (r.outcome || "");
          slot.summary.innerHTML = "";
          slot.summary.appendChild(outcomeChip(r.outcome));
          slot.summary.appendChild(el("span", "tname", r.tool || r.label || ""));
          slot.summary.appendChild(el("span", "muted right",
            (r.durationMs != null ? r.durationMs + " ms" : "")));
          if (r.reason) {
            const why = el("div", "card-sub");
            why.textContent = r.reason;
            slot.detail.insertBefore(why, slot.detail.firstChild);
          }
          if (r.stdout) {
            slot.detail.appendChild(el("div", "card-title", "stdout"));
            slot.detail.appendChild(el("pre", "out", r.stdout));
          }
          if (r.stderr) {
            slot.detail.appendChild(el("div", "card-title", "stderr"));
            slot.detail.appendChild(el("pre", "out", r.stderr));
          }
        }
        if (r.outcome && r.outcome !== "ok") {
          t.refused += 1;
          bump();
          setDragon("alert");
          if (slot && (r.outcome === "blocked" || r.outcome === "refused-to-start")) {
            slot.node.open = true;
            const btn = el("button", "btn ghost", "Policy changed? Retry →");
            btn.style.marginTop = "10px";
            btn.addEventListener("click", () => retryLast(me));
            slot.detail.appendChild(btn);
          }
        }
        break;
      }
      case "tool_result": {
        bubble = null;               // prose after a tool call starts fresh
        break;
      }
      case "turn_continue": {
        setDragon("thinking");
        break;
      }
      case "notice": {
        body.appendChild(el("div", "notice", ev.message));
        break;
      }
      case "error": {
        body.appendChild(el("div", "errline", ev.message));
        setDragon("alert");
        break;
      }
      case "perf": {
        t.lastTtftMs = ev.ttftMs;
        break;
      }
      case "done": {
        finalText = ev.text || "";
        if (bubble && finalText) bubble.innerHTML = miniMd(finalText);
        break;
      }
    }
    if (S.agent === me) scrollChat();
  };

  try {
    await sse("/api/chat", { message: text, history, agent: me },
              onEvent, S.abort.signal);
  } catch (e) {
    if (e.name !== "AbortError")
      body.appendChild(el("div", "errline", String(e.message || e)));
  }

  t.lastUserIdx = t.history.length;
  t.history.push({ role: "user", content: text });
  if (finalText) t.history.push({ role: "assistant", content: finalText });
  if (t.history.length > 24) t.history = t.history.slice(-24);

  S.busy = false;
  /* Including on abort and on a thrown stream: the bar must never outlive the
   * thing it claims is running. */
  liveStop(me);
  S.abort = null;
  $("send").classList.remove("hidden");
  $("stop").classList.add("hidden");
  setDragon(t.refused ? "alert" : "happy");
  setTimeout(() => { if (!S.busy) setDragon("idle"); }, 2600);

  hydrate().catch(() => {});
}

$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("input").value;
  $("input").value = "";
  $("input").style.height = "auto";
  send(v);
});
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});
$("input").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 180) + "px";
});
$("stop").addEventListener("click", () => { if (S.abort) S.abort.abort(); });
/* Clears this agent's conversation and nothing else. The other three keep
 * theirs, which is the point of them being separate. */
$("clearChat").addEventListener("click", () => transcriptClear());
/* The starter buttons are built per agent, out of its own profile, and wire
 * themselves up in emptyState(). */
$("editThisPolicy").addEventListener("click", () => {
  if (!S.dirty) {
    S.policyAgent = S.agent;
    S.policy = JSON.parse(JSON.stringify(policySource()));
    renderPolicy();
  }
  showTab("policy");
});

/* ====================================================================== */
/* policy editor                                                           */
/* ====================================================================== */

/* Which policy the form is editing. An agent id edits profiles\<id>.json;
 * the empty string edits policy.json, the host-wide default that no agent
 * uses - the Run tab's dry run, the dialect check at startup and verify.py
 * do, and they must not borrow one agent's boundary to make a claim about
 * the machine. */
function policySource() {
  if (known(S.policyAgent)) return profile(S.policyAgent).policy || {};
  return S.state.policy || {};
}

function policyLabel() {
  return known(S.policyAgent) ? label(profile(S.policyAgent)) : "the host default";
}

function renderPolicyWho() {
  const sel = $("policyWho");
  sel.innerHTML = "";
  for (const p of profiles()) {
    const o = el("option", null, label(p));
    o.value = p.name;
    if (p.name === S.policyAgent) o.selected = true;
    sel.appendChild(o);
  }
  const host = el("option", null, "Host default (policy.json)");
  host.value = "";
  if (!S.policyAgent) host.selected = true;
  sel.appendChild(host);

  const p = S.policyAgent && profile(S.policyAgent);
  $("policySub").textContent = p
    ? label(p) + " brings its own policy, in profiles\\" + p.name + ".json. " +
      "Saving reaches that agent's next tool call and no other agent's."
    : "policy.json. No agent uses this one: it is what the Run tab's dry run, " +
      "the dialect check at startup and verify.py compile when the claim is " +
      "about the host rather than about an agent.";
}

$("policyWho").addEventListener("change", () => {
  if (S.dirty) {
    toast("Unsaved changes. Save or revert before switching.", true);
    renderPolicyWho();           // put the picker back where it was
    return;
  }
  S.policyAgent = $("policyWho").value;
  S.policy = JSON.parse(JSON.stringify(policySource()));
  renderPolicy();
});

function capOf(key) {
  const c = (S.state.capabilities || {})[key];
  return c || { supported: true, why: "" };
}

function field(label, help, control, capKey) {
  const f = el("div", "field");
  f.appendChild(el("label", null, label));
  const h = el("div", "help", help);
  const cap = capKey ? capOf(capKey) : null;
  if (cap && !cap.supported) {
    f.classList.add("blocked");
    h.appendChild(el("div", "deny", cap.why || "This host cannot enforce it."));
  }
  f.appendChild(h);
  f.appendChild(control);
  return f;
}

function toggle(getter, setter, disabled) {
  const b = el("button", "toggle" + (getter() ? " on" : ""));
  b.type = "button";
  if (disabled) b.disabled = true;
  b.addEventListener("click", () => {
    setter(!getter());
    b.classList.toggle("on", getter());
    policyChanged();
  });
  return b;
}

function pathEditor(kind, capKey) {
  const wrap = el("div");
  const list = el("div", "pathlist");
  const cap = capOf(capKey);
  const p = S.policy;
  p.paths = p.paths || {};
  p.paths[kind] = p.paths[kind] || [];

  const draw = () => {
    list.innerHTML = "";
    p.paths[kind].forEach((v, i) => {
      const row = el("div", "pathrow");
      const inp = el("input");
      inp.value = v;
      inp.spellcheck = false;
      inp.addEventListener("input", () => { p.paths[kind][i] = inp.value; policyChanged(); });
      row.appendChild(inp);
      const x = el("button", "x", "×");
      x.type = "button";
      x.title = "Remove";
      x.addEventListener("click", () => { p.paths[kind].splice(i, 1); draw(); policyChanged(); });
      row.appendChild(x);
      list.appendChild(row);
    });
    if (!p.paths[kind].length) list.appendChild(el("p", "muted", "No paths."));
  };
  draw();
  wrap.appendChild(list);

  const add = el("button", "btn ghost addpath", "Add a path");
  add.type = "button";
  add.disabled = !cap.supported;
  add.addEventListener("click", () => { p.paths[kind].push(""); draw(); policyChanged(); });
  wrap.appendChild(add);

  if (!cap.supported)
    wrap.appendChild(el("p", "deny", cap.why || "This host will refuse the run if you set this."));
  return wrap;
}

function renderPolicy() {
  const form = $("policyForm");
  const p = S.policy;
  form.innerHTML = "";
  renderPolicyWho();

  /* paths */
  let g = el("div", "group");
  g.appendChild(el("h3", null, "What the sandbox can see"));
  g.appendChild(el("p", "gsub",
    "Everything else is invisible. Use ${project}, ${workspace}, ${home}, " +
    "${windir}, ${system32}, ${temp}, ${programfiles}, ${localappdata}, " +
    "${systemdrive} rather than typing absolute paths."));
  g.appendChild(el("div", "card-title", "Readable"));
  g.appendChild(pathEditor("read", "readPaths"));
  g.appendChild(el("div", "card-title", "Writable"));
  g.appendChild(pathEditor("write", "writePaths"));
  g.appendChild(el("div", "card-title", "Explicitly denied"));
  g.appendChild(el("p", "gsub",
    "Only meaningful where the host supports deny rules. Under the AppContainer " +
    "tiers paths are denied by default, and wxc-exec refuses a config that sets " +
    "this - it does not drop the field."));
  g.appendChild(pathEditor("deny", "denyPaths"));
  form.appendChild(g);

  /* network */
  g = el("div", "group");
  g.appendChild(el("h3", null, "Network"));
  g.appendChild(el("p", "gsub",
    "Dialect negotiated on this host: " + (S.state.dialect || "?") + "."));
  p.network = p.network || {};
  g.appendChild(field("Outbound internet",
    "Let the sandbox reach the network. Off means fetch_url fails inside the container.",
    toggle(() => (p.network.outbound === "allow"),
           (v) => (p.network.outbound = v ? "allow" : "deny"),
           !capOf("outboundToggle").supported),
    "outboundToggle"));
  g.appendChild(field("Local network",
    "Machines on your LAN, and the host's own loopback.",
    toggle(() => !!p.network.localNetwork,
           (v) => (p.network.localNetwork = v),
           !capOf("hostLoopback").supported),
    "hostLoopback"));
  form.appendChild(g);

  /* ui */
  g = el("div", "group");
  g.appendChild(el("h3", null, "Desktop"));
  g.appendChild(el("p", "gsub",
    "Whether contained code can draw on your screen or touch your clipboard."));
  p.ui = p.ui || {};
  g.appendChild(field("Allow windows",
    "Let the contained process create visible windows.",
    toggle(() => !!p.ui.allowWindows, (v) => (p.ui.allowWindows = v),
           !capOf("ui").supported), "ui"));
  const clip = el("select");
  ["none", "read", "write", "readwrite"].forEach((v) => {
    const o = el("option", null, v);
    o.value = v;
    if ((p.ui.clipboard || "none") === v) o.selected = true;
    clip.appendChild(o);
  });
  clip.disabled = !capOf("ui").supported;
  clip.addEventListener("change", () => { p.ui.clipboard = clip.value; policyChanged(); });
  g.appendChild(field("Clipboard", "Clipboard access for contained code.", clip, "ui"));
  g.appendChild(field("Input injection",
    "Let it synthesise keystrokes and mouse events. Leave this off.",
    toggle(() => !!p.ui.allowInputInjection,
           (v) => (p.ui.allowInputInjection = v),
           !capOf("ui").supported), "ui"));
  form.appendChild(g);

  /* limits */
  g = el("div", "group");
  g.appendChild(el("h3", null, "Limits"));
  p.limits = p.limits || {};
  const to = el("input");
  to.type = "number";
  to.min = "1000";
  to.step = "1000";
  to.value = p.limits.timeoutMs || 30000;
  to.addEventListener("input", () => {
    p.limits.timeoutMs = parseInt(to.value, 10) || 30000;
    policyChanged();
  });
  g.appendChild(field("Timeout (ms)",
    "How long the contained process may run before MXC kills it.", to));
  form.appendChild(g);

  /* advanced */
  g = el("div", "group");
  g.appendChild(el("h3", null, "Advanced"));
  g.appendChild(el("p", "gsub",
    "These change how the container is built, not what it can reach."));
  p.advanced = p.advanced || {};
  const adv = [
    ["leastPrivilege", "Least privilege", "Strip every capability not explicitly granted.", "leastPrivilege"],
    ["learningMode", "Learning mode", "Report what would have been denied instead of changing enforcement.", null],
    ["captureDenials", "Record denials", "Write a receipt for every denial into receipts/. Needs host support.", "captureDenials"],
    ["allowDaclMutation", "Allow ACL changes", "Tier 3 grants read access by editing real ACEs on disk. Off means tier 3 cannot grant paths at all.", "daclMutation"],
    ["sendUnsupportedAnyway", "Send unsupported fields anyway", "Do not silently drop a field this host cannot enforce - send it and let wxc-exec refuse the run, loudly.", null],
  ];
  for (const [key, label, help, capKey] of adv) {
    g.appendChild(field(label, help,
      toggle(() => !!p.advanced[key], (v) => (p.advanced[key] = v),
             capKey ? !capOf(capKey).supported : false),
      capKey));
  }
  form.appendChild(g);

  /* tools */
  g = el("div", "group");
  g.appendChild(el("h3", null, "Tools"));
  g.appendChild(el("p", "gsub",
    "A gate on the host. Switching a tool off here means the request never " +
    "reaches a sandbox at all - different from being blocked inside one, and " +
    "the Control Panel labels them differently. It is the same gate in all " +
    "four profiles on purpose: leaving them open is what makes the difference " +
    "between the agents a containment result rather than an if statement."));
  p.tools = p.tools || {};
  for (const t of S.state.tools || []) {
    if (!(t.name in p.tools)) p.tools[t.name] = t.enabled;
    g.appendChild(field(t.name,
      t.description + (t.danger ? " Off by default." : ""),
      toggle(() => !!p.tools[t.name], (v) => (p.tools[t.name] = v), false)));
  }
  form.appendChild(g);

  renderLint(S.state.lint || []);
  refreshPreview();
}

function policyChanged() {
  S.dirty = true;
  $("savePolicy").textContent = "Save •";
  clearTimeout(policyChanged._t);
  policyChanged._t = setTimeout(refreshPreview, 350);
}

function renderLint(lint) {
  const box = $("lintBox");
  box.innerHTML = "";
  if (!lint || !lint.length) return;
  const wrap = el("div", "lint");
  for (const n of lint) {
    const l = el("div", "l " + n.level);
    l.appendChild(el("b", null, n.field));
    l.appendChild(el("span", null, n.message));
    wrap.appendChild(l);
  }
  box.appendChild(wrap);
}

async function refreshPreview() {
  const { body } = await postJSON("/api/policy/preview", { policy: S.policy });
  if (body.error) {
    $("policyJson").textContent = body.error;
    return;
  }
  $("policyJson").textContent = JSON.stringify(body.config, null, 2);
  const lint = (body.lint || []).concat(
    (body.notes || []).map((n) => ({ level: n.level, field: n.field || "compiler", message: n.message })));
  renderLint(lint);
}

$("savePolicy").addEventListener("click", async () => {
  // The server takes either shape. With an agent named it writes that
  // agent's profile; without one it writes policy.json.
  const payload = S.policyAgent
    ? { agent: S.policyAgent, policy: S.policy } : S.policy;
  const { ok, body } = await postJSON("/api/policy", payload);
  if (!ok) {
    renderLint(body.lint || []);
    toast("Not saved - fix the errors first.", true);
    return;
  }
  S.dirty = false;
  $("savePolicy").textContent = "Save";
  toast("Saved. " + policyLabel() + "'s next tool call will use it.");
  await hydrate();
});

$("revertPolicy").addEventListener("click", async () => {
  S.dirty = false;
  $("savePolicy").textContent = "Save";
  await hydrate();
  toast("Reverted to what is on disk.");
});

$("dryRun").addEventListener("click", async () => {
  if (S.dirty) {
    toast("Save first - dry-run reads the file from disk.", true);
    return;
  }
  term("\n$ wxc-exec --dry-run   (" + policyLabel() +
       ", parse and validate, nothing spawned)\n", "d");
  const { body } = await postJSON("/api/policy/dryrun", { agent: S.policyAgent || null });
  const r = body.run || {};
  if (r.outcome === "ok") {
    toast("wxc-exec accepted this policy.");
    term("  accepted\n", "g");
  } else {
    toast("wxc-exec refused: " + (r.reason || r.outcome), true);
    term("  " + (r.reason || r.outcome) + "\n", "c");
    if (r.offendingField) term("  field: " + r.offendingField + "\n", "y");
  }
  if (r.stderr) term(r.stderr + "\n", "d");
  showTab("run");
  await hydrate();
});

/* ====================================================================== */
/* run tab                                                                 */
/* ====================================================================== */

function term(text, cls) {
  const t = $("term");
  const n = el("span", cls || null, text);
  t.appendChild(n);
  t.scrollTop = t.scrollHeight;
}
$("clearTerm").addEventListener("click", () => ($("term").innerHTML = ""));

function renderRunTab() {
  const st = S.state;

  /* whose sandbox the hand-run goes into. Defaults to whoever is on screen in
   * the Agents tab, so "run read_file by hand" answers the question you were
   * just asking rather than a different agent's version of it. */
  const whoSel = $("toolWho");
  const keep = whoSel.value;
  whoSel.innerHTML = "";
  for (const p of profiles()) {
    const o = el("option", null, "as " + label(p));
    o.value = p.name;
    whoSel.appendChild(o);
  }
  if (!profiles().length) {
    const o = el("option", null, "host default");
    o.value = "";
    whoSel.appendChild(o);
  }
  whoSel.value = known(keep) ? keep : (S.agent || "");

  /* tool runner */
  const pick = $("toolPick");
  const prev = pick.value;
  pick.innerHTML = "";
  for (const t of st.tools || []) {
    const o = el("option", null, t.name + (t.enabled ? "" : "  (off in policy)"));
    o.value = t.name;
    pick.appendChild(o);
  }
  if (prev) pick.value = prev;
  drawToolArgs();
  renderSetupSteps();
}

/* Step four names a file, and which file it is depends on which agent is on
 * screen. Kept out of renderRunTab so switching agent can refresh the step
 * without rebuilding the tool runner above it, which would throw away an
 * argument somebody was half-way through typing. */
function renderSetupSteps() {
  const st = S.state;
  const ol = $("setupSteps");
  ol.innerHTML = "";
  const steps = [
    ["Start the model.",
     "lemonade-server serve",
     "CastleKeep expects it at " + ((st.lemonade || {}).baseUrl || "") +
     ". One model serves all " + (profiles().length || "four") +
     " agents. Load " + ((st.lemonade || {}).model || "the model") +
     " before you ask any of them anything."],
    ["Check what this machine can actually enforce.",
     "python verify.py",
     "Writes VERIFY-REPORT.md. Until the negative tests pass, do not describe this setup as contained."],
    ["Start CastleKeep.",
     "python run.py",
     "Serves on 127.0.0.1 and opens a browser. No packages to install."],
    ["Change what one agent may reach, while it runs.",
     "notepad profiles\\" + (S.agent || "diagnostics") + ".json",
     "Each agent brings its own policy out of profiles\\, and policy.json is " +
     "the host-wide default that none of them use. Or use the Policy tab. " +
     "Either way the change lands on that agent's next tool call - the policy " +
     "of a running sandbox is immutable, so it can never land on one already " +
     "in flight."],
  ];
  for (const [title, cmd, note] of steps) {
    const li = el("li");
    li.appendChild(el("span", null, title));
    li.appendChild(el("code", null, cmd));
    li.appendChild(el("div", "muted", note));
    ol.appendChild(li);
  }
}

function drawToolArgs() {
  const box = $("toolArgs");
  box.innerHTML = "";
  const t = (S.state.tools || []).find((x) => x.name === $("toolPick").value);
  if (!t) return;
  for (const [name, spec] of Object.entries(t.parameters || {})) {
    box.appendChild(el("label", null, name + " - " + (spec.description || "")));
    const multiline = name === "content";
    const inp = el(multiline ? "textarea" : "input");
    if (multiline) inp.rows = 4;
    inp.dataset.arg = name;
    inp.dataset.kind = spec.type || "string";
    box.appendChild(inp);
  }
  if (!Object.keys(t.parameters || {}).length)
    box.appendChild(el("p", "muted", "This tool takes no arguments."));
}
$("toolPick").addEventListener("change", drawToolArgs);

$("toolGo").addEventListener("click", async () => {
  const name = $("toolPick").value;
  const args = {};
  $("toolArgs").querySelectorAll("[data-arg]").forEach((i) => {
    if (!i.value) return;
    args[i.dataset.arg] = i.dataset.kind === "integer"
      ? parseInt(i.value, 10) : i.value;
  });

  const as = $("toolWho").value;
  term("\n$ " + name + " " + JSON.stringify(args) +
       (as ? "   as " + label(profile(as)) : "") + "\n", "b");
  $("toolGo").disabled = true;
  try {
    await sse("/api/tool", { name, arguments: args, agent: as || null }, (ev) => {
      if (ev.type === "tool_call") {
        term("  command  " + ev.command + "\n", "d");
        for (const n of ev.notes || []) term("  " + n.level + "  " + n.message + "\n", "y");
      } else if (ev.type === "sandbox") {
        const r = ev.run || {};
        const cls = r.outcome === "ok" ? "g" : (r.outcome === "blocked" ? "c" : "y");
        term("  " + (r.outcome || "") + (r.durationMs != null ? "  " + r.durationMs + " ms" : "") + "\n", cls);
        if (r.reason) term("  " + r.reason + "\n", cls);
        if (r.stdout) term(r.stdout.replace(/\s*$/, "") + "\n");
        if (r.stderr) term(r.stderr.replace(/\s*$/, "") + "\n", "d");
      } else if (ev.type === "error") {
        term("  " + ev.message + "\n", "c");
      }
    });
  } catch (e) {
    term("  " + (e.message || e) + "\n", "c");
  }
  $("toolGo").disabled = false;
  await hydrate();
});

const VERIFY_HEADING = {
  inspect: "What the host says about itself",
  validate: "What the binary will accept  (--dry-run, nothing spawned)",
  live: "What actually happened when a sandbox ran",
};

$("runVerify").addEventListener("click", async () => {
  const box = $("verifySteps");
  box.innerHTML = "";
  $("runVerify").disabled = true;
  setDragon("working");
  let kind = null;
  term("\n$ python verify.py\n", "b");

  try {
    await sse("/api/verify", {}, (ev) => {
      if (ev.type === "begin") {
        term("  executor  " + (ev.exe || "not found") + "\n", "d");
        return;
      }
      if (ev.type === "step") {
        if (ev.kind !== kind) {
          kind = ev.kind;
          box.appendChild(el("div", "hdr", VERIFY_HEADING[kind] || kind));
        }
        const s = el("div", "s " + ev.status);
        s.appendChild(el("div", "mark", ev.status.toUpperCase()));
        const b = el("div");
        b.appendChild(el("div", null, ev.title));
        if (ev.detail) b.appendChild(el("div", "d", ev.detail));
        s.appendChild(b);
        box.appendChild(s);
        const cls = { pass: "g", fail: "c", warn: "y", skip: "d" }[ev.status] || "";
        term("  " + ev.status.toUpperCase().padEnd(5) + "  " + ev.title + "\n", cls);
        if (ev.detail && ev.status !== "pass") term("         " + ev.detail + "\n", "d");
        return;
      }
      if (ev.type === "report") {
        const c = ev.counts || {};
        term("\n  " + (c.pass || 0) + " passed, " + (c.warn || 0) + " warnings, " +
             (c.fail || 0) + " failed, " + (c.skip || 0) + " skipped\n",
             (c.fail ? "c" : "g"));
        term("  tier      " + (ev.tier || "unknown") + "\n", "d");
        term("  dialect   " + (ev.dialect || "") + "\n", "d");
        if (ev.savedMarkdown) term("  report    " + ev.savedMarkdown + "\n", "d");
        toast(c.fail ? (c.fail + " checks failed - see the report.")
                     : "Everything this host claims, it proved.", !!c.fail);
        setDragon(c.fail ? "alert" : "happy");
      }
      if (ev.type === "error") term("  " + ev.message + "\n", "c");
    });
  } catch (e) {
    term("  " + (e.message || e) + "\n", "c");
  }
  $("runVerify").disabled = false;
  await hydrate();
});

/* ====================================================================== */
/* settings                                                                */
/* ====================================================================== */

function mini(target, rows) {
  const box = $(target);
  box.innerHTML = "";
  for (const [k, v] of rows) {
    const row = el("div", "row");
    row.appendChild(el("b", null, k));
    const s = el("span");
    if (v instanceof Node) s.appendChild(v); else s.textContent = v == null ? "-" : String(v);
    row.appendChild(s);
    box.appendChild(row);
  }
}

function warmLabel(w) {
  if (w.state === "ready")   return "yes, loaded in " + ((w.ms || 0) / 1000).toFixed(1) + "s";
  if (w.state === "warming") return "loading now";
  if (w.state === "failed")  return "failed - " + (w.error || "");
  if (w.state === "no-model")    return "no, Lemonade is not serving it";
  if (w.state === "unreachable") return "no, Lemonade is not reachable";
  return "not started";
}

function renderSettings() {
  const st = S.state;
  const lem = st.lemonade || {};
  mini("modelCard", [
    ["Base URL", lem.baseUrl],
    ["Route prefix", lem.routePrefix || "-"],
    ["Reachable", lem.reachable ? "yes" : "no"],
    ["Model", lem.model],
    ["Served by Lemonade", lem.modelPresent ? "yes" : "NO - nothing will work"],
    ["Weights resident", warmLabel(st.warmup || {})],
    ["Server has", (lem.models || []).length + " models" +
                   ((lem.suggestions || []).length
                    ? "  (closest: " + lem.suggestions.join(", ") + ")" : "")],
    (function() {
      const ms = (thread(S.agent) || {}).lastTtftMs;
      return ["Last TTFT", ms != null
        ? ms + " ms" + (ms > 5000 ? "  — try a smaller model" : "")
        : "-"];
    })(),
  ]);

  const probe = st.probe || {};
  mini("exeCard", [
    ["wxc-exec", st.mxcExe || st.mxcError || "not found"],
    ["Probe", probe.available ? "ok" : (probe.error || "failed")],
    ["Tier", (st.capabilities || {})._tierLabel || probe.tier || "unknown"],
    ["Network dialect", st.dialect],
    ["Project", st.projectDir],
    ["Workspace", st.workspace],
  ]);

  const notes = $("notesCard");
  notes.innerHTML = "";
  for (const n of st.notes || []) {
    const i = el("div", "item " + (n.level === "error" ? "error" : n.level));
    i.appendChild(el("span", null, n.message));
    notes.appendChild(i);
  }
  if (!(st.notes || []).length) notes.appendChild(el("p", "muted", "Nothing to report."));

  const about = $("aboutCard");
  about.innerHTML = "";
  [
    "The chat loop and the model run on this machine, outside any sandbox. " +
    "Every tool call spawns a fresh one-shot container through wxc-exec and " +
    "throws it away when the command exits.",
    "That split is not a shortcut. MXC has no long-running-daemon shape on " +
    "Windows ProcessContainer - the contained process has to exit inside its " +
    "timeout - so a supervisor outside, re-entering a one-shot per tool call, " +
    "is the only honest arrangement. CastleKeep contains what the agent does, " +
    "not what the agent is.",
    "Each agent brings its own policy, out of its own file in profiles\\. One " +
    "model, one loop and the same nine tools serve all of them; the only thing " +
    "that differs between the agents is the box their tool calls run inside. " +
    "policy.json is still here as the host-wide default, used by the Run tab's " +
    "dry run, the dialect check at startup and verify.py - the machinery that " +
    "is not any one agent's.",
    "Policy is immutable once a container is provisioned. CastleKeep compiles " +
    "a fresh config from that agent's file for every call, which is exactly " +
    "why an edit lands on the next one and never on the one already running.",
    "Nothing on screen claims a tier or a capability that the host did not " +
    "report. If a knob says it cannot be enforced here, that text came from " +
    "wxc-exec's own validation.",
  ].forEach((t) => about.appendChild(el("p", null, t)));
}

$("rescan").addEventListener("click", async () => {
  $("rescan").disabled = true;
  await postJSON("/api/rescan", {});
  await hydrate();
  $("rescan").disabled = false;
  toast("Re-probed the host.");
});

/* ====================================================================== */
/* boot                                                                    */
/* ====================================================================== */

setDragon("idle");
showTab((location.hash || "#assistant").slice(1) || "assistant");
hydrate().catch((e) => {
  toast("Could not reach the CastleKeep server: " + e.message, true);
});
