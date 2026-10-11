# CastleKeep

Four local AI agents on one machine, each able to do only what you let it.

Everything runs on your machine. The model runs on your machine. The agent
loop runs on your machine. And every single thing an agent tries to *do* runs
inside a throwaway Microsoft MXC sandbox built from a policy file you can edit
while the app is running.

The point of the exercise is the refusals. You will ask an agent to read
something it should not be able to read, and watch the sandbox stop it. Then
you will change one line of policy, ask again, and watch it work. Nothing in
this app simulates that. If the screen says a sandbox refused something, a
sandbox refused something.

## The four agents

They share one model, one agent loop and the same nine tools. The only thing
that differs between them is the box their tool calls run inside, which is why
the differences you see are a containment result and not an `if` statement.

The dragon checks the device. It reads no files of yours at all and has no
network. It is the only one the launch wizard names, so it answers to whatever
you typed there; the other three go by their job titles.

Finance looks up rates and prices. It is the only agent that may reach the
network, and it is also the only one with nothing of yours to send.

Health reads a folder of clinic notes and cannot write a byte or reach the
network. The notes in `workspace\clinic` are invented for this workshop. Do
not repoint it at real medical records to make the demo better.

Paperwork files and renames things. It may write, inside one folder, and has
no network.

Read those last two paragraphs against each other. The agent that can talk to
the internet is the one holding nothing worth sending, and the agent holding
your files cannot talk.

Each agent keeps its own conversation. Switching agents in the bar swaps the
whole transcript rather than carrying one across, so a model is never handed a
stretch of conversation produced under a boundary that was not its own.

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

**Agents** is the chat tab, with all four along the top and a separate
conversation behind each. Ask the dragon what kind of machine this is, how
much disk is free, what is eating memory. Each answer involves a real tool
call, and each tool call spawns a real sandbox, and you can watch them arrive
inline, with the command and the exact configuration that was sent. The panel
on the right shows the boundary the agent on screen is working inside, and
underneath it the same four lines for all of them, so you can see what moved.

**Control Panel** is the honest view: the tier this host actually gave you,
which knobs it can enforce, every tool and what it needs, and a running list of
everything that has been refused and by whom.

**Policy** is the file, and the picker at the top says whose. Edit paths, flip
network off, switch tools on and off. Knobs this host cannot enforce are
disabled with the reason attached, rather than silently doing nothing. Save,
and the change lands on that agent's very next tool call and on no other
agent's. No restart, no reload. Each call re-reads the file from disk and
compiles a fresh sandbox configuration from it.

**Run** is the terminal view, if you would rather watch it that way. The
hand-run picks an agent too, so a tool you run yourself goes into the same
one-shot sandbox that agent's own tool calls get.

**Settings** is the model and the executor.

## Where the policies live

Each agent brings its own, as one file in `profiles\`. The filename is the
agent's id, so the dragon is `profiles\diagnostics.json`. A profile is a
policy with a few extra keys on top for the name, the creature and the
starter questions, and the sandbox compiler ignores the keys it does not
know. Drop a fifth file in that folder and you get a fifth agent without
touching any Python.

`policy.json` in the root is the host-wide default, and no agent uses it. It
is what the Run tab's dry run, the network dialect negotiation at startup and
`verify.py` compile, because those make a claim about the machine rather than
about an agent and must not borrow one agent's boundary to do it.

You can edit any of them in a text editor instead of the Policy tab. They are
the same files, and they are commented. `COMPILED.md` explains what each field
becomes on the wire, and `profiles\_readme.md` explains the extra keys.

## Three ways to be told no

They look different on screen on purpose, because they mean very different
things.

**Stopped on the host** (blue) means a tool is switched off in the agent's
profile. The request never reached a sandbox. This is the weakest kind of
control, the agent's own harness declining, and it is marked that way. All
four profiles ship with the same tools switched on, deliberately, so that
what any one agent cannot do is something MXC refused rather than something
the harness never attempted.

**Blocked by policy** (red) means the sandbox started, the command ran, and
MXC refused the access. This is the real thing.

**Sandbox refused to start** (amber) means the configuration itself was
rejected. Usually you asked for something this backend does not implement.
The refusal names the offending field.

Each agent is told the difference too, in plain language, along with an
instruction not to go looking for a way around it and the names of the other
three, so that "Paperwork can do that, ask it" is an answer it can give.

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
