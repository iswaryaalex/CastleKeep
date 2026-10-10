# CastleKeep: a tour of the code

## About this document

This document explains all of CastleKeep. It starts at the first line that
runs. It ends at the last pixel on the screen.

Read it with the repository open. Each part names the file and the function
that does the work. You can go to that code and read it directly.

### Who this document is for

You are a developer. You can read Python. You do not know this codebase yet.
You do not know MXC. You want to change this code with confidence.

### The language rules

This document uses ASD-STE100 Simplified Technical English. These rules apply:

- Sentences are short. A descriptive sentence has 25 words or fewer.
- The voice is active. "The loop calls the tool." Not "The tool is called."
- Verb tenses are simple. The document uses *is*, *was*, and *will be*.
- One word has one meaning. A *run* is always one sandbox invocation.
- Paragraphs are short. A paragraph has 6 sentences or fewer.
- Technical names keep their exact spelling. `compile_config` is a technical
  name, not two words.

### One correction before you start

You asked about LangGraph. **CastleKeep does not use LangGraph.** It does not
use LangChain. It does not use any agent framework.

CastleKeep has **no third-party packages at all**. It uses only the Python
standard library. You can prove this:

```bash
grep -rhoE "^\s*(import|from)\s+[a-zA-Z_][a-zA-Z0-9_]*" --include="*.py" . | sort -u
```

The result contains only standard library names. There is no
`requirements.txt` and no `pyproject.toml`.

[Part 6](#part-6--the-agent-loop) explains what does the work that you expect
LangGraph to do. It also maps each LangGraph idea to the CastleKeep part that
replaces it.

The reason for this choice is in [run.py:10](run.py#L10):

```python
Python 3.9+. No packages to install - this is stdlib only on purpose, so the
whole thing survives a conference wifi network and a locked-down laptop.
```

---

## Table of contents

1. [The one idea](#part-1--the-one-idea)
2. [The parts list](#part-2--the-parts-list)
3. [The program start](#part-3--the-program-start)
4. [MXC: the sandbox](#part-4--mxc-the-sandbox)
5. [The policy](#part-5--the-policy)
6. [The agent loop](#part-6--the-agent-loop)
7. [The five agents](#part-7--the-five-agents)
8. [One user journey, end to end](#part-8--one-user-journey-end-to-end)
9. [The web server](#part-9--the-web-server)
10. [The browser code](#part-10--the-browser-code)
11. [The proof: verify.py](#part-11--the-proof-verifypy)
12. [Measured limits](#part-12--measured-limits-on-this-hardware)
13. [How to extend the code](#part-13--how-to-extend-the-code)

---

## Part 1 — The one idea

CastleKeep is a local AI assistant. You control what it can touch. A Microsoft
sandbox called MXC enforces that control.

### The trust boundary

Look at this line. It is the most important line in the project.

> CastleKeep contains what the agent **does**, not what the agent **is**.

It is in the header of [core/agent.py:11](core/agent.py#L11).

Two things run on your computer, outside any sandbox:

| Part | Where it runs | Why |
|---|---|---|
| The model (Lemonade Server) | Host, unsandboxed | The model only thinks. It touches nothing. |
| The agent loop (`core/agent.py`) | Host, unsandboxed | It is the supervisor. It must survive each sandbox. |
| Each tool call | Inside a new sandbox | This is the part that touches your files. |

The model can decide to do something bad. The sandbox stops it. The boundary
is outside the model, so a model mistake cannot cross it.

### Why each tool call gets a new sandbox

MXC has no long-running daemon shape on Windows ProcessContainer. The
contained process must exit inside its timeout. So "an agent that lives inside
a sandbox" does not exist.

What exists is this pattern:

```
host: agent loop  ──► build a config ──► one sandbox ──► run one command ──► sandbox is destroyed
         ▲                                                                        │
         └──────────────────────── result comes back ─────────────────────────────┘
```

This gives a property that is very valuable in a workshop. The policy is read
from disk **for each tool call**. You can edit the policy while the program
runs. The next tool call obeys the new policy. There is no restart and no
reload.

---

## Part 2 — The parts list

### Python files

| File | Purpose |
|---|---|
| [run.py](run.py) | The entry point. Starts the App and the web server. |
| [bootstrap.py](bootstrap.py) | Deletes stale `.pyc` files before any import. |
| [core/app.py](core/app.py) | Shared state. One `App` object for each process. |
| [core/mxc.py](core/mxc.py) | The only file that talks to the MXC binary. |
| [core/policy.py](core/policy.py) | Turns `policy.json` into an MXC configuration. |
| [core/agent.py](core/agent.py) | The agent loop. Model in, tool calls out. |
| [core/lemonade.py](core/lemonade.py) | Talks to the local model server. |
| [core/tools.py](core/tools.py) | The tool catalogue. Each tool is one command. |
| [core/agents.py](core/agents.py) | The agent registry. Prompts, tools, policies. |
| [core/vault.py](core/vault.py) | The four sealed persona folders and their data. |
| [core/basecamp.py](core/basecamp.py) | The always-on base agent thread. |
| [core/mailbox.py](core/mailbox.py) | The global mail and calendar view. |
| [core/profile.py](core/profile.py) | Who sits here. Names, faces, accounts, theme. |
| [core/server.py](core/server.py) | A small HTTP server. Standard library only. |
| [core/verify.py](core/verify.py) | Proves the claims on your own machine. |

### Browser files

| File | Purpose |
|---|---|
| [ui/launch.html](ui/launch.html) | The front door. Checks the host and the model. |
| [ui/onboard.html](ui/onboard.html) | Setup. Five steps. |
| [ui/index.html](ui/index.html) | The application. Five tabs. |
| [ui/app.js](ui/app.js) | All application behaviour. |
| [ui/critters.js](ui/critters.js) | The five animal faces, as pixel art. |
| [ui/theme.js](ui/theme.js) | The three themes. |
| [ui/dragon.js](ui/dragon.js) | The CastleKeep mark in the title bar. |
| [ui/style.css](ui/style.css) | All styles. Themes are token tables. |
| [ui/phase1.html](ui/phase1.html) | A terminal walkthrough of MXC alone. |
| [ui/architecture.html](ui/architecture.html) | Diagrams of the system. |

### Data folders

| Folder | In git? | Content |
|---|---|---|
| `bin/` | Yes | The MXC executables for x64 and arm64. |
| `policies/` | No | One policy file for each agent. You edit these. |
| `vault/` | No | The four persona worlds. Made on first run. |
| `mailbox/` | No | The global mail and calendar. Made on first run. |
| `workspace/` | Yes | A scratch folder for the PC Assist agent. |
| `receipts/` | No | Denial receipts, if the host supports them. |

---

## Part 3 — The program start

### Step 1: bootstrap.py deletes the bytecode cache

[run.py:25](run.py#L25) runs this before it imports `core`:

```python
import bootstrap
bootstrap.purge(HERE)   # never import stale .pyc - see bootstrap.py
```

Python decides that a cached `.pyc` file is good. It compares the source file
mtime and size. That test is correct on a local disk. It is wrong for this
project.

This folder moves between machines. People copy it to USB sticks. They unpack
it from zip files. They edit it through file shares. Any of these actions can
leave a source file with new content but old metadata. Python then runs
yesterday's code.

[bootstrap.py:27](bootstrap.py#L27) sets `sys.dont_write_bytecode = True` and
deletes every `__pycache__` folder. A full recompile costs a few hundred
milliseconds. One stale import costs an hour.

### Step 2: the App object is built

[core/app.py:22](core/app.py#L22) `App.__init__` does the work. It is pure
setup. It does not touch the network and it does not spawn a sandbox.

The order matters:

```python
self.cfg = _load_json(self.config_path)          # config.json
self.policy = policy_mod.load(self.policy_path)  # the root policy.json
...
mailbox_mod.ensure(self.mailbox, self.project_dir)   # make mailbox/ if absent
self.vault = ...                                     # vault/ path
self.profile = profile_mod.load(self.project_dir)    # profile.json, or None
vault_mod.ensure(self.vault, self.project_dir, self.connectors())
self.basecamp = basecamp_mod.Basecamp(self)          # idle until start()
```

`ensure` never overwrites. A participant who has used the application for ten
minutes keeps all their work after a restart.

### Step 3: App.start() measures the machine

[core/app.py:317](core/app.py#L317) `App.start()` is the first function that
touches the outside world. It does four things in order:

1. It re-reads `config.json`, in case you edited it.
2. It runs `wxc-exec --probe`. This asks MXC what this host can enforce.
3. It negotiates the network dialect. [Part 5](#the-network-dialect) explains
   this.
4. It checks Lemonade, then warms the model in a background thread.

Then it starts the base agent thread:

```python
# Last, because it spawns sandboxes and there is no point doing that
# before we know whether this host can build one.
self.basecamp.start()
```

### Step 4: the web server starts

[core/server.py:423](core/server.py#L423) `make_server` binds a
`ThreadingHTTPServer` to `127.0.0.1`. There is no authentication. There is no
remote access either, so there is nothing to authenticate.

The server does check the `Origin` header. See
[core/server.py:52](core/server.py#L52). This stops a web page in another tab
from driving your agent.

### Step 5: the browser opens the launch screen

The browser opens `http://127.0.0.1:7701/`. The route table at
[core/server.py:30](core/server.py#L30) maps `/` to `launch.html`, not to the
application:

```python
PAGES = {
    "/": "/launch.html",
    "/app": "/index.html",
    "/launch": "/launch.html",
    "/onboard": "/onboard.html",
}
```

The launch screen is the front door for a reason. It is where the host check
and the model check happen. If you arrive at the application first, you arrive
before the application can answer.

---

## Part 4 — MXC: the sandbox

This is the part you do not know. Read this part slowly.

### What MXC is

MXC is a Microsoft sandbox technology for Windows. CastleKeep uses one
executable from it: `wxc-exec.exe`. The copy in `bin/x64/` travels with this
repository.

`wxc-exec.exe` does one job. You give it a JSON configuration. It builds a
container, runs one command inside that container, and destroys the container.

It is not a service. It is not a daemon. It is a one-shot process.

### The command line contract

The full contract is at the top of [core/mxc.py:4](core/mxc.py#L4). CastleKeep
uses only three options:

| Option | What CastleKeep uses it for |
|---|---|
| `--probe` | Ask the host what it can enforce. Prints JSON. |
| `--dry-run` | Parse and validate a config. Do not run anything. |
| `--config-base64 <b64>` | The real run. The config as base64 JSON. |

CastleKeep never uses `--audit`. The header says why:

```python
CastleKeep uses --probe, --dry-run and --config-base64. It never uses --audit,
because --audit turns the restrictions OFF for the run, and a workshop about
containment should not quietly run uncontained.
```

### Where the binary comes from

[core/mxc.py:59](core/mxc.py#L59) `resolve_binary` looks in this order:

1. `mxc.exePath` in `config.json`, if you set it.
2. `mxc.binDir` in `config.json`. The shipped value is `bin`.
3. The `MXC_BIN_DIR` environment variable.
4. `<project>/bin/<arch>/wxc-exec.exe`.
5. Two `node_modules` locations, for people with the MXC SDK installed.
6. `%LOCALAPPDATA%\Microsoft\MXC\bin`.
7. The system `PATH`.

If every location fails, the function raises `BinaryNotFound`. The message
lists every path that it tried. The docstring explains the choice:

```python
"""Find the executor. Returns an absolute path, or raises BinaryNotFound
with every place that was looked at, because a silent miss here is the
single most annoying way for this project to fail."""
```

### The three tiers

Windows gives different containment strength on different machines. MXC calls
these tiers. `--probe` reports which tier your host gives you.

| Tier | Name | Strength |
|---|---|---|
| 1 | BaseContainer | Kernel-enforced. The strongest. |
| 2 | AppContainer + BFS | Filesystem virtualisation. Most machines get this. |
| 3 | AppContainer + DACL | Changes ACEs on your real paths. |

The tier decides which policy fields work. This is the most surprising part of
MXC, and [the next section](#from-probe-to-capabilities) is about it.

### From probe to capabilities

[core/mxc.py:316](core/mxc.py#L316) `Mxc.probe()` runs `wxc-exec --probe` and
parses the JSON. Then it calls `derive_capabilities`.

[core/mxc.py:442](core/mxc.py#L442) `derive_capabilities` turns the probe
result into a plain answer for each policy knob. The answer has two fields:

```python
def cap(ok, why=""):
    return {"supported": bool(ok), "why": why}
```

`supported` is a boolean. `why` is the text that the user interface shows when
the answer is no.

The important case is `denyPaths`. Read the docstring:

```python
"""...The important one, and the one that surprises people: at the
AppContainer tier `filesystem.deniedPaths` is rejected outright - the binary
says "Paths are denied by default unless granted via readwritePaths or
readonlyPaths." It does not quietly drop the field. It refuses the run."""
```

This is the key idea of MXC. **Everything is denied by default.** You do not
write deny rules. You write grant rules. A deny list is not a smaller grant
list; on tier 2 it is an error that stops the run.

Here is the full capability table that `derive_capabilities` produces:

| Capability | Needs | Effect when absent |
|---|---|---|
| `readPaths` | Always available | — |
| `writePaths` | Always available | — |
| `denyPaths` | BaseContainer | The field is left out of the config. |
| `outboundToggle` | Always available | — |
| `perHostRules` | Never on Windows | Outbound is all or nothing. |
| `hostLoopback` | BaseContainer | The sandbox cannot reach `127.0.0.1`. |
| `leastPrivilege` | BaseContainer | Asking for it forces a weaker tier. |
| `captureDenials` | BaseContainer | No denial receipts. |
| `daclMutation` | AppContainer tiers | — |

The `hostLoopback` entry explains a design choice:

```python
"hostLoopback": cap(
    base,
    "ingress.hostLoopback='allow' is rejected by the AppContainer fallback. "
    "This is exactly why CastleKeep keeps the model on the host: nothing "
    "inside the sandbox ever needs to reach 127.0.0.1.",
),
```

A sandboxed process cannot reach Lemonade on loopback. So the model must stay
on the host. This is not a shortcut. It is the only arrangement that works.

### One sandbox run

[core/mxc.py:364](core/mxc.py#L364) `Mxc.execute` is the function that spawns a
sandbox. The steps are short:

```python
payload = json.dumps(mxc_config, separators=(",", ":"))
b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")

argv = [self.exe, "--config-base64", b64]
if dry_run:
    argv.append("--dry-run")
...
r = subprocess.run(argv, capture_output=True, text=True, timeout=wall, errors="replace")
```

The configuration goes as base64. This removes every quoting problem between
Python, the shell, and the binary.

The wall-clock timeout is the policy timeout plus 30 seconds:

```python
wall = timeout or (((mxc_config.get("process") or {}).get("timeout") or 30000)
                   / 1000.0 + 30)
```

The policy timeout stops the contained process. The wall timeout stops
`wxc-exec` itself. The second one is a safety net for the first.

### The three kinds of "no"

[core/mxc.py:169](core/mxc.py#L169) `_classify` reads the exit code, stdout,
and stderr. It decides what happened. This function is the heart of the
demonstration.

```python
"""Work out what actually happened. Three distinct outcomes, and keeping
them distinct is the difference between a demo that teaches something and
a demo that just prints red text.

  refused-to-start : MXC would not build the sandbox at all (reject,
                     don't degrade). The policy asked for something this
                     host cannot enforce.
  blocked          : the sandbox was built, the command ran, and the
                     policy stopped it from touching something.
  ok / failed      : the command ran and succeeded, or failed on its own
                     merits.
"""
```

There is a fourth outcome that MXC never produces. CastleKeep produces it
itself:

| Outcome | Who refused | Where it is set |
|---|---|---|
| `host-gate` | CastleKeep, on the host | [core/agent.py:168](core/agent.py#L168) |
| `refused-to-start` | `wxc-exec`, before the command | `_classify` step 1 and 2 |
| `blocked` | Windows, during the command | `_classify` step 3 |
| `failed` | The command itself | `_classify` fallback |

`host-gate` means that a tool is switched off in `policy.tools`. The request
never reached a sandbox. The user interface says so, because "CastleKeep
stopped this" and "Windows stopped this" are different claims.

### How a block is detected

`_classify` step 3 searches the output for text patterns. The patterns are at
[core/mxc.py:137](core/mxc.py#L137) in `_DENIED_INSIDE`.

The first entry carries a long comment. Read it. It describes a real bug and
its cost:

```python
# Two shapes, and missing the second one is expensive. cmd.exe says
# "Access is denied." PowerShell says "Access to the path 'C:\\x' is
# denied." Matching only the first classified every PowerShell refusal as
# a plain command failure - so a real containment event was reported to
# the room as a broken tool, and the model was told "the command failed"
# instead of "REFUSED BY POLICY, do not retry". That is the one mistake
# this file cannot afford to make.
```

The lesson applies to the whole file. A wrong classification does not just
print the wrong colour. It tells the model the wrong thing, and the model then
retries an action that will always fail.

---

## Part 5 — The policy

### The policy file

`policy.json` and each file in `policies/` have the same shape. The defaults
are at [core/policy.py:104](core/policy.py#L104):

```python
DEFAULTS = {
    "name": "policy",
    "containment": "processcontainer",
    "paths": {"read": [], "write": [], "deny": []},
    "network": {"outbound": "deny", "localNetwork": False},
    "ui": {"allowWindows": False, "clipboard": "none", "allowInputInjection": False},
    "limits": {"timeoutMs": 30000},
    "advanced": {...},
    "tools": {},
}
```

[core/policy.py:123](core/policy.py#L123) `normalise` merges your file over
these defaults. After `normalise`, no other function must check for a missing
section.

### Path variables

[core/policy.py:36](core/policy.py#L36) `path_context` builds the variable
table:

| Variable | Points to |
|---|---|
| `${project}` | The repository folder. |
| `${workspace}` | `workspace/`. The PC Assist scratch folder. |
| `${mailbox}` | `mailbox/`. The base agent's global view. |
| `${vault}` | `vault/`. The root of the four persona worlds. |
| `${home}` | `%USERPROFILE%`. |
| `${windir}`, `${system32}` | The Windows folders. |
| `${temp}`, `${programfiles}`, `${localappdata}`, `${systemdrive}` | As named. |

`${system32}` appears in every policy in this project. The reason is at
[core/agents.py:170](core/agents.py#L170):

```python
# ${system32} is in every single read list. It is where cmd.exe, findstr.exe,
# certutil.exe and curl.exe themselves live - take it away and the sandbox
# cannot start the tool at all, which teaches the wrong lesson very loudly.
```

[core/policy.py:66](core/policy.py#L66) `expand` replaces the variables. An
unknown variable raises `PolicyError` and names the known ones.

There is deliberately **no** `${vault_self}` variable. The comment at
[core/policy.py:48](core/policy.py#L48) explains:

```python
# There is deliberately no ${vault_self}: a variable whose meaning depends
# on which agent is asking would make a policy file impossible to read on
# its own, and lint() and compile_config() would both have to learn about
# agents to resolve it.
```

A policy file means the same thing to every reader. This matters more than the
small amount of repetition that it costs.

### The linter

[core/policy.py:140](core/policy.py#L140) `lint` finds problems before MXC has
to. It returns a list of `{level, field, message}`. The level is `error`,
`warn`, or `info`.

An `error` means the run will certainly fail. The server refuses to save a
policy that has an error. See [core/server.py:263](core/server.py#L263):

```python
lint = policy_mod.lint(incoming, app.path_ctx(), app.caps)
if any(n["level"] == "error" for n in lint):
    return self._json({"saved": False, "lint": lint}, 400)
```

A `warn` means the run will probably fail on this host. `lint` produces
warnings from the capability table, so the message is the host's own reason.

### The compiler

[core/policy.py:213](core/policy.py#L213) `compile_config` is the translation
layer. It turns one policy into one MXC configuration.

It returns two values:

```python
"""Build one MXCConfiguration. Returns (config, notes).

`notes` records every decision that was not a straight pass-through, so
the UI can show "you asked for X, here is what happened to X" instead of
the config silently differing from the policy.
"""
```

The `notes` list is the honesty mechanism. A field that is dropped always
produces a note.

Here is the full translation table:

| Policy field | MXC field | Note |
|---|---|---|
| `paths.read` | `filesystem.readonlyPaths` | Expanded to absolute paths. |
| `paths.write` | `filesystem.readwritePaths` | — |
| `paths.deny` | `filesystem.deniedPaths` | Dropped if the tier refuses it. |
| `network.outbound` | `network.egress.default` | `allow` or `deny`. |
| `network.localNetwork` | `network.ingress.hostLoopback` | Dropped if the tier refuses it. |
| `ui.allowWindows` | `ui.disable` | The sense is inverted. |
| `ui.clipboard` | `ui.clipboard` | — |
| `ui.allowInputInjection` | `ui.injection` | — |
| `limits.timeoutMs` | `process.timeout` | — |
| `advanced.learningMode` | `processContainer.learningMode` | — |
| `advanced.leastPrivilege` | `processContainer.leastPrivilege` | Dropped if the tier refuses it. |
| `advanced.captureDenials` | `processContainer.captureDenials` | Needs a receipts folder. |
| `advanced.allowDaclMutation` | `fallback.allowDaclMutation` | — |
| `tools` | *nothing* | A host-side gate. It never reaches MXC. |

Two details are worth your attention.

**A read-write grant does not also need a read grant.**

```python
ro = [x for x in ro if x.lower() not in {y.lower() for y in rw}]
```

Sending both creates a confusing precedence question. The compiler removes the
duplicate.

**The `decide` helper is where a capability becomes a decision.**

```python
def decide(key, field, requested):
    """Returns True if the field should go on the wire."""
    if not requested:
        return False
    if supported(key):
        return True
    if send_anyway:
        notes.append({... "Sent anyway so you can see MXC refuse it. " ...})
        return True
    notes.append({... "Left out of this run - this host cannot enforce it. " ...})
    return False
```

The `sendUnsupportedAnyway` flag in `advanced` is a teaching tool. It sends a
field that this host cannot enforce, so that the room can watch MXC refuse it.

### The network dialect

`wxc-exec` has changed its network schema between versions. CastleKeep does
not guess which one your binary wants. It asks.

[core/policy.py:366](core/policy.py#L366) `negotiate_dialect` runs a
`--dry-run` for each dialect:

```python
for dialect in ("modern", "legacy"):
    cfg, _ = compile_config(policy, ctx, probe_command, dialect=dialect)
    run = mxc.execute(cfg, label="negotiate network dialect (%s)" % dialect,
                      dry_run=True, timeout=90)
```

A dry run parses and validates, then exits. It spawns nothing. So this check is
cheap and safe.

The two shapes:

```python
# modern
{"egress": {"default": "deny"}, "ingress": {"default": "deny", "hostLoopback": "deny"}}

# legacy
{"defaultPolicy": "block", "allowLocalNetwork": False}
```

If both dialects fail, the dialect is `none`. Then `compile_config` sends no
network block at all. It also adds an `error` note:

```python
"message": "You asked for outbound DENY, but this host rejected "
           "every network dialect wxc-exec offers, so the run "
           "carries no network policy at all. The sandbox is "
           "most likely on the network. Do not claim the network "
           "is contained until the Run tab shows otherwise.",
```

This is the project's attitude in one message. It would be easy to print
"Outbound: denied" from the policy file. That would be a lie. The code reports
what is enforced, not what was asked for.

---

## Part 6 — The agent loop

### What replaces LangGraph

You expected a graph framework. There is none. This table maps each LangGraph
idea to the CastleKeep code that does the same job:

| LangGraph idea | CastleKeep equivalent | File |
|---|---|---|
| `StateGraph` | A `while True` loop | [core/agent.py:234](core/agent.py#L234) |
| State object | Three local variables: `messages`, `used`, `final_text` | `Agent.turn` |
| Node | One pass through the loop body | `Agent.turn` |
| Conditional edge | `if not calls: break` | [core/agent.py:283](core/agent.py#L283) |
| `ToolNode` | `Agent.call_tool` | [core/agent.py:150](core/agent.py#L150) |
| Tool registry | `CATALOGUE`, a list of `Tool` objects | [core/tools.py:737](core/tools.py#L737) |
| `@tool` decorator | The `Tool` class and its `schema()` method | [core/tools.py:94](core/tools.py#L94) |
| Recursion limit | `agent.maxToolCallsPerTurn` in `config.json` | [core/agent.py:230](core/agent.py#L230) |
| Checkpointer / memory | The `history` array from the browser | [core/agent.py:227](core/agent.py#L227) |
| Subgraphs / multi-agent | The agent registry | [core/agents.py:400](core/agents.py#L400) |
| LLM provider adapter | `core/lemonade.py` | [core/lemonade.py:48](core/lemonade.py#L48) |
| Streaming callbacks | An `emit` function passed down the stack | `Agent.turn(..., emit)` |

The loop is about 70 lines. You can read all of it in two minutes. That is the
argument for writing it by hand.

### The turn loop

[core/agent.py:219](core/agent.py#L219) `Agent.turn` is the whole loop. Here is
the structure, with the detail removed:

```python
def turn(self, user_text, history, emit):
    pol = app.reload_policy(self.agent_id)            # 1. read the policy NOW
    schemas = tools_mod.schemas(pol, self.agent_id)   # 2. which tools exist

    system = agents_mod.system_prompt(self.agent_id, app.profile)
    messages = [{"role": "system",
                 "content": system + _policy_briefing(pol, app, self.agent_id)}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    while True:
        # 3. ask the model, stream the answer
        for ev in app.lemonade.chat(messages, tools=schemas or None, stream=True):
            ...collect tokens, reasoning, and tool calls...

        if not calls:
            break                                     # 4. no tools wanted: done

        if used + len(calls) > max_calls:
            break                                     # 5. budget spent

        messages.append({"role": "assistant", "tool_calls": [...]})

        for c in calls:                               # 6. run each tool
            result = self.call_tool(c["name"], c["arguments"], emit)
            messages.append({"role": "tool", "content": result})

    emit({"type": "done", "text": "\n\n".join(final_text)})
```

Four points deserve attention.

**Point 1. The policy is read at the start of the turn and again for each
tool call.** `Agent.call_tool` at [core/agent.py:157](core/agent.py#L157)
repeats the read:

```python
# Re-read the policy from disk for THIS call. Not cached, not
# inherited from the start of the turn. This is what makes an edit in
# the Policy tab land on the very next tool call.
pol = app.reload_policy(self.agent_id)
```

**Point 2. The tool budget is a hard stop.** `maxToolCallsPerTurn` defaults to
8. Without it, a confused model can loop until the browser gives up.

**Point 3. There is no memory store.** The browser holds the conversation and
sends it back as `history`. The server keeps nothing between requests. One
process can serve several agents, and each has its own history in the browser.

**Point 4. The loop handles a reasoning-only answer.** This was a real bug.
See [core/agent.py:274](core/agent.py#L274):

```python
# A reasoning model can finish a turn having written its entire
# answer into the reasoning channel and emitted no content at all.
# ...with nothing in `content` the chat window shows a blank reply
# underneath three successful sandbox runs, which reads as "the
# sandbox ate my answer".
if not text and not calls and reasoning:
    text = ("".join(reasoning).strip() + "\n\n_(The model wrote that in its "
            "reasoning channel rather than its reply. ...)_")
```

### Two things the loop tells the model

The loop injects two pieces of text that are not enforcement. They are advice.
They stop the model from wasting turns.

**The policy briefing.** [core/agent.py:323](core/agent.py#L323)
`_policy_briefing` appends the current grants to the system prompt:

```
The sandbox policy in force right now:
- Readable: C:\...\vault\health\records, C:\Windows\System32
- Writable: C:\...\vault\health\invites, C:\...\vault\health\outbox
- Outbound network: deny
- Tool call timeout: 30s
Anything not listed as readable is not readable. Do not guess at paths outside it.
```

The docstring is explicit about its status:

```python
"""Tell the model what it can and cannot reach, in the model's own terms.
This is not enforcement - MXC is enforcement - it just stops the model
wasting turns on things that will certainly be refused."""
```

**The grant diagnosis.** [core/agent.py:50](core/agent.py#L50)
`_grant_diagnosis` runs **after** MXC refuses. It explains which grant was
missing. The docstring states the problem it solves:

```python
"""Which grant was actually missing, in the policy's own words.

Windows will not tell you. PowerShell reports a refused write to
mailbox\\labels as "Access to the path 'C:\\Users' is denied", naming the
first directory it could not traverse rather than the one you asked for.
Handed that, a model confidently blames whichever path it can see in the
error and sends the user to change a rule that was never the problem.

This runs only after MXC has already refused. It explains the refusal; it
does not make it."""
```

Each `Tool` can declare a `paths` callback. The callback returns the paths that
this call will touch. `_grant_diagnosis` compares those paths with the policy
grants. It names the exact missing grant.

### Tool calls over the wire

[core/lemonade.py:182](core/lemonade.py#L182) `Lemonade.chat` handles two tool
formats. It negotiates between them at runtime.

**Native mode.** The request carries an OpenAI-style `tools` array. The
response carries `tool_calls`. This is the normal path.

**Prompted mode.** Some backends reject the `tools` parameter. Then
`chat` falls back. [core/lemonade.py:407](core/lemonade.py#L407)
`_inject_tool_prompt` adds a system message:

```
You can run tools. To run one, reply with ONLY this, and nothing else:

<tool_call>{"tool": "<name>", "arguments": {...}}</tool_call>
```

[core/lemonade.py:432](core/lemonade.py#L432) `_parse_prompted_calls` then
extracts the block from the text. Both paths yield the same event:

```python
{"type": "tool_calls", "calls": [{"id", "name", "arguments"}]}
```

The loop in `agent.py` cannot tell the difference. This is the point of the
design.

### How a tool becomes a command

[core/tools.py:94](core/tools.py#L94) `Tool` holds everything about one tool:

| Field | Purpose |
|---|---|
| `name`, `description`, `parameters` | What the model sees. |
| `build(args, ctx)` | A function that returns a command line string. |
| `shell` | `cmd`, `powershell`, or `curl`. For the user interface. |
| `needs` | Plain text. What grant this tool needs. |
| `danger` | If true, the tool is off unless the policy turns it on. |
| `agent` | One agent id, a tuple of ids, or `"*"`. |
| `paths(args, ctx)` | Which paths this call will touch. For diagnosis only. |
| `folder_enum` | If true, `schema()` builds a per-agent folder enum. |

The file header states two rules. Both are deliberate:

```python
  * Paths are NOT validated here. If the model asks to read a file it should
    not be able to read, the request goes straight through to MXC and MXC
    refuses it. Checking in the agent would be checking in exactly the layer
    the whole session argues you cannot trust.

  * Commands are built with explicit, fully quoted executable paths and, for
    anything with structure, PowerShell's -EncodedCommand.
```

[core/tools.py:50](core/tools.py#L50) `shell_ps` builds a PowerShell command.
It encodes the script as base64 UTF-16LE:

```python
script = "$ProgressPreference='SilentlyContinue';" + script
enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
return cmd_line(_q(PWSH % _windir()), "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc)
```

The `$ProgressPreference` line is not cosmetic. The docstring explains:

```python
"""...With a redirected stderr PowerShell serialises its streams as CLIXML,
and the first thing it emits is a progress record for "Preparing modules for
first use" - roughly 300 characters of XML before any real output. On a
refusal that XML is what lands in the run's detail field, and detail is
truncated at 400 characters on its way to the model."""
```

### Two gates, not one

A tool can be stopped in two places. Keep them separate in your mind.

| Gate | Question | Code |
|---|---|---|
| Registry | Does this agent have a hand of this shape? | `Tool.for_agent` |
| Policy | Is that hand switched off right now? | `policy["tools"][name]` |

[core/tools.py:943](core/tools.py#L943) `for_agent` states the difference:

```python
"""Two separate questions, and conflating them is how you end up unable to
explain a refusal: this one is "does this agent have hands of this shape
at all", and policy.tools is "is this particular hand switched off right
now". The health agent never sees list_processes; it is not off, it is
not part of what the health agent is."""
```

---

## Part 7 — The five agents

### The registry

[core/agents.py:400](core/agents.py#L400) `REGISTRY` is a list of five records.
Each record defines one agent completely:

| Field | Purpose |
|---|---|
| `id` | The stable key. Used in URLs and file names. |
| `role` | `base` or `persona`. |
| `label` | What people read. |
| `blurb`, `examples` | Text for the user interface. |
| `systemTemplate` | The prompt, with `{me}`, `{base}`, `{user}`, `{vault}`, `{data}`. |
| `tools` | The tool names this agent may ask for. |
| `policyFile` | `policies/<id>.json`. |
| `presets` | Three starting policies. |
| `vault` | Its folder name under `vault/`, or `None`. |
| `dataFolder` | What its own data folder is called. |
| `connector` | Which account seeds its data. |
| `critter` | The animal suggested during setup. |

The file header states the rule for adding behaviour:

```python
Nothing else in the codebase should hardcode an agent's identity - if you
find yourself adding an `if agent_id == "health"` somewhere, the field it
wants probably belongs here.
```

### The two kinds of agent

Four **personas**. Each is sealed in `vault/<name>/`:

| Agent | id | Folder | Reads | Writes |
|---|---|---|---|---|
| Health | `health` | `vault/health` | `records` | `invites`, `outbox` |
| Finance | `finance` | `vault/finance` | `ledger` | `invites`, `outbox` |
| PC Assist | `computer-assist` | `vault/pc-assist` | `reddit`, the device | `workspace`, `invites`, `outbox` |
| Coding | `coding` | `vault/coding` | `github` | `invites`, `outbox` |

> **Note.** The PC Assist id is `computer-assist`, but its folder is
> `pc-assist`. The id is older than the folder. A rename would orphan a policy
> file that somebody already edited. [core/tools.py:539](core/tools.py#L539)
> `_sources` returns both strings for this reason.

One **base agent**, id `base`. It has no vault. It reads every persona's
`invites` and `outbox`. It writes `mailbox/calendar` and `mailbox/drafts`.

The asymmetry is the whole exercise. The header at
[core/agents.py:30](core/agents.py#L30) says it:

```python
That asymmetry is the whole exercise. A persona produces; the base agent
collects; neither can see the other's private half.
```

### Why a persona cannot name another vault

A persona reaches its own folder through `ctx["agentVault"]`. The model never
supplies the root. [core/app.py:84](core/app.py#L84) `tool_ctx` injects it:

```python
rec = agents_mod.get(agent_id)
ctx["agentId"] = rec["id"]
ctx["agentData"] = rec.get("dataFolder") or ""
ctx["agentVault"] = (os.path.join(self.vault, rec["vault"])
                     if rec.get("vault") else "")
```

So the finance agent has no way to address `vault/health/records`. It has no
word for it. This is stronger than a refusal.

The enforced layer is still there. PC Assist has `read_file`, which takes a
free path. Point it at a health record and MXC blocks it. Both layers are real,
and [Part 11](#part-11--the-proof-verifypy) measures them.

### The prompt placeholders

[core/agents.py:568](core/agents.py#L568) `system_prompt` fills five
placeholders. Two of them are names, and they are not the same name:

```python
#   {me}   - what this particular agent is called ("Health", or the name the
#            participant typed for the base agent)
#   {base} - the always-on agent's name, which every persona has to be able to
#            refer to because handing work to it is the only way a persona
#            reaches the calendar
# One placeholder for both is how you end up with a health agent that thinks
# it is also the thing collecting its own invitations.
```

### The vault

[core/vault.py](core/vault.py) copies the pattern from `core/mailbox.py`:

| Function | Purpose |
|---|---|
| `layout()` | Reads the registry. Returns `{folder: data folder}`. |
| `ensure()` | Makes the tree. Seeds each data folder once. Never overwrites. |
| `items()` | Host-side read of one folder, for the user interface. |
| `summary()` | Counts and lists, for the Mission pane. |
| `fingerprint()` | A cheap stamp of all `invites` and `outbox` folders. |
| `pending_count()` | How many items wait across all personas. |

`fingerprint` deserves a note. Read its docstring at
[core/vault.py:177](core/vault.py#L177):

```python
"""...Comparing stamps is an optimisation and nothing more. It decides WHEN
to ask, never WHETHER the answer is allowed - that is still MXC's call, made
fresh against whatever policies\\base.json says at that instant."""
```

The seed data is a Python constant, `SEED`, at
[core/vault.py:238](core/vault.py#L238). An optional
`workshop/vault-seed.json` can replace it. This matches `core/mailbox.py`.

`_personalise` at [core/vault.py:90](core/vault.py#L90) substitutes the three
account names. It is shallow and string-only on purpose:

```python
"""Shallow and string-only on purpose. The seed is ours, the substitution
is cosmetic, and a recursive rewrite of arbitrary participant-supplied text
into arbitrary JSON is a much larger blast radius than 'the GitHub records
say your username'."""
```

### The always-on base agent

[core/basecamp.py](core/basecamp.py) runs a daemon thread. The loop is at
[core/basecamp.py:123](core/basecamp.py#L123):

```python
def _loop(self):
    while not self._stop.is_set():
        try:
            if self.enabled():
                self._tick()
        except Exception as e:
            self._set(state="error", reason=str(e))
        self._wake.wait(self.interval())
        self._wake.clear()
```

`_tick` at [core/basecamp.py:135](core/basecamp.py#L135) decides whether to
spawn a sandbox. There are two reasons to run:

```python
#   1. Something in the vault changed - an agent produced an invitation
#      or a draft and there is new work to collect.
#
#   2. The last run was not clean. A refusal is a state somebody is
#      actively trying to fix, and the fix is an edit to a policy file,
#      which changes nothing in the vault at all. Without this clause
#      you could grant the missing path, watch the bubble stay red, and
#      conclude the edit had not landed.
```

`_stamp` at [core/basecamp.py:156](core/basecamp.py#L156) therefore includes
the base policy file mtime, not only the vault fingerprint.

The sync itself is a real sandboxed tool call:

```python
agent = Agent(self.app, agents_mod.BASE_ID)
text = agent.call_tool("sync_vaults", {}, events.append)
```

The file header defends this choice at length. The short form:

```python
It would have been considerably easier to read the eight folders here, in
Python, on the host... But that pane is a window onto files, and this is an
agent doing work. If the merge ran on the host then policies\\base.json
would be a decoration.
```

### The merge command

[core/tools.py:563](core/tools.py#L563) `_b_sync_vaults` builds one PowerShell
script. The script does four things:

1. It proves that the calendar folder is readable, before it writes anything.
2. For each persona, it reads `invites` and merges each one into
   `mailbox/calendar/<date>.json`.
3. For each persona, it copies `outbox` items into `mailbox/drafts/`.
4. It prints one line of JSON: `{"invites":N,"drafts":N,"refused":[...]}`.

Three design points are in the docstring. Each solves a real failure:

```python
* Each persona is wrapped in its own try/catch and a failure is RECORDED,
  not raised. If it raised, taking one folder out of the base agent's
  paths.read would stop every other agent reaching the calendar too.

* Merging an invite is a read-modify-write of the day file, so the base
  agent needs calendar on BOTH paths.read and paths.write... So the script
  PROVES the calendar is enumerable before it writes a single byte.

* Nothing is gated on Test-Path. Test-Path answers "access denied" with
  $false, exactly as it answers "not there" - which would turn a refusal
  into a silent skip and let this tool report a clean zero while the
  policy was stopping it.
```

The third point is subtle and important. `Test-Path` cannot tell you the
difference between "absent" and "forbidden". The script uses
`Get-ChildItem -ErrorAction Stop` instead, and reports the Windows message.

Dedupe is by `sourceId`, not by deletion. This tier cannot delete files, so the
invite stays where it was. The script skips any event that already carries its
`sourceId`.

### The profile

[core/profile.py](core/profile.py) stores one small JSON file at the project
root. It holds the participant's answers:

| Field | Content |
|---|---|
| `userName` | What the agents call you. |
| `agentName` | What you called the base agent. |
| `subagents` | The agent ids that are on. `base` is always first. |
| `presets` | Which preset each agent started from. |
| `critters` | `{agentId: species}`. All five are distinct. |
| `connectors` | `{gmail, reddit, github}`. |
| `theme` | `parchment`, `moonlit`, or `sakura`. |
| `activeAgent` | Which agent the chat opens on. Never `base`. |

`normalise` at [core/profile.py:64](core/profile.py#L64) repairs bad input
instead of rejecting it. Two examples:

```python
# The base agent is not a choice. Four personas writing invitations into
# folders that nothing ever reads is not a smaller version of this app, it
# is a broken one - so it goes first and it always goes.
subs = [agents_mod.BASE_ID] + subs
```

```python
"""Duplicates are resolved rather than rejected. A profile where two agents
share a face is not dangerous, it is just confusing on screen - and the
repair (hand the later one whichever species is still going spare) is
obvious enough that stopping to ask about it would be worse."""
```

The connector rules reject bad values rather than correct them. The reason is
in [core/profile.py:130](core/profile.py#L130):

```python
"""The three dummy accounts. An entry that does not match its shape is
dropped, not corrected - an invented username seeded into somebody's
GitHub records would be a quiet lie about whose data they are looking at."""
```

The file header states the security position clearly:

```python
Nothing in here is a security boundary. A profile cannot grant access - it
records which policy file each subagent uses, and those files go through the
same lint and compile path as anything typed by hand.
```

---

## Part 8 — One user journey, end to end

This part follows one request through every layer. The request is:

> Create an invite for my next doctor appointment.

The Health agent is selected.

### Step 1. The browser sends the message

[ui/app.js](ui/app.js) `send()` opens a POST to `/api/chat`. The body holds
three fields:

```json
{"agent": "health", "message": "Create an invite...", "history": [...]}
```

The reply is a Server-Sent Events stream. `sse()` in `ui/app.js` reads it with
`fetch` and a `ReadableStream`. `EventSource` cannot be used, because it is
GET-only and this endpoint needs a body.

### Step 2. The server checks the model, then starts the loop

[core/server.py:324](core/server.py#L324) handles `/api/chat`. Before it starts
the agent, it checks the warm-up state:

```python
w = app.warmup_state()
if w.get("state") in ("no-model", "unreachable", "failed"):
    self._sse({"type": "error", "message": w.get("error") or ...})
```

Without this check, the user types a message and a stack trace about
`model_not_found` arrives in the chat window. That reads as "the application is
broken", not as "the model name in `config.json` is wrong".

Then:

```python
agent = Agent(app, body.get("agent"))
agent.turn(body.get("message") or "", body.get("history") or [], self._sse)
```

### Step 3. The loop builds the prompt

`Agent.turn` reads `policies/health.json` from disk. It builds the tool schemas
for the health agent only. It builds the system prompt:

- The persona text from `agents.REGISTRY`, with `{me}` set to `Health`.
- The policy briefing, which lists the real granted paths.

### Step 4. The model asks for `list_records`

The model replies with a tool call. The schema constrains the `folder`
argument. [core/tools.py:140](core/tools.py#L140) `Tool.schema` builds the enum
per agent:

```python
rec = agents_mod.get(agent_id)
folders = [f for f in (rec.get("dataFolder"), "invites", "outbox") if f]
props["folder"] = {"type": "string", "enum": folders, ...}
```

For the health agent, the enum is `["records", "invites", "outbox"]`.

The comment above it records why the enum exists:

```python
# Measured, not guessed: asked "what have my vitals done", a 2B
# model called list_records(folder="health") - the name of the
# VAULT, which is not a folder at all - got a failure, and retried
# the identical call.
```

### Step 5. `call_tool` runs one sandbox

[core/agent.py:150](core/agent.py#L150) `Agent.call_tool` does seven things:

```python
pol = app.reload_policy(self.agent_id)        # 1. fresh policy from disk
mine = {t.name: t for t in tools_mod.for_agent(self.agent_id)}
tool = mine.get(name)                         # 2. does this agent have it?

if not gate.get(name, not tool.danger):       # 3. host gate
    ...record a "host-gate" run and return...

command, tool = tools_mod.build_command(      # 4. build the command line
    name, arguments, app.tool_ctx(self.agent_id))

cfg, notes = app.compile_for(pol, command)    # 5. policy -> MXC config

run = app.mxc.execute(cfg, label=name, ...)   # 6. ONE SANDBOX
app.record_run(run)

if run["outcome"] in ("blocked", "failed"):   # 7. explain a refusal
    diagnosis = _grant_diagnosis(tool, arguments, pol, app.tool_ctx(...))
```

Step 5 calls `App.compile_for`, which calls `App.working_dir` first. That
function deserves a note. Read its docstring at
[core/app.py:275](core/app.py#L275):

```python
"""Where the contained process starts.

It has to be somewhere the policy actually grants. A sandbox launched
with a cwd it cannot reach fails with 'Access is denied' before the
command runs at all - which reads on screen as the tool being refused,
when what was really refused was the working directory. That is the
worst failure this app can produce, because it is a real refusal
reported against the wrong thing."""
```

So the working directory comes from the policy. It is never assumed.

### Step 6. The model reads the record

The model calls `read_record(id="appointments")`. The result is the raw JSON of
`vault/health/records/appointments.json`. It holds the real date, start time,
room, and the note about fasting.

### Step 7. The model writes the invite

The model calls `create_invite` with those values.
[core/tools.py:486](core/tools.py#L486) `_b_create_invite` builds the record:

```python
source = _source_of(ctx)                       # "health", from ctx["agentId"]
invite = {
    "id": _slug("invite-" + (a.get("title") or "meeting")),
    "kind": "invite",
    "source": source,
    ...
    "status": "waiting for the base agent to pick it up",
}
return ps_write(_vault_dir(ctx, "invites", invite["id"] + ".json"),
                json.dumps(invite, indent=2))
```

The `source` field is stamped here, not at merge time. The docstring says why:

```python
"""...Stamped here rather than at merge time because the merge reads
these files across a policy boundary and should not have to infer
anything about where they came from."""
```

The sandbox writes the file. The health agent's work ends here. It has no
grant anywhere near a calendar.

### Step 8. The base agent notices

Within 20 seconds, `Basecamp._tick` runs. `vault.fingerprint` has changed, so
`_run_sync` starts.

It builds an `Agent` for the base agent id and calls `sync_vaults`. That is a
real sandbox, under `policies/base.json`.

### Step 9. The merge

The PowerShell script reads `vault/health/invites/*.json`. It opens
`mailbox/calendar/2026-10-22.json`, appends the event with its `source` and
`sourceId`, sorts by start time, and writes the file back.

It prints:

```json
{"invites":1,"drafts":0,"refused":[]}
```

### Step 10. The result reaches the screen

`Basecamp._run_sync` parses that line. It updates `self.state`:

```python
merged = int(result.get("invites") or 0) + int(result.get("drafts") or 0)
...
return self._set(state=("partial" if refused else "ok"), ...)
```

Note the `partial` state. The comment explains it:

```python
# Partly refused is NOT "ok". Two of four agents getting through is
# exactly the state a participant has just engineered by editing the
# policy, and calling it a success would hide the thing they are
# looking for.
```

The browser polls `/api/basecamp` every six seconds. `drawKeeper()` in
`ui/app.js` updates the badge count and the border colour. The calendar tab
shows the new event, tagged *from health*, with the fox face.

### The same journey when the policy says no

Remove `${vault}\health\invites` from `paths.read` in `policies/base.json`.
Save. Ask for another invite.

1. The health agent still writes its invite. Its own policy did not change.
2. `Basecamp._tick` fires. The fingerprint changed.
3. `sync_vaults` runs. `Get-ChildItem` on that folder throws.
4. The `catch` records `{source: "health", vault: "health", stage: "invites",
   error: "Access is denied"}`.
5. The other three personas still merge. The script continues.
6. The state becomes `partial`. The bubble border turns amber.
7. The note shows `vault\health\invites — Access is denied`.

Put the line back. `_stamp` includes the policy mtime, so the next tick re-runs
the sync. The invite arrives. There is no restart.

---

## Part 9 — The web server

[core/server.py](core/server.py) is a `ThreadingHTTPServer` from the standard
library. It serves the files in `ui/` and a small JSON API.

### The endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | Everything the user interface needs, in one object. |
| GET | `/api/policy` | One agent's policy. |
| GET | `/api/profile` | The profile and the agent registry. |
| GET | `/api/mailbox` | The global mailbox, read on the host. |
| GET | `/api/basecamp` | The merged view plus the last sync state. |
| GET | `/api/runs`, `/api/refusals` | The sandbox log. |
| GET | `/api/health` | Lemonade and MXC status. Used for polling. |
| POST | `/api/profile` | Save setup. Write policy files. Seed the vault. |
| POST | `/api/profile/reset` | Delete `profile.json`. Stop the base agent. |
| POST | `/api/policy` | Save a policy. Refuses if lint finds an error. |
| POST | `/api/policy/preset` | Overwrite one policy with a named preset. |
| POST | `/api/policy/preview` | Compile a policy. Do not run it. |
| POST | `/api/policy/dryrun` | Compile and `--dry-run` it. |
| POST | `/api/basecamp/sync` | Force a sync on the next tick. |
| POST | `/api/basecamp/read` | Clear the unread badge. |
| POST | `/api/warmup`, `/api/rescan` | Re-check the model and the host. |
| POST | `/api/chat` | The agent loop. Returns SSE. |
| POST | `/api/tool` | Run one tool by hand. Returns SSE. |
| POST | `/api/verify` | Run the full check. Returns SSE. |

### The agent query parameter

[core/server.py:146](core/server.py#L146) `_agent_param` decides which agent a
request is about. It has three cases:

```python
# keep_blank_values, because "?agent=" is a meaningful request - it
# means the root policy.json - and the default would silently drop it
# and hand back the active agent's policy instead.
q = urllib.parse.parse_qs(..., keep_blank_values=True)
if "agent" not in q:
    return self.app.active_agent()
return q["agent"][0] or None
```

| Query | Meaning |
|---|---|
| absent | The active agent from the profile. |
| `?agent=health` | That agent. |
| `?agent=` | The root `policy.json`. Used by Phase 1. |

### Server-sent events over POST

Three endpoints stream. `_sse_open` writes the headers. `_sse` writes one
frame:

```python
def _sse(self, obj):
    try:
        self.wfile.write(("data: %s\n\n" % json.dumps(obj, default=str)).encode("utf-8"))
        self.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        raise _ClientGone()
```

`_ClientGone` is caught in `do_POST`. A user who closes the tab mid-turn does
not produce a stack trace.

### The request body must always be read

[core/server.py:75](core/server.py#L75) `_read_body` runs for every POST,
before dispatch. This is not optional. The docstring explains:

```python
"""Drain the request body off the socket, always, before dispatching.

This is HTTP/1.1 with keep-alive, so the body is not optional reading:
bytes a handler does not consume stay in the buffer and become the
start of the NEXT request on that connection. The browser's postJSON
sends '{}' even when there is nothing to say, so every endpoint that
ignored its body - rescan, warmup, dryrun, profile/reset - was leaving
two bytes behind and the following request arrived with a method of
'{}GET'. It presented as a sporadic 501 that moved around depending on
which button you pressed, which is exactly the kind of bug that gets
blamed on the sandbox."""
```

---

## Part 10 — The browser code

### No build step

There is no bundler, no transpiler, and no package manager. The browser loads
ES modules directly:

```html
<script type="module" src="/app.js"></script>
```

`ui/app.js` imports from `/dragon.js`, `/critters.js`, and `/theme.js`. The
server serves those paths as static files.

### The state object

[ui/app.js:23](ui/app.js#L23) holds all application state in one object:

```javascript
const S = {
  state: null,       // the last /api/state response
  policy: null,      // working copy, may be dirty
  dirty: false,
  agent: null,       // active agent id
  histories: {},     // per-agent chat history
  busy: false,
  abort: null,
  turnCalls: 0,
  turnRefused: 0,
  warmPoll: null,
  mail: null,
};
```

`histories` is keyed by agent id. The comment says why:

```javascript
// per-subagent chat history - switching agents must not
// carry one agent's conversation into another's context
```

### The single rule of this file

The header states it:

```javascript
/*
 * One rule runs through this file: nothing here decides anything. Every tier,
 * every capability, every refusal on screen came from the host - from
 * `wxc-exec --probe`, from a --dry-run, or from a sandbox that really ran and
 * really failed. If the server did not say it, this file does not draw it.
 */
```

### The hydrate cycle

`hydrate()` fetches `/api/state` and redraws everything:

```javascript
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
```

This runs after every save, every tool run, and every agent switch. It is cheap
and it removes a whole class of stale-screen bugs.

### Switching agent

`switchAgent(id)` is not a view change. The comment says:

```javascript
/* Switching agent is not a view change. It swaps the system prompt, the tool
 * set and the policy file all at once, which is the whole reason the rail
 * lists them separately: you can watch the Policy tab change under you. */
```

### The animal faces

[ui/critters.js](ui/critters.js) draws five animals on a 22×22 pixel grid. The
contract matches `dragon.js`, so the existing `.avatar` CSS needs no change.

The art is 22 strings of 22 characters, over a small palette:

```
.  transparent      w  eye white       p  pink: nose, inner ear
o  outline          e  pupil           a  accent: fronds, tufts
b  body             s  body shade      l  light: muzzle, chest
```

Only the ears and the palette change between species. The header explains:

```javascript
 * Only the ears and the palette differ between species, on purpose. Five
 * animals drawn to five different proportions look like five clip-art assets
 * that happen to share a screen; five drawn on one armature look like a set.
```

A state changes three rows only: the two eye rows and the mouth row. `paint()`
converts the grid to run-length `<rect>` elements. A 22×22 grid is 484 cells
and about 90 runs.

### The themes

[ui/theme.js](ui/theme.js) holds three theme records. `applyTheme` sets
`document.documentElement.dataset.theme` and writes to `localStorage`.

The CSS is a token table for each theme. Nothing below the token blocks knows
that more than one theme exists:

```css
:root, [data-theme="parchment"] { --bg:#FAF8F1; ... }
[data-theme="moonlit"]          { --bg:#11141E; ... }
[data-theme="sakura"]           { --bg:#FDF4F8; ... }
```

Every page carries a small inline script in its `<head>`, before the
stylesheet:

```html
<script>
  try {
    var t = localStorage.getItem("castlekeep-theme");
    if (["parchment", "moonlit", "sakura"].indexOf(t) >= 0)
      document.documentElement.dataset.theme = t;
  } catch (e) {}
</script>
```

This must be inline. A module script is deferred by definition, and that is too
late. Without it, a dark theme shows a white flash on every page load.

### The floating bubble

The bubble is the base agent's presence. `ui/app.js` holds its state in `K`:

```javascript
const K = { open: false, tab: "calendar", data: null, poll: null };
```

`loadKeeper()` polls `/api/basecamp`. `drawKeeper()` sets the badge, the border
colour, and the face state:

| Sync state | Border | Face |
|---|---|---|
| `ok`, no unread | Brand | `idle` |
| `ok`, unread | Brand | `happy` |
| `partial` | Amber | `thinking` |
| `blocked` | Red, no float animation | `alert` |

`drawKeeperNote()` writes the refusal text. It uses `r.vault`, not `r.source`:

```javascript
// r.vault, not r.source: the folder is what has to go in the policy
// file, and for the computer assistant the two are different strings.
```

### The onboarding page

[ui/onboard.html](ui/onboard.html) holds five panels and one state object.

The face picker uses a swap, never a steal:

```javascript
/* Assigning a face is a SWAP, never a steal. If the fox is already on the
 * finance agent and you put it on the base agent, finance gets whatever the
 * base agent was wearing. ... with five faces for five agents there is always
 * something to trade. */
function assignCritter(agentId, species) {
  const holder = Object.keys(S.critters)
    .find((id) => id !== agentId && S.critters[id] === species);
  if (holder) S.critters[holder] = S.critters[agentId];
  S.critters[agentId] = species;
}
```

The connector rules are duplicated from `core/profile.py`. The comment states
the status of the duplicate:

```javascript
/* Same three rules the server enforces in profile.py. Duplicated rather than
 * fetched because the point of validating here is to say something useful
 * before anything is sent - but the server is still the one that decides, and
 * an entry that gets past this is dropped there rather than trusted. */
```

---

## Part 11 — The proof: verify.py

`python verify.py` measures every claim on your own machine. It writes
`VERIFY-REPORT.md` and `verify-report.json`.

The Run tab calls the same code over SSE.

### What it checks

| Group | Checks |
|---|---|
| Host | The binary, the probe, the tier, each capability. |
| Dry run | Every policy shape, validated but not run. |
| Live | Real sandboxes that try to do things they must not. |
| Tools | Every tool in the catalogue, under its own agent's policy. |
| Lemonade | Reachable, serving the model, weights resident. |

### The results on this machine

```
42 passed, 8 warnings, 0 failed, 5 skipped
Tier      AppContainer + BFS (tier 2)
Dialect   modern
```

The eight warnings are all host capability limits, not code faults. Four of
them are the fields that tier 2 cannot enforce.

### Why a tool test uses its own agent's policy

[core/verify.py:417](core/verify.py#L417) finds the owner of each tool from the
registry:

```python
def owner_of(tool):
    for agent_id in agents_mod.ids():
        if tool.for_agent(agent_id) and _has_policy(app, agent_id):
            return agent_id
    return None
```

A tool that is tested under the wrong policy gives a result about the wrong
file. `_has_policy` at [core/verify.py:85](core/verify.py#L85) states this.

---

## Part 12 — Measured limits on this hardware

These are facts about this machine, measured by `verify.py`. They are not
opinions and they are not bugs in CastleKeep.

### 1. `dir` does not work inside a sandbox

`cmd`'s directory listing asks for an access that an AppContainer read grant
does not carry. `Get-ChildItem` on the same granted folder works.

This is why every file-listing tool uses PowerShell. The comment is at
[core/tools.py:254](core/tools.py#L254).

### 2. Nothing can delete or move a file

A read-write grant carries create and write. It does not carry DELETE. So
`Move-Item` and `move` both fail, even inside one granted folder.

Two consequences:

- The `move_file` tool cannot work on this tier. `verify.py` skips it and says
  why.
- `archive_message` copies the message and leaves a tombstone. See
  [core/tools.py:314](core/tools.py#L314) `_ps_file_message`.
- `sync_vaults` leaves each invite in place and dedupes by `sourceId`.

### 3. A sandbox cannot reach `127.0.0.1`

`ingress.hostLoopback='allow'` is rejected on the AppContainer tiers. This is
why Lemonade runs on the host, and why the mailbox is files and not a local
mail server.

The full reasoning is at the top of [core/mailbox.py:9](core/mailbox.py#L9).

### 4. `deniedPaths` is rejected, not ignored

On tier 2, `filesystem.deniedPaths` makes the run fail. Everything is denied by
default. Narrow the grant lists instead.

### 5. `New-Item -Force` needs rights on the parent

Creating a directory that already exists still asks for create rights on the
parent folder. `_ps_file_message` guards with `Test-Path` for this reason:

```python
# Guarded, not -Force. New-Item -Force on a directory that already
# exists still asks for create rights on the PARENT, and the parent
# here is the mailbox root, which no sensible policy grants.
```

---

## Part 13 — How to extend the code

### Add a tool

1. Write a builder in `core/tools.py`. It takes `(args, ctx)` and returns a
   command string. Use `shell_ps` for anything with structure.
2. Write a `paths` callback, if the tool touches the filesystem. This feeds the
   refusal diagnosis.
3. Add a `Tool(...)` entry to `CATALOGUE`. Set `agent` to one id, a tuple of
   ids, or `"*"`.
4. Add the tool name to the owning agent's `tools` list in `core/agents.py`.
5. Add the tool to the preset tool gates in `core/agents.py`.
6. Add a sample call to `sample` in `core/verify.py`, so the tool is tested.

### Add a persona agent

1. Add a record to `REGISTRY` in `core/agents.py`. Set `vault` and
   `dataFolder`.
2. Add presets with `_persona_presets(...)`.
3. Add seed data under the new key in `SEED` in `core/vault.py`.
4. Add the id to `_PERSONA_IDS` in `core/agents.py`, so the base agent reads
   its folders.

`vault.layout()` reads the registry, so the folders are made automatically.
`tools.PERSONAS` reads `agents.persona_ids()`, so the shared record tools apply
automatically.

> **Note.** There are five animal faces and five agents. A sixth agent needs a
> sixth face in `ui/critters.js` and in `profile.CRITTERS`.

### Add a theme

1. Add a record to `THEMES` in `ui/theme.js`.
2. Add a token block to `ui/style.css`. Copy an existing block and change the
   values. Set `--bg-art` and `--chat-art`.
3. Add the id to `THEMES` in `core/profile.py`.
4. Add the id to the inline list in the `<head>` of `launch.html`,
   `onboard.html`, and `index.html`.

### Add a path variable

Add one key to `path_context` in [core/policy.py:36](core/policy.py#L36). That
is the only place. `expand`, `lint`, and `compile_config` all read from that
dictionary.

### Change what a tool may reach

Do not change the code. Edit the policy file in `policies/`. The change lands
on the next tool call.

---

## Appendix A — Terms

| Term | Meaning in this project |
|---|---|
| Agent | One of the five records in `agents.REGISTRY`. |
| Persona | One of the four agents with a vault folder. |
| Base agent | The always-on agent with id `base`. |
| Run | One invocation of `wxc-exec`. One sandbox. |
| Policy | One file in `policies/`, or the root `policy.json`. |
| Preset | A complete starting policy offered during setup. |
| Grant | One entry in `paths.read` or `paths.write`. |
| Tier | The containment strength that this host supports. |
| Dialect | Which network schema shape `wxc-exec` accepts. |
| Host gate | A tool switched off in `policy.tools`. |
| Tombstone | A marker file left where a message was, because this tier cannot delete. |
| Vault | The `vault/` folder, or one persona folder inside it. |
| Connector | One of the three dummy account names. |
| Critter | One of the five animal faces. |

## Appendix B — Where to read next

| If you want to understand | Read |
|---|---|
| The argument, in short | [README.md](README.md) |
| How to present this | [WORKSHOP.md](WORKSHOP.md) |
| The diagrams | [ARCHITECTURE.md](ARCHITECTURE.md), [/architecture](ui/architecture.html) |
| Each MXC wire field | [COMPILED.md](COMPILED.md) |
| MXC without an agent | [/phase1](ui/phase1.html) |
| What this host can prove | `VERIFY-REPORT.md`, after `python verify.py` |
