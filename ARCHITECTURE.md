# How CastleKeep is put together

Diagrams are Mermaid. GitHub renders them inline; VS Code needs the *Markdown
Preview Mermaid Support* extension. If you would rather not install anything,
run the app and open **`/architecture`** - the same diagrams, drawn in plain
HTML and CSS, no extension and no CDN.

`COMPILED.md` is the field-by-field mapping from `policy.json` to the
MXCConfiguration wire format. This page is the shape of the system around it.

---

## 1. The one idea

The agent loop and the model run on the host, with your privileges. Only what
the agent *does* goes into a container. That is a real limit, and it is worth
saying out loud rather than glossing: MXC has no long-running-daemon shape on
Windows ProcessContainer, so "an always-on agent living inside the sandbox" is
not a thing that exists.

```mermaid
flowchart TB
    subgraph HOST["HOST - unsandboxed, your privileges"]
        UI["Browser UI<br/>127.0.0.1:7701"]
        SRV["core/server.py<br/>stdlib HTTP + SSE"]
        AG["core/agent.py<br/>the loop"]
        LEM["Lemonade Server<br/>the model"]
    end

    subgraph DISK["DISK"]
        POL["policies/base.json<br/>policies/health.json<br/>policies/finance.json<br/>policies/computer-assist.json<br/>policies/coding.json"]
        MB["mailbox/"]
        WS["workspace/"]
    end

    subgraph SB["MXC SANDBOX - fresh per tool call, destroyed on exit"]
        CMD["one command<br/>cmd.exe or powershell.exe"]
    end

    UI --> SRV
    SRV --> AG
    AG <--> LEM
    POL -->|"re-read before EVERY tool call"| AG
    AG -->|"compiled MXCConfiguration"| CMD
    CMD -->|"granted paths only"| MB
    CMD -->|"granted paths only"| WS
    CMD -->|"stdout, or a refusal"| AG
```

The dashed promise nobody makes: nothing stops the *model* from wanting to do
something. What stops it is that the container it runs commands in cannot
reach anything the policy did not grant.

---

## 2. One tool call, end to end

The important beat is that the policy is read **twice** - once to tell the
model what it can ask for, once again at the moment of the call. That second
read is why an edit in the Policy tab lands on the very next tool call and
never on one already running.

```mermaid
sequenceDiagram
    autonumber
    participant U as You
    participant UI as Browser
    participant S as server.py
    participant A as agent.py
    participant L as Lemonade
    participant P as policies/health.json
    participant X as wxc-exec.exe
    participant C as sandbox

    U->>UI: "archive the newsletter"
    UI->>S: POST /api/chat {agent: "health"}
    S->>A: Agent(app, "health")
    A->>P: reload_policy("health")
    A->>L: messages + tool schemas for health only
    L-->>A: tool_call archive_message
    A->>P: reload_policy("health") AGAIN
    Note over A,P: fresh read, so your edit<br/>lands on THIS call
    A->>A: compile_config -> MXCConfiguration
    A->>X: execute(config)
    X->>C: spawn one-shot container
    C-->>X: Access is denied
    X-->>A: outcome: blocked
    A-->>L: "REFUSED BY POLICY ... do not retry"
    L-->>A: plain-English explanation for you
    A-->>UI: SSE: tokens + sandbox event
```

---

## 3. Onboarding

The launch screen checks the host and the model, then sends a machine that has
never been set up to `/onboard` instead of straight into the app. Five steps.

```mermaid
flowchart LR
    L["/<br/>launch.html<br/>host + model check"] --> Q{"profile.json<br/>exists?"}
    Q -->|no| O["/onboard"]
    Q -->|yes| APP["/app"]

    O --> S1["1. your name"]
    S1 --> S2["2. name the BASE agent<br/>+ pick its face"]
    S2 --> S3["3. pick persona agents<br/>+ a face each<br/>(5 faces, 5 agents)"]
    S3 --> S4["4. connectors<br/>gmail / reddit / github<br/>local dummy accounts"]
    S4 --> S5["5. a starting policy for each,<br/>with what it REFUSES<br/>spelled out"]
    S5 --> W["POST /api/profile"]

    W --> F1["profile.json"]
    W --> F2["policies/base.json<br/>policies/health.json<br/>policies/finance.json<br/>policies/computer-assist.json<br/>policies/coding.json"]
    W --> F3["vault/ seeded<br/>with each agent's data"]
    F1 --> APP
```

Step 5 is the point of the whole thing: you choose what each agent may touch
**before** any of them has done anything. The base agent comes first on that
screen, because it is the only one with reach across all four folders.

A preset cannot grant anything the Policy tab could not - it is a starting
point, not a privileged one. Re-running setup never overwrites a policy file
or a vault folder that already exists.

---

## 4. What an agent actually is

Everything that used to be hardcoded hangs off one record in
`core/agents.py`. Switching agent swaps all three arms at once.

There are two kinds. Four **personas**, each sealed in its own vault folder,
and one **base agent** that collects what they produce.

```mermaid
flowchart TB
    R["core/agents.py<br/>REGISTRY"]
    R --> B["base<br/>role: base"]
    R --> H["health"]
    R --> FI["finance"]
    R --> CA["computer-assist<br/>(PC Assist)"]
    R --> CO["coding"]

    B --> BP["PROMPT<br/>always on; collects, never<br/>holds data of its own"]
    B --> BT["TOOLS<br/>sync_vaults, list_messages,<br/>read_message, search_mail,<br/>list_events, draft_reply"]
    B --> BF["POLICY<br/>policies/base.json<br/>reads every invites + outbox,<br/>NO data folder"]

    H --> HP["PROMPT<br/>vitals, labs, medications"]
    H --> HT["TOOLS<br/>list_records, read_record,<br/>search_records,<br/>create_invite, draft_message"]
    H --> HF["POLICY<br/>policies/health.json<br/>reads vault/health/records"]
```

The four personas share one set of hands. They differ in what their policy
lets those hands reach, which is the only difference worth having.

Two separate gates, and conflating them makes refusals impossible to explain:

- **Does this agent have hands of this shape at all?** The health agent never
  sees `list_processes`. It is not switched off; it is not part of what the
  health agent is.
- **Is this particular hand switched off right now?** That is `policy.tools`,
  a host-side gate, and the weakest control on the screen.

### The produce-and-collect loop

A persona cannot put anything on a calendar. It writes an invitation into its
own `invites/` folder and stops. The base agent picks it up.

```mermaid
flowchart LR
    U["you ask Health for<br/>an appointment invite"] --> HA["health agent<br/>policies/health.json"]
    HA -->|"ONE sandbox"| INV["vault/health/invites/*.json<br/>source: health"]

    FP["basecamp thread<br/>fingerprint changed?"] -.->|"every 20s, host-side stat"| INV
    FP -->|"ONE sandbox<br/>policies/base.json"| SYNC["sync_vaults"]
    SYNC --> CAL["mailbox/calendar/2026-10-22.json<br/>event tagged 'from health'"]
    CAL --> BUB["the bubble<br/>counter + 1"]
```

Take `${vault}\health\invites` out of the base agent's `paths.read` and the
chain breaks at `sync_vaults`, with Windows' own refusal text on screen. The
other three personas keep arriving. Put it back and the next check picks it up,
with no restart - the fingerprint includes the policy file mtime for exactly
this reason.

---

## 5. Where the data comes from

Two trees, both files on disk, both made on first run. `mailbox/` is the base
agent's global view. `vault/` is the four personas' sealed worlds.

The mailbox is a real Gmail account made for the workshop, snapshotted once by
the presenter and served as files. The vault is seeded from `core/vault.py`,
with the three handles you typed during setup substituted in.
**No participant logs in to anything and no credential ships in the repo.**

```mermaid
flowchart LR
    G["Gmail<br/>workshop account"] -->|"presenter, once,<br/>read-only IMAP"| SNAP["workshop/mail-snapshot.py"]
    SNAP --> SEED["workshop/mailbox-seed.json<br/>IS committed"]
    SEED -->|"first run, per machine"| MB["mailbox/<br/>NOT committed"]

    MB --> PANE["bubble + mailbox pane<br/>read on the HOST"]
    MB --> TOOLS["base agent tools<br/>read through the SANDBOX"]

    TOOLS --> Q{"policies/base.json<br/>grants this folder?"}
    Q -->|yes| OK["the message"]
    Q -->|no| NO["REFUSED BY POLICY"]
```

The vault is laid down the same way, one folder per persona:

```mermaid
flowchart LR
    SEEDV["core/vault.py SEED<br/>+ your gmail / reddit / github handles"]
    SEEDV -->|"first run, per machine"| V["vault/<br/>NOT committed"]

    V --> VH["health/records<br/>finance/ledger<br/>coding/github<br/>pc-assist/reddit"]
    V --> VO["*/invites<br/>*/outbox"]

    VH -->|"its OWN agent only"| P1["read"]
    VO -->|"its own agent writes"| P2["write"]
    VO -->|"the base agent reads"| P3["sync_vaults"]
```

A persona's data folder is readable by that persona and by nobody else. Its
two outgoing folders are the only things the base agent can see.

**The pane and the agent read the same files by different routes, and that is
deliberate.** The pane says there are messages in your private folder; the
agent is refused them. That gap on screen is the policy working, not a bug.
The bubble's counter is the other half of the same idea: the lists are a host
read, but the counter only moves when a real sandboxed sync was allowed to
move it.

Why files and not a live connection - all three reasons matter:

| | |
|---|---|
| **The sandbox cannot reach the network for this** | `hostLoopback` is only grantable on BaseContainer. `verify.py` measures that a contained process cannot reach loopback on the tiers most machines get, so a mail server - local or proxied - is unreachable no matter which knob you flip. No working state to flip *into*. |
| **Shared live IMAP breaks at room scale** | Gmail caps simultaneous connections per account at around fifteen and flags many IPs at once. One person archiving would change everyone's inbox. |
| **A live credential fights the injection demo** | There is a planted phishing email in the seed. Putting a Google app password where the agent might read it is the one thing that demo exists to punish. |

---

## 6. The three kinds of "no"

They look different on screen because they mean very different things.

```mermaid
flowchart TB
    T["the model asks for a tool"] --> G1{"switched on in<br/>policy.tools?"}
    G1 -->|no| H["HOST GATE - blue<br/>never reached a sandbox<br/>the WEAKEST control"]
    G1 -->|yes| B["compile MXCConfiguration"]

    B --> G2{"wxc-exec accepts<br/>the config?"}
    G2 -->|no| R["REFUSED TO START - amber<br/>names the offending field"]
    G2 -->|yes| RUN["one-shot container spawns,<br/>the command really runs"]

    RUN --> G3{"Windows allows<br/>the access?"}
    G3 -->|no| BL["BLOCKED BY POLICY - red<br/>THIS is the real one"]
    G3 -->|yes| OK["ok, plus stdout"]
```

A host gate is the agent's own harness declining, and a harness is exactly the
layer the whole exercise argues you cannot trust. It is blue for a reason.

---

## 7. The file map

```mermaid
flowchart TB
    subgraph CORE["core/"]
        A1["agents.py<br/>agent registry - prompts, tool<br/>sets, policy files, presets"]
        A2["profile.py<br/>who is sitting here"]
        A3["app.py<br/>shared state, per-agent policy<br/>load/save, working_dir"]
        A4["agent.py<br/>the loop, one tool call"]
        A5["tools.py<br/>the hands - one command each"]
        A6["policy.py<br/>policy.json -> MXCConfiguration"]
        A7["mxc.py<br/>spawns wxc-exec, classifies outcomes"]
        A8["mailbox.py<br/>seeds and reads the mailbox"]
        A12["vault.py<br/>the four sealed persona folders"]
        A13["basecamp.py<br/>the always-on base agent thread"]
        A9["server.py<br/>routes"]
        A10["lemonade.py<br/>the model client"]
        A11["verify.py<br/>what actually works here"]
    end

    subgraph UIDIR["ui/"]
        U1["launch.html - host + model check"]
        U2["onboard.html - the five steps"]
        U3["index.html + app.js - the app"]
        U4["critters.js - the five faces"]
        U5["theme.js - the three themes"]
        U6["phase1.html - terminal walkthrough"]
    end

    subgraph GEN["written at runtime, NOT in git"]
        G1["profile.json"]
        G2["policies/*.json"]
        G3["mailbox/"]
        G4["vault/"]
    end

    A1 --> A4
    A2 --> A3
    A3 --> A4
    A6 --> A4
    A5 --> A4
    A4 --> A7
    A8 --> A9
    A12 --> A13
    A13 --> A7
    U2 --> G1
    U2 --> G2
    A8 --> G3
    A12 --> G4
```

A fuller walkthrough of every file, with the code quoted and explained, is in
[CODE-TOUR.md](CODE-TOUR.md).

---

## 8. Measured limits on this hardware

From `verify.py`, not from anybody's expectations. Re-run it on your own box
rather than trusting this list.

| | |
|---|---|
| Tier | AppContainer + BFS (tier 2) |
| Network dialect | modern |
| `dir` through cmd | **refused** - enumeration asks for an access an AppContainer read grant does not carry. `Get-ChildItem` is fine, which is why the mail and record tools are PowerShell. |
| Delete / move a file | **refused** - a read-write grant carries create and write but not DELETE, so `move_file` cannot work here at all. The base agent archives by copy-and-tombstone, and `sync_vaults` dedupes by `sourceId` rather than clearing a folder it cannot clear. The pane says so rather than hiding it. |
| Loopback from inside | refused, as designed - this is why the model stays on the host |
| PowerShell in a sandbox | works now; it did not on the first run |

If a refusal does not happen when you said it would, say so out loud and go
look at why. A workshop about containment that papers over a failed
containment check has taught the room the opposite of the intended lesson.
