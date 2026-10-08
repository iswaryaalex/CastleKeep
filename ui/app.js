/*
 * CastleKeep UI.
 *
 * One rule runs through this file: nothing here decides anything. Every tier,
 * every capability, every refusal on screen came from the host - from
 * `wxc-exec --probe`, from a --dry-run, or from a sandbox that really ran and
 * really failed. If the server did not say it, this file does not draw it.
 */

import { dragonSvg } from "/dragon.js";

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
  policy: null,      // working copy, may be dirty
  dirty: false,
  agent: null,       // active subagent id; null until the first hydrate
  histories: {},     // per-subagent chat history - switching agents must not
                     // carry one agent's conversation into another's context
  busy: false,
  abort: null,
  turnCalls: 0,
  turnRefused: 0,
  warmPoll: null,    // interval id while the model's weights load
  mail: null,
};

const agentRec = () =>
  ((S.state && S.state.agents) || []).find((a) => a.id === S.agent) || null;

const history = () => (S.histories[S.agent] = S.histories[S.agent] || []);

/* ====================================================================== */
/* dragon                                                                  */
/* ====================================================================== */

function setDragon(state) {
  const html = dragonSvg(state);
  ["brandDragon", "chatDragon", "emptyDragon"].forEach((id) => {
    const n = $(id);
    if (n) n.innerHTML = html;
  });
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
  const q = S.agent ? "?agent=" + encodeURIComponent(S.agent) : "";
  const st = await getJSON("/api/state" + q);
  S.state = st;
  S.agent = st.activeAgent || null;
  if (!S.dirty) S.policy = JSON.parse(JSON.stringify(st.policy));
  renderAgentNav();
  renderChrome();
  renderMission();
  renderControl();
  renderPolicy();
  renderRunTab();
  renderSettings();
  if ((agentRec() || {}).sidePane === "mailbox") loadMailbox();
}

/* ------------------------------------------------------------- agents */

/* Switching agent is not a view change. It swaps the system prompt, the tool
 * set and the policy file all at once, which is the whole reason the rail
 * lists them separately: you can watch the Policy tab change under you. */
async function switchAgent(id) {
  if (id === S.agent || S.busy) return;
  if (S.dirty && !confirm(
      "You have unsaved policy changes for this agent. Switch anyway and lose them?"))
    return;
  S.agent = id;
  S.dirty = false;
  S.turnCalls = 0;
  S.turnRefused = 0;
  $("statCalls").textContent = "0";
  $("statRefused").textContent = "0";
  await hydrate();
  renderTranscript();
}

function renderAgentNav() {
  const nav = $("agentNav");
  const agents = (S.state.agents || []).filter((a) => a.enabled);
  nav.innerHTML = "";
  // With one agent there is nothing to switch between, and a rail group
  // containing a single permanently-selected button is just noise.
  nav.parentElement.querySelectorAll(".rail-label")[1].classList
    .toggle("hidden", agents.length < 2);
  if (agents.length < 2) return;
  for (const a of agents) {
    const b = el("button", "nav agent" + (a.id === S.agent ? " on" : ""));
    b.appendChild(el("i", null, ""));
    b.lastChild.dataset.ic = a.id === "triage" ? "mail" : "panel";
    b.appendChild(document.createTextNode(a.label));
    b.title = a.blurb;
    b.addEventListener("click", () => switchAgent(a.id));
    nav.appendChild(b);
  }
}

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

  $("hostChip").textContent = st.projectDir || "";
  $("hostChip").title = st.projectDir || "";

  /* The agent's own name, everywhere it is spoken to. A participant named it
   * in setup; showing them "Assistant" afterwards wastes the one moment the
   * app felt like theirs. */
  const prof = st.profile || {};
  const rec = agentRec();
  const name = prof.agentName || "Assistant";
  document.querySelector(".brand-name").textContent = name;
  document.querySelector(".brand-sub").textContent =
    rec ? rec.label.toLowerCase() : "local assistant";
  document.title = name + " - CastleKeep";

  $("chatTitle").textContent = rec && rec.id !== "computer-assist"
    ? name + " · " + rec.label : name;
  $("chatSub").textContent = rec
    ? rec.blurb + " Runs on this machine; nothing you type leaves it."
    : "Runs on this machine. Nothing you type leaves it.";
  $("input").placeholder = "Ask " + name + " something…";

  /* The empty state belongs to renderEmptyState, which owns those nodes and
   * rebuilds them for whichever agent is selected. Writing to them from here
   * would reach for elements a transcript redraw has already replaced, and
   * hydrate() runs after every save, every tool run and every agent switch. */
  if ($("transcript").querySelector(".empty")) renderEmptyState();
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

function renderMission() {
  const rec = agentRec() || {};
  const mail = rec.sidePane === "mailbox";
  $("sideTitle").textContent = mail ? "Mailbox" : "Mission";
  $("mailboxView").classList.toggle("hidden", !mail);
  $("missionView").classList.toggle("hidden", mail);

  const box = $("missionPolicy");
  box.innerHTML = "";
  const p = S.state.policy || {};
  for (const [k, v] of policySummary(p)) {
    const row = el("div", "row");
    row.appendChild(el("b", null, k));
    row.appendChild(el("span", null, v));
    box.appendChild(row);
  }
  const off = Object.entries(p.tools || {}).filter(([, on]) => !on).map(([n]) => n);
  if (off.length) {
    const row = el("div", "row");
    row.appendChild(el("b", null, "Tools off"));
    row.appendChild(el("span", null, off.join(", ")));
    box.appendChild(row);
  }
  renderMissionRuns(S.state.runs || []);
}

function renderMissionRuns(runs) {
  const box = $("missionRuns");
  box.innerHTML = "";
  if (!runs.length) {
    box.appendChild(el("p", "muted", "Nothing has run yet."));
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

/* ------------------------------------------------------------- mailbox */

/* Drawn from a HOST-side read, not from the sandbox. That is deliberate and
 * worth saying out loud in the room: this pane is a window onto the files, and
 * the agent's view of the same files is whatever its policy allows. When the
 * agent is refused a message that is sitting right there on screen, the gap
 * between the two panes IS the demo. */
async function loadMailbox() {
  try {
    S.mail = await getJSON("/api/mailbox");
  } catch (e) {
    return;
  }
  const m = S.mail;
  $("mailboxNote").textContent =
    m.inbox.length + " in the inbox, " + m.archive.length + " archived" +
    (m.filed ? ", " + m.filed + " filed (tombstoned - this tier cannot delete)" : "") +
    (m.privateCount ? ", " + m.privateCount + " in the private folder" : "") + ".";

  drawMail($("mailList"), m.inbox, "The inbox is empty.");
  drawMail($("draftList"), m.drafts,
           "No drafts yet. Ask for a reply and one appears here.");

  const cal = $("calList");
  cal.innerHTML = "";
  if (!m.calendar.length) cal.appendChild(el("p", "muted", "No days held."));
  for (const d of m.calendar) {
    const day = el("div", "mailrow");
    const b = el("div", "mailbody");
    b.appendChild(el("div", "msub", d.date));
    for (const ev of d.events || [])
      b.appendChild(el("div", "mfrom", ev.start + "-" + ev.end + "  " + ev.title));
    day.appendChild(b);
    cal.appendChild(day);
  }
}

function drawMail(box, items, emptyText) {
  box.innerHTML = "";
  if (!items.length) {
    box.appendChild(el("p", "muted", emptyText));
    return;
  }
  for (const msg of items) {
    const row = el("div", "mailrow" + (msg.unread ? " unread" : ""));
    const b = el("div", "mailbody");
    b.appendChild(el("div", "mfrom", (msg.from || "").replace(/\s*<.*>$/, "")));
    b.appendChild(el("div", "msub", msg.subject || "(no subject)"));
    b.appendChild(el("div", "msnip", msg.snippet || msg.status || ""));
    row.appendChild(b);
    row.appendChild(el("span", "mdate", (msg.date || "").slice(5, 10)));
    row.title = msg.id;
    box.appendChild(row);
  }
}

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
    feed.appendChild(el("p", "muted", "Nothing refused yet. Ask Assistant to read something outside the granted paths."));
  } else {
    for (const r of refused) {
      const item = el("div", "item " + (r.outcome || ""));
      const body = el("div");
      body.appendChild(el("b", null, (r.tool || r.label || "run") + " - " + (OUTCOME[r.outcome] || ["", r.outcome])[1]));
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
    td.colSpan = 5;
    tr.appendChild(td);
    tb.appendChild(tr);
  }

  /* reachable paths */
  const pc = $("pathsCard");
  pc.innerHTML = "";
  const ctx = st.paths || {};
  const pol = st.policy || {};
  const expand = (v) => String(v).replace(/\$\{(\w+)\}/g, (m, k) =>
    ctx[k.toLowerCase()] != null ? ctx[k.toLowerCase()] : m);
  const section = (label, arr) => {
    const row = el("div", "row");
    row.appendChild(el("b", null, label));
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
  section("Read", (pol.paths || {}).read);
  section("Write", (pol.paths || {}).write);
  section("Denied", (pol.paths || {}).deny);

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
  for (const [key, label] of Object.entries(LABEL)) {
    const c = caps[key];
    if (!c) continue;
    const row = el("div", "row");
    row.appendChild(el("b", null, label));
    const s = el("span");
    s.appendChild(el("span", "chip " + (c.supported ? "ok" : "bad"),
                     c.supported ? "enforced here" : "not available"));
    if (c.why) s.appendChild(el("div", "muted", c.why));
    row.appendChild(s);
    cc.appendChild(row);
  }
  if (!cc.children.length)
    cc.appendChild(el("p", "muted", "The host has not been probed yet. Settings -> Re-scan."));

  /* tools */
  const tc = $("toolsCard");
  tc.innerHTML = "";
  for (const t of st.tools || []) {
    const n = el("div", "t" + (t.enabled ? "" : " off"));
    const head = el("div");
    head.appendChild(el("b", null, t.name));
    head.appendChild(el("span", "chip " + (t.enabled ? "ok" : "bad") + " right",
                        t.enabled ? "on" : "off"));
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

function transcriptClear() {
  $("transcript").innerHTML = "";
  S.histories[S.agent] = [];
  S.turnCalls = 0;
  S.turnRefused = 0;
  $("statCalls").textContent = "0";
  $("statRefused").textContent = "0";
  renderTranscript();
}

/* Redraw the conversation for whichever agent is now selected. Switching back
 * and forth should find each conversation where you left it - the tool-call
 * detail is not replayed, only the prose, because those sandboxes are long
 * gone and re-rendering them would imply they were still live. */
function renderTranscript() {
  const t = $("transcript");
  t.innerHTML = "";
  const h = history();
  if (!h.length) {
    renderEmptyState();
    return;
  }
  for (const m of h) {
    const body = msgNode(m.role);
    body.appendChild(el("div", "bubble", m.content));
  }
  scrollChat();
}

function renderEmptyState() {
  const rec = agentRec() || {};
  const old = $("transcript").querySelector(".empty");
  if (old) old.remove();
  const wrap = el("div", "empty");
  const av = el("span", "avatar lg");
  av.innerHTML = dragonSvg("idle");
  wrap.appendChild(av);
  wrap.appendChild(el("h2", null, rec.id === "triage"
    ? "What is in your inbox?" : "Ask about this device."));
  wrap.appendChild(el("p", null,
    "Every tool call runs in a throwaway container built from " +
    ((S.state || {}).policyFile || "policy.json") + " as it is at that instant."));
  const box = el("div", "starters");
  for (const s of rec.examples || []) {
    const b = el("button", "starter", s);
    b.type = "button";
    b.addEventListener("click", () => send(s));
    box.appendChild(b);
  }
  wrap.appendChild(box);
  $("transcript").appendChild(wrap);
}

function msgNode(role) {
  const wrap = el("div", "msg " + role);
  if (role === "assistant") {
    const who = el("div", "who");
    const av = el("span", "avatar sm");
    av.innerHTML = dragonSvg("idle");
    who.appendChild(av);
    wrap.appendChild(who);
  }
  const body = el("div", "body");
  if (role === "assistant") body.appendChild(el("div", "name", "Assistant"));
  wrap.appendChild(body);
  $("transcript").appendChild(wrap);
  return body;
}

function scrollChat() {
  const t = $("transcript");
  t.scrollTop = t.scrollHeight;
}

async function send(text) {
  if (!text.trim() || S.busy) return;
  const empty = $("transcript").querySelector(".empty");
  if (empty) empty.remove();

  const ub = msgNode("user");
  ub.appendChild(el("div", "bubble", text));

  const body = msgNode("assistant");
  let bubble = null, thinkBox = null, thinkText = null;
  const calls = new Map();

  S.busy = true;
  setDragon("thinking");
  $("send").classList.add("hidden");
  $("stop").classList.remove("hidden");
  S.abort = new AbortController();

  const sentAgent = S.agent;
  const priorHistory = history().slice();
  let finalText = "";

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
        S.turnCalls += 1;
        $("statCalls").textContent = String(S.turnCalls);
        break;
      }
      case "sandbox": {
        const r = ev.run || {};
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
          S.turnRefused += 1;
          $("statRefused").textContent = String(S.turnRefused);
          setDragon("alert");
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
      case "done": {
        finalText = ev.text || "";
        break;
      }
    }
    scrollChat();
  };

  try {
    await sse("/api/chat",
              { message: text, history: priorHistory, agent: sentAgent },
              onEvent, S.abort.signal);
  } catch (e) {
    if (e.name !== "AbortError")
      body.appendChild(el("div", "errline", String(e.message || e)));
  }

  // Record against the agent the turn was SENT to, not whatever is selected
  // now - otherwise an agent switch mid-answer files the reply under the
  // wrong conversation.
  const h = (S.histories[sentAgent] = S.histories[sentAgent] || []);
  h.push({ role: "user", content: text });
  if (finalText) h.push({ role: "assistant", content: finalText });
  if (h.length > 24) S.histories[sentAgent] = h.slice(-24);

  S.busy = false;
  S.abort = null;
  $("send").classList.remove("hidden");
  $("stop").classList.add("hidden");
  setDragon(S.turnRefused ? "alert" : "happy");
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
$("clearChat").addEventListener("click", () => transcriptClear());

/* ====================================================================== */
/* policy editor                                                           */
/* ====================================================================== */

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
  const rec = agentRec();
  form.innerHTML = "";

  /* Say which agent and which file, loudly. With more than one policy on disk
   * the single most likely mistake in the room is editing the right form and
   * saving it over the wrong file. */
  $("policyAgent").textContent = rec ? rec.label : "";
  $("policyAgent").className = "chip plain" + (rec ? "" : " hidden");
  $("policyFile").textContent = (S.state || {}).policyFile || "policy.json";

  /* presets */
  if (rec && (rec.presets || []).length) {
    let pg = el("div", "group");
    pg.appendChild(el("h3", null, "Start from a suggested policy"));
    pg.appendChild(el("p", "gsub",
      "Replaces everything below. A preset cannot grant anything you could not " +
      "type into this same form by hand - it is a starting point, not a " +
      "privileged one."));
    const row = el("div", "presetrow");
    for (const pr of rec.presets) {
      const b = el("button", "presetbtn" + (p.name === pr.id ? "" : ""));
      b.type = "button";
      b.appendChild(el("b", null, pr.label));
      b.appendChild(el("span", null, pr.summary));
      b.addEventListener("click", async () => {
        if (!confirm('Replace ' + ($("policyFile").textContent) + ' with the "' +
                     pr.label + '" preset? Your current edits to it are lost.'))
          return;
        const { ok } = await postJSON("/api/policy/preset",
                                      { agent: S.agent, preset: pr.id });
        if (!ok) return toast("Could not apply that preset.", true);
        S.dirty = false;
        await hydrate();
        toast('Applied "' + pr.label + '". The next tool call will use it.');
      });
      row.appendChild(b);
    }
    pg.appendChild(row);
    form.appendChild(pg);
  }

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
    "the Control Panel labels them differently."));
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

/* Every policy call carries the agent id. Without it "Save" on a page showing
 * policies\triage.json would write policy.json, which is the single most
 * expensive bug this feature could have: it would look like it worked. */
const agentQ = () => (S.agent ? "?agent=" + encodeURIComponent(S.agent) : "");

async function refreshPreview() {
  const { body } = await postJSON("/api/policy/preview" + agentQ(),
                                  { policy: S.policy });
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
  const { ok, body } = await postJSON("/api/policy" + agentQ(), S.policy);
  if (!ok) {
    renderLint(body.lint || []);
    toast("Not saved - fix the errors first.", true);
    return;
  }
  S.dirty = false;
  $("savePolicy").textContent = "Save";
  toast("Saved to " + (body.policyFile || "policy.json") +
        ". The next tool call will use it.");
  await hydrate();
});

$("revertPolicy").addEventListener("click", async () => {
  const file = (S.state || {}).policyFile || "policy.json";
  S.dirty = false;
  $("savePolicy").textContent = "Save";
  await hydrate();
  toast("Reverted to " + file + " on disk.");
});

$("dryRun").addEventListener("click", async () => {
  const file = (S.state || {}).policyFile || "policy.json";
  if (S.dirty) {
    toast("Save first - dry-run reads " + file + " from disk.", true);
    return;
  }
  term("\n$ wxc-exec --dry-run   (parse and validate, nothing spawned)\n", "d");
  const { body } = await postJSON("/api/policy/dryrun" + agentQ(), {});
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

  /* setup steps */
  const ol = $("setupSteps");
  ol.innerHTML = "";
  const steps = [
    ["Start the model.",
     "lemonade-server serve",
     "CastleKeep expects it at " + ((st.lemonade || {}).baseUrl || "") +
     ". Load " + ((st.lemonade || {}).model || "the model") + " before you ask Assistant anything."],
    ["Check what this machine can actually enforce.",
     "python verify.py",
     "Writes VERIFY-REPORT.md. Until the negative tests pass, do not describe this setup as contained."],
    ["Start CastleKeep.",
     "python run.py",
     "Serves on 127.0.0.1 and opens a browser. No packages to install."],
    ["Edit the policy while it runs.",
     "notepad policy.json",
     "Or use the Policy tab. Either way the change lands on the next tool call - the policy of a running sandbox is immutable, so it can never land on one already in flight."],
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

  term("\n$ " + name + " " + JSON.stringify(args) + "\n", "b");
  $("toolGo").disabled = true;
  try {
    await sse("/api/tool", { name, arguments: args, agent: S.agent }, (ev) => {
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
  ]);

  const probe = st.probe || {};
  mini("exeCard", [
    ["wxc-exec", st.mxcExe || st.mxcError || "not found"],
    ["Probe", probe.available ? "ok" : (probe.error || "failed")],
    ["Tier", (st.capabilities || {})._tierLabel || probe.tier || "unknown"],
    ["Network dialect", st.dialect],
    ["Project", st.projectDir],
    ["Workspace", st.workspace],
    ["Mailbox", st.mailbox],
  ]);

  const prof = st.profile;
  mini("profileCard", prof ? [
    ["You", prof.userName || "(not given)"],
    ["Agent name", prof.agentName],
    ["Subagents", (prof.subagents || []).join(", ")],
    ["Policy files", (prof.subagents || [])
      .map((id) => (st.agents.find((a) => a.id === id) || {}).policyFile)
      .filter(Boolean).join("   ")],
  ] : [["Setup", "Not done yet - the launch screen will offer it."]]);

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
    "Policy is immutable once a container is provisioned. CastleKeep compiles " +
    "a fresh config from policy.json for every call, which is exactly why an " +
    "edit lands on the next one and never on the one already running.",
    "Nothing on screen claims a tier or a capability that the host did not " +
    "report. If a knob says it cannot be enforced here, that text came from " +
    "wxc-exec's own validation.",
  ].forEach((t) => about.appendChild(el("p", null, t)));
}

$("resetProfile").addEventListener("click", async () => {
  if (!confirm("Forget your name, your agent's name and which subagents are on?" +
               "\n\nYour policy files are left exactly as they are."))
    return;
  await postJSON("/api/profile/reset", {});
  location.href = "/onboard";
});

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
hydrate().then(() => {
  // Somebody who has never been through setup lands here with no profile -
  // usually by bookmarking /app. Send them to the front of the queue rather
  // than letting them wonder why the agent has no name.
  if (!S.state.profile) {
    location.href = "/onboard";
    return;
  }
  renderTranscript();
}).catch((e) => {
  toast("Could not reach the CastleKeep server: " + e.message, true);
});
