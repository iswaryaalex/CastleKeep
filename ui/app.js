/*
 * Sanctum UI.
 *
 * One rule runs through this file: nothing here decides anything. Every tier,
 * every capability, every refusal on screen came from the host - from
 * `wxc-exec --probe`, from a --dry-run, or from a sandbox that really ran and
 * really failed. If the server did not say it, this file does not draw it.
 */

import { dragonSvg } from "/dragon.js";
import { critterSvg } from "/critters.js";
import { applyTheme, themePicker } from "/theme.js";

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

/* The face of whichever agent is selected. Each one wears a different animal,
 * chosen during setup, so "which agent am I talking to" is answerable from the
 * corner of your eye rather than by reading a title. The dragon stays on as
 * the app's own mark in the title bar - it is Sanctum, not an agent. */
function critterOf(agentId) {
  const agents = (S.state && S.state.agents) || [];
  const rec = agents.find((a) => a.id === agentId);
  return (rec && rec.critter) || "fox";
}

function faceOf(agentId, state) {
  return critterSvg(critterOf(agentId), state || "idle");
}

/* The Sanctum logo: a circle of five cute animals (fox, cat, owl, bunny,
   axolotl) arranged around a ring, each holding a small torch flame.
   Drawn as a compact 28×28 SVG so it reads as a mark at small sizes. */
const SANCTUM_LOGO = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28">
  <!-- outer ring -->
  <circle cx="14" cy="14" r="13" fill="none" stroke="var(--brand)" stroke-width="1.5"/>
  <!-- inner glow -->
  <circle cx="14" cy="14" r="7" fill="var(--brand-soft)" stroke="var(--brand-line)" stroke-width="1"/>
  <!-- five animal heads spaced evenly (72° apart), each at r=9.5 from center -->
  <!-- fox  @ 270°: 14,4.5 -->
  <g transform="translate(14,4.5)">
    <circle r="2.6" fill="var(--brand-ink)" opacity=".85"/>
    <!-- ears -->
    <polygon points="-1.8,-2.6 0,-4.2 0.6,-2.2" fill="var(--brand-ink)"/>
    <polygon points="1.8,-2.6 0,-4.2 -0.6,-2.2" fill="var(--brand-ink)"/>
    <!-- eyes -->
    <circle cx="-0.9" cy="-0.4" r="0.45" fill="var(--brand-soft)"/>
    <circle cx="0.9" cy="-0.4" r="0.45" fill="var(--brand-soft)"/>
    <!-- torch flame -->
    <ellipse cx="0" cy="5.4" rx="0.9" ry="1.3" fill="var(--brand)" opacity=".9"/>
    <rect x="-0.35" y="3.6" width="0.7" height="1.9" rx="0.35" fill="var(--brand-ink)" opacity=".6"/>
  </g>
  <!-- cat  @ 342°: 23.0,12.1 -->
  <g transform="translate(23.0,12.1)">
    <circle r="2.6" fill="var(--brand-ink)" opacity=".85"/>
    <polygon points="-1.8,-2.6 0,-4.2 0.6,-2.2" fill="var(--brand-ink)"/>
    <polygon points="1.8,-2.6 0,-4.2 -0.6,-2.2" fill="var(--brand-ink)"/>
    <circle cx="-0.9" cy="-0.4" r="0.45" fill="var(--brand-soft)"/>
    <circle cx="0.9" cy="-0.4" r="0.45" fill="var(--brand-soft)"/>
    <ellipse cx="0" cy="5.4" rx="0.9" ry="1.3" fill="var(--brand)" opacity=".9"/>
    <rect x="-0.35" y="3.6" width="0.7" height="1.9" rx="0.35" fill="var(--brand-ink)" opacity=".6"/>
  </g>
  <!-- owl  @ 54°:  19.6,21.3 -->
  <g transform="translate(19.6,21.3)">
    <circle r="2.6" fill="var(--brand-ink)" opacity=".85"/>
    <!-- owl: two big round eyes instead of ears -->
    <circle cx="-1" cy="-0.3" r="1" fill="var(--brand-soft)"/>
    <circle cx="1" cy="-0.3" r="1" fill="var(--brand-soft)"/>
    <circle cx="-1" cy="-0.3" r="0.45" fill="var(--brand-ink)" opacity=".7"/>
    <circle cx="1" cy="-0.3" r="0.45" fill="var(--brand-ink)" opacity=".7"/>
    <ellipse cx="0" cy="5.4" rx="0.9" ry="1.3" fill="var(--brand)" opacity=".9"/>
    <rect x="-0.35" y="3.6" width="0.7" height="1.9" rx="0.35" fill="var(--brand-ink)" opacity=".6"/>
  </g>
  <!-- bunny @ 126°: 8.4,21.3 -->
  <g transform="translate(8.4,21.3)">
    <circle r="2.6" fill="var(--brand-ink)" opacity=".85"/>
    <!-- bunny: tall thin ears -->
    <ellipse cx="-1.1" cy="-3.8" rx="0.55" ry="1.6" fill="var(--brand-ink)"/>
    <ellipse cx="1.1" cy="-3.8" rx="0.55" ry="1.6" fill="var(--brand-ink)"/>
    <circle cx="-0.9" cy="-0.4" r="0.45" fill="var(--brand-soft)"/>
    <circle cx="0.9" cy="-0.4" r="0.45" fill="var(--brand-soft)"/>
    <ellipse cx="0" cy="5.4" rx="0.9" ry="1.3" fill="var(--brand)" opacity=".9"/>
    <rect x="-0.35" y="3.6" width="0.7" height="1.9" rx="0.35" fill="var(--brand-ink)" opacity=".6"/>
  </g>
  <!-- axolotl @ 198°: 5.0,12.1 -->
  <g transform="translate(5.0,12.1)">
    <circle r="2.6" fill="var(--brand-ink)" opacity=".85"/>
    <!-- axolotl: gill fronds -->
    <path d="M-2.2,-1.8 Q-3.8,-3.2 -2.6,-4.2" stroke="var(--brand-ink)" stroke-width="0.7" fill="none"/>
    <path d="M2.2,-1.8 Q3.8,-3.2 2.6,-4.2" stroke="var(--brand-ink)" stroke-width="0.7" fill="none"/>
    <circle cx="-0.9" cy="-0.4" r="0.45" fill="var(--brand-soft)"/>
    <circle cx="0.9" cy="-0.4" r="0.45" fill="var(--brand-soft)"/>
    <ellipse cx="0" cy="5.4" rx="0.9" ry="1.3" fill="var(--brand)" opacity=".9"/>
    <rect x="-0.35" y="3.6" width="0.7" height="1.9" rx="0.35" fill="var(--brand-ink)" opacity=".6"/>
  </g>
</svg>`;

function setDragon(state) {
  const brand = $("brandDragon");
  if (brand) brand.innerHTML = SANCTUM_LOGO;
  const mine = faceOf(S.agent, state);
  ["chatDragon", "emptyDragon"].forEach((id) => {
    const n = $(id);
    if (n) n.innerHTML = mine;
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
  // Memory draws from the basecamp poll; refresh it once on entry so an
  // opened tab is current rather than up to one tick stale.
  if (name === "memory") {
    renderMemory();
    if (typeof loadKeeper === "function") loadKeeper().then(renderMemory);
  }
}

document.querySelectorAll(".nav").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));
document.body.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) showTab(g.dataset.goto);
});

/* Memory is a read-only window on what the always-on agent has collected -
 * the merged inbox, drafts and calendar it keeps in mailbox\. It reuses the
 * basecamp poll (K.data) so opening the tab costs nothing, and refreshes it
 * once on entry so a freshly-opened tab is not a tick stale. */
function renderMemory() {
  const d = (typeof K !== "undefined" && K.data) || {};
  const inbox = d.inbox || [];
  const drafts = d.drafts || [];
  const cal = d.calendar || [];

  const mail = $("memMailbox");
  if (mail) {
    mail.innerHTML = "";
    const rows = [
      ["In the inbox", String(inbox.length)],
      ["Drafts waiting", String(drafts.length)],
      ["Days on the calendar", String(cal.length)],
    ];
    for (const [k, v] of rows) {
      const row = el("div", "row");
      row.appendChild(el("b", null, k));
      row.appendChild(el("span", null, v));
      mail.appendChild(row);
    }
    if (!inbox.length && !drafts.length)
      mail.appendChild(el("p", "muted",
        "Nothing collected yet. As agents produce invites and drafts, the " +
        "always-on agent merges them here."));
  }

  const cbox = $("memCalendar");
  if (cbox) {
    cbox.innerHTML = "";
    const flat = flattenCalendar(cal).slice(0, 8);
    if (!flat.length) cbox.appendChild(el("p", "muted", "No upcoming events."));
    for (const ev of flat) {
      const row = el("div", "row");
      row.appendChild(el("b", null, ev.day + "  " + ev.when));
      row.appendChild(el("span", null, ev.title));
      cbox.appendChild(row);
    }
  }
}

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
  applyTheme((st.profile || {}).theme);
  renderAgentNav();
  renderPersonaStrip();
  renderChrome();
  renderMission();
  renderControl();
  renderPolicy();
  renderRunTab();
  renderSettings();
  if ((agentRec() || {}).sidePane === "mailbox") loadMailbox();
  renderKeeper();
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

/* Agents are shown in the main panel persona strip, not in the sidebar.
   The sidebar just holds the always-on (base) agent card at the bottom. */
function renderAgentNav() {
  const slot = $("alwaysOnSlot");
  if (!slot) return;
  slot.innerHTML = "";
  const base = (S.state.agents || []).find((a) => a.role === "base" && a.enabled);
  if (!base) return;

  const sep = el("div", "rail-sep");
  const label = el("div", "rail-label rail-always", "Always on");
  const b = el("button",
    "nav agent always-on" + (base.id === S.agent ? " on" : ""));
  b.appendChild(faceNode(base.id, "idle"));
  b.appendChild(document.createTextNode(baseName()));
  b.title = base.blurb;
  b.addEventListener("click", () => switchAgent(base.id));

  slot.appendChild(label);
  slot.appendChild(b);
}

function faceNode(agentId, state) {
  const n = el("span", "face");
  n.innerHTML = faceOf(agentId, state);
  return n;
}

function baseName() {
  return ((S.state || {}).profile || {}).agentName || "Assistant";
}

/* The strip above the transcript. Personas only: these are the four you take
 * turns talking to, and each has its own folder, its own tools and its own
 * policy file waiting behind it. */
function renderPersonaStrip() {
  const box = $("personaStrip");
  if (!box) return;
  const personas = (S.state.agents || [])
    .filter((a) => a.enabled && a.role === "persona");
  box.innerHTML = "";
  box.classList.toggle("hidden", personas.length < 2);
  for (const a of personas) {
    const b = el("button", "persona" + (a.id === S.agent ? " on" : ""));
    b.type = "button";
    b.appendChild(faceNode(a.id, a.id === S.agent ? "happy" : "idle"));
    b.appendChild(document.createTextNode(a.label));
    b.title = a.blurb;
    b.disabled = S.busy;
    b.addEventListener("click", () => switchAgent(a.id));
    box.appendChild(b);
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

  /* The router, made visible. When the selected agent has its own model, the
   * chip reports THAT model, not the global default - because that is the one
   * Lemonade will actually serve this agent's next turn. The chip turns the
   * brand colour so the override is obvious at a glance. */
  const override = ((st.profile || {}).agentModels || {})[S.agent];
  if (lem.reachable && lem.modelPresent && override && override !== lem.model) {
    m.className = "chip warn";
    m.textContent = override + "  (this agent)";
    m.title = (agentRec() || {}).label + " is routed to " + override +
              " - the rest of the app uses " + lem.model + ".";
  }

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

  /* Who you are actually talking to. The name the participant typed belongs to
   * the BASE agent and to nothing else - putting it in front of every persona
   * ("Pip · Health", "Ask Pip something" while Health is selected) undoes the
   * one thing the strip above the transcript is there to teach, which is that
   * these are four separate agents with four separate policy files. The brand
   * keeps the chosen name, because that is the app's own corner. */
  const prof = st.profile || {};
  const rec = agentRec();
  const name = prof.agentName || "Assistant";
  const here = rec ? (rec.role === "base" ? name : rec.label) : name;
  // The brand is the app's own corner: it is Sanctum, not the agent you are
  // talking to. The agent name lives in the sub-line and in the chat title.
  document.querySelector(".brand-name").textContent = "Sanctum";
  document.querySelector(".brand-sub").textContent =
    rec ? rec.label.toLowerCase() : "local assistant";
  document.title = name + " - Sanctum";

  $("chatTitle").textContent = here;
  $("chatSub").textContent = rec
    ? rec.blurb + " Runs on this machine; nothing you type leaves it."
    : "Runs on this machine. Nothing you type leaves it.";
  $("input").placeholder = "Ask " + here + " something…";

  /* The empty state belongs to renderEmptyState, which owns those nodes and
   * rebuilds them for whichever agent is selected. Writing to them from here
   * would reach for elements a transcript redraw has already replaced, and
   * hydrate() runs after every save, every tool run and every agent switch. */
  if ($("transcript").querySelector(".empty")) renderEmptyState();
}

/* --------------------------------------------------------- sandbox status */

/* The structured status, one row per control, as the reference mock shows:
 * an icon, a label, a plain-language line, and a chip that says whether the
 * host ENFORCES it. "status" is one of ok (green, enforced/blocked-as-asked),
 * allow (green, deliberately open), or off (neutral). The chip word is chosen
 * to read true in a room: a read grant that is locked down says "Blocked",
 * outbound that is open says "Allowed". */
function sandboxStatus(p) {
  const paths = p.paths || {};
  const net = p.network || {};
  const ui = p.ui || {};
  const n = (a) => (a && a.length) || 0;
  const netDead = S.state && S.state.dialect === "none";

  const readable = n(paths.read) > 0;
  const writable = n(paths.write) > 0;
  const outOpen = net.outbound === "allow";
  const toolsOff = Object.entries(p.tools || {})
    .filter(([, on]) => !on).map(([k]) => k);

  return [
    { ic: "cube", label: "Containment",
      sub: "Running in an isolated container",
      chip: "Enforced", status: "ok" },
    { ic: "folder", label: "Readable",
      sub: readable ? n(paths.read) + " path" + (n(paths.read) === 1 ? "" : "s") + " granted"
                    : "No local file read access",
      chip: readable ? "Scoped" : "Blocked", status: readable ? "allow" : "ok" },
    { ic: "pencil", label: "Writable",
      sub: writable ? n(paths.write) + " path" + (n(paths.write) === 1 ? "" : "s") + " granted"
                    : "No local file write access",
      chip: writable ? "Scoped" : "Blocked", status: writable ? "allow" : "ok" },
    { ic: "globe", label: "Outbound",
      sub: netDead ? "Not enforced on this host"
                   : (outOpen ? "Network calls permitted" : "No outbound network"),
      chip: netDead ? "n/a" : (outOpen ? "Allowed" : "Blocked"),
      status: netDead ? "off" : (outOpen ? "allow" : "ok") },
    { ic: "network", label: "Local network",
      sub: netDead ? "Not enforced on this host"
                   : (net.localNetwork ? "Local network reachable" : "No local network access"),
      chip: netDead ? "n/a" : (net.localNetwork ? "Allowed" : "Blocked"),
      status: netDead ? "off" : (net.localNetwork ? "allow" : "ok") },
    { ic: "window", label: "Windows / UI",
      sub: ui.allowWindows ? "Desktop interaction permitted" : "No UI or desktop interaction",
      chip: ui.allowWindows ? "Allowed" : "Blocked",
      status: ui.allowWindows ? "allow" : "ok" },
    { ic: "clock", label: "Timeout",
      sub: "Max " + Math.round(((p.limits || {}).timeoutMs || 30000) / 1000) +
           "s per request",
      chip: Math.round(((p.limits || {}).timeoutMs || 30000) / 1000) + "s", status: "off" },
    { ic: "tools", label: "Tools off",
      sub: toolsOff.length ? toolsOff.join(", ") : "Every tool in this policy is on",
      chip: toolsOff.length ? "Disabled" : "All on",
      status: toolsOff.length ? "ok" : "allow" },
  ];
}

const SBX_IC = {
  cube:    "M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10",
  folder:  "M3 6h6l2 2h10v11H3z",
  pencil:  "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  globe:   "M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2c3 3 3 17 0 20M12 2c-3 3-3 17 0 20",
  network: "M6 7a2 2 0 100-4 2 2 0 000 4zM18 7a2 2 0 100-4 2 2 0 000 4zM12 21a2 2 0 100-4 2 2 0 000 4zM6 5h12M6 5l6 12M18 5l-6 12",
  window:  "M3 4h18v16H3zM3 9h18M7 6.5h.01M10 6.5h.01",
  clock:   "M12 2a10 10 0 100 20 10 10 0 000-20zM12 7v5l3 2",
  tools:   "M14 7a3 3 0 00-4 4l-6 6 2 2 6-6a3 3 0 004-4l-2 2-2-2z",
};

function sbxIcon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "sbx-ic");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", SBX_IC[name] || SBX_IC.cube);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.6");
  path.setAttribute("stroke-linejoin", "round");
  path.setAttribute("stroke-linecap", "round");
  svg.appendChild(path);
  return svg;
}

function renderMission() {
  const rec = agentRec() || {};
  const mail = rec.sidePane === "mailbox";
  $("sideTitle").textContent = mail ? "Mailbox" : "Sandbox Status";
  if ($("sbxOn")) $("sbxOn").classList.toggle("hidden", mail);
  $("mailboxView").classList.toggle("hidden", !mail);
  $("missionView").classList.toggle("hidden", mail);

  const p = S.state.policy || {};
  const here = rec.role === "base" ? baseName() : (rec.label || "this agent");
  if ($("sbxSub"))
    $("sbxSub").textContent =
      "What " + here + " may touch, enforced on every tool call.";

  const box = $("sbxRows");
  if (box) {
    box.innerHTML = "";
    for (const r of sandboxStatus(p)) {
      const row = el("div", "sbx-row");
      const icw = el("span", "sbx-icw status-" + r.status);
      icw.appendChild(sbxIcon(r.ic));
      row.appendChild(icw);
      const txt = el("div", "sbx-txt");
      txt.appendChild(el("div", "sbx-label", r.label));
      txt.appendChild(el("div", "sbx-sub", r.sub));
      row.appendChild(txt);
      row.appendChild(el("span", "sbx-chip chip-" + r.status, r.chip));
      box.appendChild(row);
    }
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

    // A policy block is the one outcome you can do something about from here.
    // Offer the diff inline rather than making somebody reconstruct which path
    // was refused and hand-edit the policy file to add it.
    const fix = r.outcome === "blocked" ? suggestFix(r) : null;
    if (fix) {
      const b = el("button", "fixbtn", "Fix →");
      b.title = "Show which grant was missing and add it";
      box.appendChild(row);
      const panel = el("div", "denial-panel hidden");
      b.addEventListener("click", () => {
        const open = !panel.classList.contains("hidden");
        panel.classList.toggle("hidden", open);
        b.classList.toggle("on", !open);
        if (!open && !panel.dataset.built) {
          renderDenialDiff(fix, panel, b);
          panel.dataset.built = "1";
        }
      });
      row.appendChild(b);
      box.appendChild(panel);
      continue;
    }

    const t = el("span", "mono right", r.durationMs != null ? r.durationMs + " ms" : "");
    row.appendChild(t);
    box.appendChild(row);
  }
}

/* ---------------------------------------------------- denial -> policy fix */

/* Turn a real Windows path back into the token a policy would use, longest
 * match first so ${vault}\health beats a bare drive. Mirrors policy.expand on
 * the server, but in reverse - we only ever offer a token the server can
 * expand back to the same path. */
function tokenisePath(abs) {
  const ctx = (S.state && S.state.paths) || {};
  // Longest value first: ${vault}\health must win over ${systemdrive}.
  const entries = Object.entries(ctx)
    .filter(([, v]) => typeof v === "string" && v.length > 2)
    .sort((a, b) => b[1].length - a[1].length);
  const low = abs.toLowerCase();
  for (const [key, val] of entries) {
    const v = String(val).toLowerCase().replace(/[\\/]+$/, "");
    if (low === v || low.startsWith(v + "\\") || low.startsWith(v + "/")) {
      const rest = abs.slice(val.replace(/[\\/]+$/, "").length);
      return "${" + key + "}" + rest.replace(/\//g, "\\");
    }
  }
  return abs; // no token matched; offer the literal path
}

/* What path was refused, and what read grant would let it through. Returns
 * null when there is nothing actionable (no path in the arguments, or the
 * path is already granted and the block was something else). */
function suggestFix(run) {
  const args = run.arguments || {};
  // read_file/list_files use `path`; move_file a `source`; everything else we
  // leave alone, because widening write or network from a one-click button is
  // exactly the kind of thing that should go through the full policy editor.
  const readTools = { read_file: "path", list_files: "path", read_record: "path",
                      list_records: "path", search_records: "path" };
  const field = readTools[run.tool];
  if (!field) return null;
  const abs = args[field] || args.path;
  if (!abs || typeof abs !== "string") return null;

  const token = tokenisePath(abs);
  const pol = S.policy || S.state.policy || {};
  const read = ((pol.paths || {}).read || []).slice();

  // Already granted? Then the block was not a missing read path and this
  // button would write a no-op. Say nothing rather than offer a fake fix.
  const already = read.some((p) => p.toLowerCase() === token.toLowerCase());
  if (already) return null;

  return { run, abs, token, read, after: read.concat([token]) };
}

/* The inline before/after. Left is the policy's read list now, with the
 * missing path absent; right is the same list with it added, highlighted. */
function renderDenialDiff(fix, panel, btn) {
  panel.innerHTML = "";

  const head = el("div", "denial-head");
  head.appendChild(el("b", null, "Denied path"));
  head.appendChild(el("code", "denial-path", fix.abs));
  panel.appendChild(head);

  const cols = el("div", "diff-cols");

  const now = el("div", "diff-col");
  now.appendChild(el("div", "diff-h", "paths.read now"));
  for (const p of fix.read) now.appendChild(el("code", "diff-line", p));
  if (!fix.read.length) now.appendChild(el("code", "diff-line muted", "(empty)"));
  cols.appendChild(now);

  const next = el("div", "diff-col");
  next.appendChild(el("div", "diff-h", "after the fix"));
  for (const p of fix.read) next.appendChild(el("code", "diff-line", p));
  next.appendChild(el("code", "diff-line diff-add", fix.token));
  cols.appendChild(next);

  panel.appendChild(cols);

  const actions = el("div", "denial-actions");
  const apply = el("button", "btn primary", "Apply fix");
  apply.addEventListener("click", () => applyDenialFix(fix, apply, panel, btn));
  actions.appendChild(apply);
  const open = el("button", "btn ghost", "Open Sandbox settings");
  open.addEventListener("click", () => showTab("policy"));
  actions.appendChild(open);
  panel.appendChild(actions);
}

/* Save the widened read list through the same /api/policy endpoint the editor
 * uses, so it goes through the same lint before it is written. On success the
 * next tool call picks it up - no restart, which is the whole point. */
async function applyDenialFix(fix, btn, panel, toggleBtn) {
  btn.disabled = true;
  btn.textContent = "Saving…";
  const next = JSON.parse(JSON.stringify(S.policy || S.state.policy || {}));
  next.paths = next.paths || {};
  next.paths.read = fix.after.slice();
  const { ok, body } = await postJSON("/api/policy" + agentQ(), next);
  if (!ok || body.saved === false) {
    btn.disabled = false;
    btn.textContent = "Apply fix";
    const why = (body.lint || []).find((n) => n.level === "error");
    toast("Could not save: " + (why ? why.message : "policy rejected"), true);
    return;
  }
  S.dirty = false;
  toast("Added " + fix.token + " to paths.read. The next run will use it.");
  panel.classList.add("hidden");
  if (toggleBtn) toggleBtn.classList.remove("on");
  await hydrate();
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
  // Amber, not red. A timeout is the policy's time limit doing its job, not
  // an access refusal - colouring it like a block teaches the wrong lesson.
  "timeout":          ["warn",  "stopped on time"],
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
  add("Sandboxes spawned", String(runs.length), "since Sanctum started");
  add("Refused", String(refused.length), "host gates, policy blocks, bad configs");
  add("Network dialect", st.dialect || "?",
      st.dialect === "none" ? "neither dialect was accepted" : "negotiated with --dry-run");
  add("Model", (st.lemonade || {}).reachable ? "up" : "down",
      (st.lemonade || {}).baseUrl || "");

  /* refused feed */
  const feed = $("refusedFeed");
  feed.innerHTML = "";
  if (!refused.length) {
    feed.appendChild(el("p", "muted", "Nothing refused yet. Ask an agent to read something outside its granted paths."));
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
  av.innerHTML = faceOf(S.agent, "idle");
  wrap.appendChild(av);
  wrap.appendChild(el("h2", null, rec.role === "base"
    ? "What has arrived?"
    : "Ask " + (rec.label || "your agent") + " something."));
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
    av.innerHTML = faceOf(S.agent, "idle");
    who.appendChild(av);
    wrap.appendChild(who);
  }
  const body = el("div", "body");
  if (role === "assistant") {
    const rec = agentRec() || {};
    body.appendChild(el("div", "name",
      rec.role === "base" ? baseName() : (rec.label || "Assistant")));
  }
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

/* The agent picker in the Sandbox header. A plain <select> of every enabled
 * agent - personas first, the always-on agent last under its own group - so
 * you can edit any policy file from one place. Switching is a real agent
 * switch (switchAgent), so the form, the file path and the live JSON all
 * follow. */
function renderPolicyAgentPick(rec) {
  const sel = $("policyAgentPick");
  if (!sel) return;
  const agents = (S.state.agents || []).filter((a) => a.enabled);
  const personas = agents.filter((a) => a.role !== "base");
  const base = agents.filter((a) => a.role === "base");
  sel.innerHTML = "";

  const addOpt = (a) => {
    const o = el("option", null,
      a.role === "base" ? baseName() + " (always on)" : a.label);
    o.value = a.id;
    if (a.id === S.agent) o.selected = true;
    sel.appendChild(o);
  };
  personas.forEach(addOpt);
  base.forEach(addOpt);

  sel.onchange = () => {
    const id = sel.value;
    if (id && id !== S.agent) switchAgent(id);
  };
}

function renderPolicy() {
  const form = $("policyForm");
  const p = S.policy;
  const rec = agentRec();
  form.innerHTML = "";

  /* Say which agent and which file, loudly. With more than one policy on disk
   * the single most likely mistake in the room is editing the right form and
   * saving it over the wrong file - so the agent picker lives right here, next
   * to Save, rather than only in the chat rail. */
  renderPolicyAgentPick(rec);
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

  /* paths - the main config, lifted onto a whiter card so it reads as the
     primary thing on the page and the rest as secondary knobs around it. */
  let g = el("div", "group group-main");
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
 * policies\health.json would write policy.json, which is the single most
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

/* The sack, for the presenter. Drawn from /api/basecamp, which the bubble is
 * already polling, so this costs nothing extra. */
function renderPost() {
  const box = $("postList");
  if (!box) return;
  const post = ((K.data || {}).post) || [];
  box.innerHTML = "";
  if (!post.length) {
    box.appendChild(el("p", "muted",
      "Nothing left to deliver. Restart the session clock to rehearse again - " +
      "it will not un-deliver anything, so delete mailbox\\ for a clean run."));
    return;
  }
  for (const item of post) {
    const row = el("div", "item");
    const when = el("span", "chip " + (item.onCue ? "info" : "plain"),
      item.onCue ? "on cue"
                 : item.dueIn <= 0 ? "due now" : inWords(item.dueIn));
    row.appendChild(when);
    const body = el("div");
    body.appendChild(el("span", null, item.subject || item.id));
    body.appendChild(el("div", "mono", item.from || ""));
    row.appendChild(body);
    const go = el("button", "btn ghost right", "Deliver now");
    go.addEventListener("click", async () => {
      go.disabled = true;
      const { body: got } = await postJSON("/api/mailbox/deliver", { id: item.id });
      if (got && got.delivered) toast("Delivered: " + got.message.subject);
      else toast("Nothing was delivered.", true);
      await loadKeeper();
      renderPost();
    });
    row.appendChild(go);
    box.appendChild(row);
  }
}

/* The live calendar feed, for the presenter. Everything here came from the
 * server: whether it is configured, when it last succeeded, and what it did
 * to the day files. */
function renderCalFeed() {
  const box = $("calFeed");
  if (!box) return;
  const f = ((K.data || {}).calendarFeed) || { state: "cold" };
  const rows = [];

  if (f.state === "off") {
    rows.push(["Feed", "not configured"]);
    rows.push(["How", "set calendar.icsUrl in config.json"]);
  } else if (f.state === "error") {
    rows.push(["Feed", "could not be reached"]);
    rows.push(["Error", f.error || "unknown"]);
    rows.push(["Showing", "the last copy that worked"]);
  } else if (f.state === "ok") {
    rows.push(["Last refresh", f.at ? ago(f.at * 1000) : "-"]);
    rows.push(["Days", String(f.days)]);
    rows.push(["Events from Google", String(f.events)]);
    rows.push(["Kept from agents", String(f.keptFromAgents)]);
    if (f.removedStale) rows.push(["Swept (moved/deleted)", String(f.removedStale)]);
    rows.push(["Window", f.window || "-"]);
    if (f.recurring)
      rows.push(["Recurring", f.recurring + " kept first instance only"]);
    if (f.outsideWindow)
      rows.push(["Outside window", f.outsideWindow + " dropped"]);
  } else {
    rows.push(["Feed", "has not run yet"]);
  }
  mini("calFeed", rows);
}

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
     "Sanctum expects it at " + ((st.lemonade || {}).baseUrl || "") +
     ". Load " + ((st.lemonade || {}).model || "the model") + " before you ask Assistant anything."],
    ["Check what this machine can actually enforce.",
     "python verify.py",
     "Writes VERIFY-REPORT.md. Until the negative tests pass, do not describe this setup as contained."],
    ["Start Sanctum.",
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

/* One row per agent: a face, a name, and a model dropdown that defaults to the
 * global model. This is the router made tangible - set the coding agent to the
 * 35B and watch the model chip change when you switch to it. */
function renderAgentModels() {
  const box = $("agentModels");
  if (!box) return;
  const st = S.state;
  const overrides = ((st.profile || {}).agentModels) || {};
  const agents = (st.agents || []).filter((a) => a.enabled);
  const order = agents.filter((a) => a.role !== "base")
    .concat(agents.filter((a) => a.role === "base"));
  box.innerHTML = "";
  for (const a of order) {
    const row = el("div", "agentmodel-row");
    const face = el("span", "face sm");
    face.innerHTML = faceOf(a.id, "idle");
    row.appendChild(face);
    row.appendChild(el("span", "agentmodel-name",
      a.role === "base" ? baseName() : a.label));
    const sel = el("select", "agentpick");
    fillModelSelect(sel, overrides[a.id] || "", true);
    sel.addEventListener("change", async () => {
      const { ok, body } = await postJSON("/api/agent-model",
        { agent: a.id, model: sel.value });
      if (!ok) { toast((body && body.error) || "Could not set model.", true); return; }
      toast(sel.value
        ? (a.role === "base" ? baseName() : a.label) + " now runs on " + sel.value
        : (a.role === "base" ? baseName() : a.label) + " back to the default model.");
      await hydrate();
    });
    row.appendChild(sel);
    box.appendChild(row);
  }
}

/* Chat-capable models only. Lemonade also serves Whisper (speech-to-text)
 * builds, which will 404 the moment the agent loop sends them a chat payload -
 * so they do not belong in a model picker for an agent. */
function chatModels() {
  const lem = (S.state || {}).lemonade || {};
  return (lem.models || []).filter((m) => !/^whisper/i.test(m));
}

function fillModelSelect(sel, chosen, includeDefault) {
  if (!sel) return;
  sel.innerHTML = "";
  if (includeDefault) {
    const o = el("option", null, "Default (" + (((S.state || {}).lemonade || {}).model || "global") + ")");
    o.value = "";
    sel.appendChild(o);
  }
  for (const m of chatModels()) {
    const o = el("option", null, m);
    o.value = m;
    if (m === chosen) o.selected = true;
    sel.appendChild(o);
  }
  if (!chosen && includeDefault) sel.value = "";
}

function renderSettings() {
  const st = S.state;
  const lem = st.lemonade || {};

  /* Global model picker. The select lists what Lemonade actually serves, so a
     choice here cannot 404 at chat time. Applying writes config.json and warms
     the new model, same path as workshop\\models.py --pick. */
  fillModelSelect($("modelSelect"), lem.model, false);

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

  renderAgentModels();

  const probe = st.probe || {};
  mini("exeCard", [
    ["wxc-exec", st.mxcExe || st.mxcError || "not found"],
    ["Probe", probe.available ? "ok" : (probe.error || "failed")],
    ["Tier", (st.capabilities || {})._tierLabel || probe.tier || "unknown"],
    ["Network dialect", st.dialect],
    ["Project", st.projectDir],
    ["Workspace", st.workspace],
    ["Mailbox", st.mailbox],
    ["Vault", st.vault],
  ]);

  const prof = st.profile;
  const conn = (prof && prof.connectors) || {};
  mini("profileCard", prof ? [
    ["You", prof.userName || "(not given)"],
    ["Base agent", prof.agentName + "  (" + critterOf("base") + ")"],
    ["Agents", (prof.subagents || [])
      .filter((id) => id !== "base")
      .map((id) => (st.agents.find((a) => a.id === id) || {}).label +
                   "  (" + critterOf(id) + ")").join("   ")],
    ["Accounts", [conn.gmail, conn.reddit && "u/" + conn.reddit,
                  conn.github && "github.com/" + conn.github]
      .filter(Boolean).join("   ") || "(none)"],
    ["Policy files", (prof.subagents || [])
      .map((id) => (st.agents.find((a) => a.id === id) || {}).policyFile)
      .filter(Boolean).join("   ")],
  ] : [["Setup", "Not done yet - the launch screen will offer it."]]);

  // Rebuilt on every hydrate, which is cheap and means the highlighted swatch
  // can never disagree with the profile the server just handed back.
  themePicker($("themeRow"), (prof || {}).theme || "parchment", saveTheme);

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
    "is the only honest arrangement. Sanctum contains what the agent does, " +
    "not what the agent is.",
    "Policy is immutable once a container is provisioned. Sanctum compiles " +
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

$("modelApply").addEventListener("click", async () => {
  const name = $("modelSelect").value;
  if (!name) return;
  const btn = $("modelApply");
  btn.disabled = true;
  $("modelApplyHint").textContent = "Pointing Lemonade at " + name + "…";
  const { ok, body } = await postJSON("/api/model", { model: name });
  btn.disabled = false;
  if (!ok) {
    $("modelApplyHint").textContent = (body && body.error) || "Could not switch model.";
    return;
  }
  $("modelApplyHint").textContent = "Now on " + name + ". Warming it now.";
  await hydrate();
  toast("Model is now " + name + ".");
});

/* ====================================================================== */
/* theme                                                                   */
/* ====================================================================== */

/* applyTheme has already repainted by the time this runs - themePicker does
 * that itself so the swatch feels instant. This only persists the choice, and
 * a failure to persist is worth a toast but not worth undoing the repaint. */
async function saveTheme(id) {
  if (!S.state || !S.state.profile) return;
  const { ok } = await postJSON("/api/profile",
    Object.assign({}, S.state.profile, { theme: id }));
  if (ok) S.state.profile.theme = id;
  else toast("Could not save the theme to profile.json.", true);
}

/* ====================================================================== */
/* the base agent's bubble                                                 */
/* ====================================================================== */

/* Everything below draws state the SERVER produced. The counter, the refusals
 * and the "last checked" time all come from a real sandboxed sync_vaults run
 * under policies\base.json; the lists are a host-side read of what that run
 * was allowed to write. If the policy stops the merge, the lists stop growing
 * and the note below says why, in Windows' own words. Nothing here invents a
 * success. */

const K = { open: false, tab: "calendar", data: null, poll: null };

const KTAB_EMPTY = {
  calendar: "Nothing on the calendar yet. Ask an agent to make an " +
            "appointment and it will appear here.",
  drafts:   "No drafts yet. Ask an agent to write a message and it will " +
            "appear here.",
  inbox:    "The mailbox is empty.",
};

function keeperEnabled() {
  return !!(S.state && (S.state.agents || []).some((a) => a.role === "base"));
}

function renderKeeper() {
  const wrap = $("keeper");
  if (!wrap) return;
  wrap.hidden = !keeperEnabled();
  if (wrap.hidden) return;
  $("keeperName").textContent = baseName();
  $("keeperFace").innerHTML = faceOf("base", K.open ? "happy" : "idle");
  if (!K.poll) {
    loadKeeper();
    K.poll = setInterval(loadKeeper, 6000);
  }
}

async function loadKeeper() {
  if (!keeperEnabled()) return;
  try {
    K.data = await getJSON("/api/basecamp");
  } catch (e) {
    return;   // the server is restarting; the next tick tries again
  }
  drawKeeper();
}

function drawKeeper() {
  const d = K.data;
  if (!d) return;
  const sync = d.sync || {};
  const btn = $("keeperBtn");
  const badge = $("keeperBadge");

  btn.className = "keeper-btn" +
    (sync.state === "blocked" ? " blocked" :
     sync.state === "partial" ? " partial" : "");
  // innerHTML, so the badge has to be re-attached rather than written over.
  btn.innerHTML = "";
  btn.appendChild(badge);
  btn.insertAdjacentHTML("beforeend",
    faceOf("base", sync.state === "blocked" ? "alert" :
                   sync.state === "partial" ? "thinking" :
                   sync.unread ? "happy" : "idle"));

  badge.hidden = !sync.unread;
  badge.textContent = sync.unread > 99 ? "99+" : String(sync.unread || 0);
  btn.title = keeperTitle(d);

  $("keeperSub").textContent =
    "always on · checks every " + Math.round(d.intervalSec || 20) + "s";
  $("keeperFace").innerHTML = faceOf("base", K.open ? "happy" : "idle");
  $("keeperWhen").textContent = sync.at
    ? "checked " + ago(sync.at * 1000)
    : (d.enabled ? "has not run yet" : "not running");

  drawKeeperNote(d);
  renderPost();
  renderCalFeed();
  renderMemory();
  if (K.open) drawKeeperBody();
}

function keeperTitle(d) {
  const sync = d.sync || {};
  if (!d.enabled) return "Not running - finish setup first.";
  if (sync.state === "blocked") return "Refused by its own policy. Open for why.";
  if (sync.state === "partial") return "Some agents got through, some did not.";
  return baseName() + " is watching every agent's outgoing folders.";
}

function drawKeeperNote(d) {
  const n = $("keeperNote");
  const sync = d.sync || {};
  n.innerHTML = "";

  if (!d.enabled) {
    n.className = "keeper-note warn";
    n.appendChild(el("b", null, "Not running."));
    n.appendChild(el("span", null,
      "There is no policy file for this agent yet, so there is nothing to " +
      "run it under. Finish setup and it starts on its own."));
    return;
  }

  if (sync.state === "blocked") {
    n.className = "keeper-note bad";
    n.appendChild(el("b", null, "Its last run was refused."));
    n.appendChild(el("span", null, sync.reason ||
      "The sandbox would not let it read what it needed."));
    return;
  }

  if ((sync.refused || []).length) {
    n.className = "keeper-note bad";
    n.appendChild(el("b", null,
      "Refused " + sync.refused.length + " of its folders."));
    for (const r of sync.refused) {
      const line = el("span", null, "");
      // r.vault, not r.source: the folder is what has to go in the policy
      // file, and for the computer assistant the two are different strings.
      line.appendChild(el("code", null,
        (r.vault === "mailbox" ? "mailbox\\" + r.stage
                               : "vault\\" + r.vault + "\\" + r.stage) +
        " — " + r.error));
      line.appendChild(document.createElement("br"));
      n.appendChild(line);
    }
    n.appendChild(el("span", null,
      "Those agents cannot reach this view until " + baseName() +
      " is granted read on those folders."));
    return;
  }

  n.className = "keeper-note ok";
  n.appendChild(el("span", null, d.pending
    ? "Collecting from " + d.pending + " item" + (d.pending === 1 ? "" : "s") +
      " across every agent's outgoing folders. It can see those folders and " +
      "nothing else inside them."
    : "Nothing waiting. The moment an agent writes an invitation or a draft, " +
      "it shows up here."));

  // A calendar that could not be refreshed is showing old data. Say so here
  // rather than only in the Run tab: the participant reading the Calendar
  // tab is the one being misled by it.
  const feed = d.calendarFeed || {};
  if (feed.state === "error") {
    n.appendChild(document.createElement("br"));
    n.appendChild(el("span", null,
      "The calendar feed could not be reached, so this is the last copy that " +
      "worked. Anything an agent added since is still here."));
  }

  // How much post is still coming, and when the next of it lands. The COUNT
  // and the time, never the subject: those are in the Run tab, which is the
  // presenter's screen, not the participant's.
  const post = d.post || [];
  if (post.length) {
    const next = post.find((p) => !p.onCue);
    n.appendChild(document.createElement("br"));
    n.appendChild(el("span", null,
      post.length + " more message" + (post.length === 1 ? "" : "s") +
      " still to arrive" +
      (next && next.dueIn > 0 ? " - next in " + inWords(next.dueIn) : "") + "."));
  }
}

function inWords(secs) {
  if (secs <= 60) return "under a minute";
  return Math.round(secs / 60) + " min";
}

function drawKeeperBody() {
  const body = $("keeperBody");
  const d = K.data || {};
  body.innerHTML = "";
  const list = K.tab === "calendar" ? flattenCalendar(d.calendar || [])
             : K.tab === "drafts"   ? (d.drafts || [])
             : (d.inbox || []);

  if (!list.length) {
    body.appendChild(el("p", "muted", KTAB_EMPTY[K.tab]));
    return;
  }

  let day = null;
  for (const item of list) {
    if (K.tab === "calendar" && item.day !== day) {
      day = item.day;
      body.appendChild(el("div", "kday", prettyDay(day)));
    }
    body.appendChild(kitem(item));
  }
}

/* Days, each with its events, flattened into one list the panel can walk.
 *
 * Today forward, oldest first - a calendar that opens on last Tuesday makes
 * the thing an agent just added the hardest row to find, and the thing an
 * agent just added is the entire reason this panel exists. Yesterday is not
 * hidden so much as not led with: if there is nothing upcoming at all, the
 * whole calendar is shown rather than an empty pane that looks like a
 * refusal.
 *
 * Sorted here rather than on the server because the server hands back the
 * calendar exactly as it sits on disk, and "as it sits on disk" is the thing
 * the merge is supposed to be judged on. */
function flattenCalendar(days) {
  const all = (days || []).slice().sort(byDate);
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = all.filter((d) => String(d.date) >= today);
  const out = [];
  for (const d of (upcoming.length ? upcoming : all)) {
    for (const ev of (d.events || [])) {
      out.push({
        day: d.date,
        title: ev.title || "(untitled)",
        when: (ev.start || "") + (ev.end ? "–" + ev.end : ""),
        detail: [ev.location, ev.notes].filter(Boolean).join(" · "),
        source: ev.source || null,
      });
    }
  }
  return out;
}

const byDate = (a, b) => String(a.date).localeCompare(String(b.date));

function kitem(item) {
  // A mail item and a calendar item have different field names; normalise
  // here so the row below only has to know about four things.
  const title = item.title || item.subject || "(no subject)";
  const when = item.when || (item.date || "").slice(11, 16) ||
               (item.date || "").slice(5, 10);
  const detail = item.detail || item.snippet || item.status || "";
  const source = item.source || null;

  // "from an agent" and "from your Google calendar" are different claims and
  // must not look the same. The green bar and the animal face mean an agent
  // produced this; a feed event gets a plain tag and no face, because there
  // is no agent behind it and drawing one would say there was.
  const byAgent = source && source !== FEED_SOURCE;

  const row = el("div", "kitem" + (byAgent ? " fresh" : ""));
  const top = el("div", "top");
  top.appendChild(el("span", "t", title));
  if (when) top.appendChild(el("span", "when", when));
  row.appendChild(top);
  if (detail) row.appendChild(el("div", "d", detail));
  if (byAgent) {
    const tag = el("span", "ktag");
    tag.appendChild(faceNode(source, "idle"));
    tag.appendChild(document.createTextNode("from " + labelOf(source)));
    row.appendChild(tag);
  } else if (source === FEED_SOURCE) {
    const tag = el("span", "ktag feed");
    tag.appendChild(document.createTextNode("Google Calendar"));
    row.appendChild(tag);
  }
  return row;
}

/* What icsfeed.py stamps on an event it pulled from the .ics address. */
const FEED_SOURCE = "calendar";

function labelOf(agentId) {
  const rec = ((S.state || {}).agents || []).find((a) => a.id === agentId);
  return rec ? rec.label.toLowerCase() : agentId;
}

function prettyDay(iso) {
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d)) return iso;
  return d.toLocaleDateString(undefined,
    { weekday: "long", day: "numeric", month: "long" });
}

function ago(ms) {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 10) return "just now";
  if (s < 90) return s + "s ago";
  if (s < 5400) return Math.round(s / 60) + "m ago";
  return Math.round(s / 3600) + "h ago";
}

function toggleKeeper(open) {
  K.open = open === undefined ? !K.open : open;
  $("keeperPanel").hidden = !K.open;
  if (K.open) {
    drawKeeperBody();
    // Clearing the badge is a claim that somebody has looked, so it is sent
    // to the server rather than kept in the tab: the count is the base
    // agent's, and a second window should not still be shouting about items
    // this one has already shown.
    postJSON("/api/basecamp/read", {}).then(() => {
      if (K.data && K.data.sync) K.data.sync.unread = 0;
      drawKeeper();
    });
  }
  renderKeeper();
}

$("keeperBtn").addEventListener("click", () => toggleKeeper());
$("keeperClose").addEventListener("click", () => toggleKeeper(false));

document.querySelectorAll("[data-ktab]").forEach((b) =>
  b.addEventListener("click", () => {
    K.tab = b.dataset.ktab;
    document.querySelectorAll("[data-ktab]").forEach((o) =>
      o.classList.toggle("on", o === b));
    drawKeeperBody();
  }));

$("keeperSync").addEventListener("click", async () => {
  const b = $("keeperSync");
  b.disabled = true;
  b.textContent = "Checking…";
  await postJSON("/api/basecamp/sync", {});
  // One interval plus a little. The sync runs on the background thread's next
  // tick, and reporting "done" before that tick has finished would be a
  // result about the previous run.
  setTimeout(async () => {
    await loadKeeper();
    await hydrate();
    b.disabled = false;
    b.textContent = "Check now";
  }, 2200);
});

$("calRefresh").addEventListener("click", async () => {
  const b = $("calRefresh");
  b.disabled = true;
  b.textContent = "Fetching…";
  const { body } = await postJSON("/api/calendar/refresh", {});
  await loadKeeper();
  await hydrate();
  b.disabled = false;
  b.textContent = "Refresh now";
  if (body && body.state === "ok")
    toast(body.events + " events from Google, " + body.keptFromAgents +
          " kept from agents.");
  else if (body && body.state === "off") toast("No calendar.icsUrl configured.", true);
  else toast("Could not reach the calendar feed.", true);
});

$("postReset").addEventListener("click", async () => {
  const b = $("postReset");
  b.disabled = true;
  await postJSON("/api/mailbox/reset-clock", {});
  await loadKeeper();
  renderPost();
  b.disabled = false;
  toast("Session clock restarted. Timed mail is due from now.");
});

$("keeperPolicy").addEventListener("click", async () => {
  toggleKeeper(false);
  // switchAgent short-circuits to undefined when it is already selected or a
  // turn is running, so this cannot be chained off its return value.
  await switchAgent("base");
  showTab("policy");
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
  toast("Could not reach the Sanctum server: " + e.message, true);
});
