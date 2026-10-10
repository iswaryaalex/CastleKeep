# CastleKeep

A local AI assistant that can only do what you let it.

Everything runs on your machine. The model runs on your machine. The agent
loop runs on your machine. And every single thing the agent tries to *do* runs
inside a throwaway Microsoft MXC sandbox built from a policy file you can edit
while the app is running.

The point of the exercise is the refusals. You will ask your agent to read
something it should not be able to read - a file, or a thread in your private
mail - and watch the sandbox stop it. Then you will change one line of policy,
ask again, and watch it work. Nothing in this app simulates that. If the
screen says a sandbox refused something, a sandbox refused something.

Windows only. Python 3.9 or newer. No pip install. It is stdlib on purpose,
so it survives conference wifi and a locked-down laptop.

## Before you start

You need two things on the box.

**Python 3.9+.** `python --version` should answer.

**Lemonade Server**, see below.

The MXC executables are already here, in `bin\`, for x64 and arm64. CastleKeep
invokes `bin\x64\wxc-exec.exe` and nothing outside this folder, so you can copy
`castlekeep\` to another machine and it still runs. `bin\README.md` says what
each executable is and where they came from. To use a different build, point
`mxc.binDir` or `mxc.exePath` in `config.json` at it, or set `MXC_BIN_DIR`.
CastleKeep tells you at startup if it cannot find an executor.

**Lemonade Server**, running and *serving the model `config.json` names*.
Those are two different claims and CastleKeep checks both, because "the server is up"
is the one that means almost nothing, and treating it as a green light is how
a preflight passes on a setup where the agent cannot answer a single message.
If the name does not match, `run.py` stops and tells you, rather than starting
and 404ing on your first sentence.

```
python workshop\models.py            what Lemonade is actually serving
python workshop\models.py qwen       search
python workshop\models.py --pick X   write X into config.json
```

`config.json` is re-read while the app runs, so `--pick` lands on the next
poll. The model chip changes and the new weights start loading. If the chip
and the file ever disagree, the file wins and the chip is about a second behind.

Startup then sends one throwaway prompt to load the weights before you need
them. On a 35B MoE that is tens of seconds of disk read, and if the first
request is a human's first chat message they watch a dragon do nothing and
conclude the app is broken. The model chip in the title bar reads *warming*
and flips to *ready* on its own.

Lemonade runs on the host and is never sandboxed. The model is not the thing
being contained.

## Run it

Verify first. Always verify first.

```
python verify.py
```

This is the program that answers "what exactly works on this machine." It
inspects the host, sends a series of `--dry-run` configurations to find out
what the binary will accept, then spawns real sandboxes and checks that the
things that should be refused are actually refused. It writes
`VERIFY-REPORT.md` and `verify-report.json` next to itself.

Read the summary at the bottom. It tells you the tier you actually got, the
network dialect that was accepted, and lists anything that failed under the
heading *"Until these pass, do not describe this setup as contained."* Take
that heading literally.

Then:

```
python run.py
```

The browser opens on `http://127.0.0.1:7701`, which is the launch screen: the
measured containment tier, whether Lemonade is serving the model `config.json`
names, and the weights loading into memory. The door opens when the model is
resident. If something is wrong it says so there and gives you a Re-check
button, so fixing it does not mean restarting.

The app itself is `/app` and the terminal walkthrough is `/phase1`.
`--no-browser` and `--port` do what you expect. `python run.py --check` prints
the host report and exits.

## Setting up your agent

The first time through, the launch screen sends you to `/onboard` instead of
straight into the app. Five questions: your name; what to call your base agent
and which animal it is; which of the four other agents to turn on and which
animal each of them gets; three dummy accounts; and a starting policy for
every agent.

That last one is the point. You are told what each preset grants and what it
will refuse, and you choose, **before** any agent has done anything. An agent
you named and whose permissions you picked is one you argue with; an agent
called Assistant is a product you assume somebody else secured.

It writes `profile.json`, seeds `vault\` with each agent's sample data, and
writes one policy file per agent under `policies\`. None of the three is in
git - forty people clone the same repo, and the name you type is yours. A
preset cannot grant anything the Policy tab could not; it is a starting point,
not a privileged one. Settings has a reset, a theme picker, and the same
presets later.

The accounts step asks for a Gmail address, a Reddit username and a GitHub
username. These create **local dummy accounts**: nothing authenticates
anywhere, no password is asked for, no request leaves the machine. The names
only decide what the sample data says.

## Four agents, and one that is always on

Each of the four **personas** is sealed into its own folder under `vault\`,
and that folder is the entire world it has:

| Agent | Reads | Writes |
|---|---|---|
| **Health** | `vault\health\records` - vitals, labs, medications, appointments | `invites`, `outbox` |
| **Finance** | `vault\finance\ledger` - accounts, transactions, bills, budget | `invites`, `outbox` |
| **PC Assist** | the device itself, plus `vault\pc-assist\reddit` | the workspace, `invites`, `outbox` |
| **Coding** | `vault\coding\github` - repos, issues, PRs, notifications | `invites`, `outbox` |

A persona cannot put anything on a calendar. The most it can do is write an
invitation into its own `invites\` folder and stop.

The **base agent** - the one you named - is what picks those up. Every twenty
seconds it checks whether any agent's `invites\` or `outbox\` has changed, and
if so spawns **one real sandbox** under `policies\base.json` to merge them
into the global calendar and mail view in `mailbox\`. That view lives in the
floating bubble in the corner, with a counter, and each item is tagged with
the agent that produced it.

The asymmetry is the whole exercise. The base agent can see across all four
agents' outgoing folders and into none of their data - not one blood test, not
one bank balance. Take one `invites` line out of its `paths.read` and that
agent silently stops reaching the calendar, with the refusal reported in
Windows' own words, on the next check, with no restart.

Data-as-files is not a shortcut around doing it properly; it is the only shape
that makes the lesson expressible. The sandbox cannot usefully reach the
network for this - `hostLoopback` is only grantable on BaseContainer, and
`verify.py` measures that a contained process cannot reach loopback on the
tiers most machines get. On disk, "read my records but only write to invites"
is one line of `paths.read` and one of `paths.write`, enforced by the same
machinery that refuses a read of `C:\Users`. The full reasoning, including why
pointing the room at live shared IMAP ends with a locked Google account, is at
the top of `core\mailbox.py`, and the vault's version of it is at the top of
`core\vault.py`.

Each agent has its own prompt, its own tools and its own policy file.
Switching between them - in the strip above the chat, or in the rail - swaps
all three at once, and the Policy tab names the file it is editing so you can
see it change.

## Phase 1, if you are running this as a workshop

`http://127.0.0.1:7701/phase1` is a seven-step terminal walkthrough that
drives `wxc-exec.exe` by hand before an agent is involved at all. Stage the
lab with `powershell -ExecutionPolicy Bypass -File .\workshop\lab-setup.ps1`,
then work down the page. Every command has a copy button, and the real
binary path and the measured tier are filled in from the running app rather
than hard-coded.

Steps five through seven are the ones worth the room's attention: the same
command refused by one line of policy, then a prompt-injection payload run
first on the host and then inside the sandbox. The second run still gets
injected, you watch the model obey the poisoned document, and the read
still fails, which is the entire argument for doing this at the boundary
rather than in the prompt.

The lab writes to `C:\CastleKeepLab` and the "secret" is a decoy string.
Point a demo at a real credential exactly once and you will understand why.

## The five tabs

**Chat** is where you talk to whichever agent is selected - switch with the
strip of faces above the transcript. Ask Health what your vitals have done
this month, ask Coding what needs you on GitHub, ask PC Assist what is eating
the disk. Each answer involves a real tool call, and each tool call spawns a
real sandbox, and you can watch them arrive inline, with the command and the
exact configuration that was sent. The base agent's bubble sits in the corner
throughout, collecting whatever the others produce.

**Control Panel** is the honest view: the tier this host actually gave you,
which knobs it can enforce, every tool and what it needs, and a running list of
everything that has been refused and by whom.

**Policy** is the file - the selected agent's, named at the top of the
tab. Edit paths, flip network off, switch tools on and off, or start again
from one of the presets.
Knobs this host cannot enforce are disabled with the reason attached, rather
than silently doing nothing. Save, and the change lands on the agent's very
next tool call. No restart, no reload. Each call re-reads the file from disk
and compiles a fresh sandbox configuration from it.

**Run** is the terminal view, if you would rather watch it that way.

**Settings** is the model, the executor, the theme, and your setup -
including a reset if somebody else needs the machine next.

You can also just edit the files in `policies\` in a text editor. They are the
same files the tab writes, and the root `policy.json` they are modelled on is
commented. `COMPILED.md` explains what each field becomes on the wire.

## If you want to read the code

`CODE-TOUR.md` explains the whole codebase, from the first line that runs to
the last pixel on the screen. It names the file and the function for every
step, quotes the code, and says why each decision was made. It covers MXC from
scratch, for readers who have never met it. Start there if you intend to
change anything.

It is written in ASD-STE100 Simplified Technical English: short sentences,
active voice, one meaning per word.

## If you would rather see it than read it

`ARCHITECTURE.md` draws the whole system: the trust boundary, one tool call end
to end, onboarding, what an agent actually is, where the data comes from, and
the three kinds of refusal. The diagrams are Mermaid, which GitHub renders
inline and VS Code renders with the *Markdown Preview Mermaid Support*
extension.

If you would rather not install anything, run the app and open
**`/architecture`** - the same diagrams in plain HTML and CSS, no extension and
no CDN. Settings links to it.

## Three ways to be told no

They look different on screen on purpose, because they mean very different
things.

**Stopped on the host** (blue) means a tool is switched off in `policy.json`.
The request never reached a sandbox. This is the weakest kind of control,
the agent's own harness declining, and it is marked that way.

**Blocked by policy** (red) means the sandbox started, the command ran, and
MXC refused the access. This is the real thing.

**Sandbox refused to start** (amber) means the configuration itself was
rejected. Usually you asked for something this backend does not implement.
The refusal names the offending field.

The agent is told the difference too, in plain language, along with an
instruction not to go looking for a way around it.

## What this does not do

It does not sandbox the model, the agent loop, or the web UI. Those run on the
host with your privileges. MXC has no long-running daemon to host them in, and
an AppContainer on most machines cannot reliably reach a loopback port, so a
design that put the loop inside would break on the majority of laptops. What
is contained is what the agent *does*, not what the agent *is*. That is a real
limit and it is worth saying out loud rather than glossing.

It does not promise you a tier. BaseContainer is kernel-enforced and is what
you want; most machines will fall back to AppContainer with DACL mutation,
which rewrites real ACLs on disk and needs `WRITE_DAC`. `verify.py` tells you
which one you got. Nothing in the UI hard-codes an answer to that question.
