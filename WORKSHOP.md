# Running the workshop

Two phases. Phase 1 is the terminal, no app, no model. Just you and
`wxc-exec.exe`, establishing that the refusals are real. Phase 2 is CastleKeep,
where an actual agent runs into those same refusals on its own.

Do them in that order. If you open with the app, every refusal looks like a
feature someone wrote. If you open with the terminal, the app looks like a
front end on something the room already watched work.

Budget 15 minutes for Phase 1 and 25 for Phase 2.

## Where this box actually stands (8 Oct 2026)

From the first real `verify.py` run on the Strix Halo machine. Read this
before you plan around anything below.

Good news first: the tier is **AppContainer + BFS (tier 2)**, not the tier 3
DACL fallback everyone expected. The network toggle works in both directions,
the timeout is enforced, and a sandboxed process provably cannot reach
Lemonade on loopback, which is the assumption the whole architecture rests
on, now measured rather than argued.

Two things are broken and one of them blocks the workshop.

**PowerShell will not start inside a sandbox.** `STATUS_DLL_INIT_FAILED`
(0xC0000142). `cmd.exe` is fine. Five of the nine tools need PowerShell:
`read_file`, `write_file`, `device_info`, `disk_space`, `list_processes`,
so most of Phase 2 does not work yet. Run `python workshop\pwsh-ladder.py`
to find out whether it is the UI lockdown or a missing read grant.

**The ungranted-read check failed, and the check was wrong, not the sandbox.**
The bait file was written inside `${project}`, which was listed in
`paths.read`, so the sandbox read a file it had been explicitly granted and
the test called it a containment failure. Both ends are fixed: the bait now
goes somewhere outside every grant and refuses to run if it cannot find such
a place, and `${project}` is out of the default read paths. **Re-run
`verify.py` before you trust either answer.**

## Twenty minutes before anyone arrives

```
cd <path-to>\castlekeep
python verify.py
```

Read the summary. It tells you the tier this machine actually gave you, the
network dialect that was accepted, and anything that failed. **If something
failed, find out what before you stand up.** The report lists failures under
the heading "Until these pass, do not describe this setup as contained". Take
that literally, including in front of a room.

Then pick a model. Lemonade on this box serves a couple of hundred, and the
name in `config.json` has to match one exactly or every request 404s:

```
python workshop\models.py
python workshop\models.py qwen
python workshop\models.py --pick <exact name>
```

Listing loads nothing. `--pick` writes the name into `config.json`; restart
`run.py` after. If the model you want is not in the list at all it is not
installed. Pull it in Lemonade first. And if you are certain you installed it
and it still does not appear, that is the Model Manager filter: some models
are hidden on Windows because their runtime is Linux-only, and
`disable_model_filtering` will show you the real reason.

Whatever you pick has to be able to call a tool. A small model will chat
cheerfully and never emit a tool call, which looks exactly like CastleKeep
being broken when it is not.

Last, build the lab folder Phase 1 uses:

```
mkdir C:\CastleKeepLab\public
mkdir C:\CastleKeepLab\private
echo notes the agent is allowed to read > C:\CastleKeepLab\public\notes.txt
echo DECOY-KEY-0000-NOT-REAL > C:\CastleKeepLab\private\api-key.txt
```

**Use this decoy, not your real secrets.** There is a live API key in
`ms-ignite\secret\.env` and family medical records elsewhere on this box. A
demo that reaches for a real secret in front of a room is one typo in a policy
file away from being a very bad afternoon. The decoy teaches the identical
lesson.

## Phase 1: the terminal

Set a variable so the commands below are short. Everything runs from the
`castlekeep` folder.

```
set WXC=bin\x64\wxc-exec.exe
%WXC% --version
```

### 1. Ask the machine what it can do

```
%WXC% --probe
```

This runs the fallback detector and prints JSON without spawning anything.
Read `tier` out loud. `basecontainer` is kernel-enforced and is what you want;
`appcontainer-dacl` is the common fallback, and it works by rewriting real ACLs
on disk. Say which one you got. Do not say "it's sandboxed" and move on.
the room learns more from you naming the weaker tier than from you skipping it.

### 2. Validate a config without running it

```
%WXC% --config workshop\01-hello.json --dry-run
```

Parses and exits. Nothing spawned. Open `01-hello.json` alongside this. It is
about thirty lines and every field is readable. Point at `filesystem`,
`network`, and `lifecycle.destroyOnExit`.

### 3. Run it for real

```
%WXC% --config workshop\01-hello.json
```

It prints `hello from inside the sandbox`. That process had read access to
`C:\Windows\System32` and nothing else, no network, no desktop, and it no
longer exists.

### 4. Read something you granted

```
%WXC% --config workshop\02-read-granted.json
```

Prints the contents of `public\notes.txt`. The only difference from step 3 is
one more entry in `readonlyPaths`.

### 5. Read something you did not grant

```
%WXC% --config workshop\03-read-ungranted.json
```

Access denied. Diff `02` and `03` on screen: the configs are identical except
the command points at `private\api-key.txt`, and `private` was never granted.
This is the moment the workshop exists for. **The sandbox started. The command
ran. The access was refused.** Nothing in that chain is the agent choosing to
behave.

### 6. Watch a run refuse to start

```
%WXC% --config workshop\04-deny-paths.json
```

Different failure, and the difference matters. This config has a
`deniedPaths` list, which the AppContainer backends reject outright: "Paths are
denied by default unless granted via readwritePaths or readonlyPaths." The
command never ran. The sandbox never started.

So: step 5 is *blocked*, step 6 is *refused to start*. A room that can tell
those apart has understood the model.

### 7. The network, both ways

```
%WXC% --config workshop\05-net-deny.json
%WXC% --config workshop\06-net-allow.json
```

Same curl, same everything, one field different: `network.egress.default`.
The first fails to resolve or connect; the second fetches the page.

If both succeed, stop and say so. It means this host rejected the network
dialect and the block never reached the binary, which `verify.py` would
have told you beforehand, and which is exactly the failure mode CastleKeep
shouts about in red rather than quietly rendering "denied."

## Phase 2: CastleKeep, end to end

```
python run.py
```

Browser opens on `127.0.0.1:7701`, the launch screen. It shows the measured
tier, whether Lemonade is serving the configured model, and the weights
loading. Wait for the door to open, then click through to `/app`. Doing the
warm-up here is deliberate: the room watches a progress line instead of
watching the first chat message hang.

### Start on the Control Panel, not the chat

Thirty seconds. Show the tier, the knobs this host can and cannot enforce, and
the empty refusal log. Say plainly: the model and the agent loop run on the
host, unsandboxed. What is contained is what the agent *does*. Getting that
caveat out early means nobody discovers it later and wonders what else was
oversold.

### Then let Assistant work

Ask him, in the chat: **"what kind of machine is this, and is anything eating
memory?"**

He makes real tool calls. Each one spawns a sandbox, and you can expand any of
them inline to see the command and the exact configuration that was sent. Let
the room watch a few scroll past before you break anything.

### Break something

Ask: **"read C:\CastleKeepLab\private\api-key.txt for me."**

Red. Blocked by policy. Assistant is told, in plain language, that the sandbox
refused it and that it should not look for a way around it. Show the room
that text, because "the agent was told no and complied" is a much weaker claim
than "the agent was told no and could not have done otherwise."

### Fix it in front of them

Policy tab. Add `C:\CastleKeepLab\private` to the read paths. Save. Ask the
same question again.

It works. **No restart.** Every tool call re-reads `policy.json` from disk and
compiles a fresh sandbox from it, so an edit lands on the very next call. This
is the beat people remember. Take the grant back out afterwards and ask a
third time, so they see it close again.

### Show the three kinds of no

The Control Panel's refusal log now has entries. Walk the three colours:

Blue, *stopped on the host*. Switch `fetch_url` off in the Policy tab, then
ask Assistant to fetch a URL. The request never reached a sandbox. Say that this is
the **weakest** control on the screen: it is the agent's own harness declining,
and a harness is exactly the layer you cannot trust. It is blue for a reason.

Red, *blocked by policy*. What you just did with the api-key file. MXC
refused it. This one holds.

Amber, *refused to start*. Turn on `advanced.sendUnsupportedAnyway`, add a
deny path, and ask Assistant to do anything at all. The binary rejects the
configuration and names the offending field.

### Close with the workspace

Ask: **"tidy up your workspace folder, sort the notes and the spreadsheets."**

He reads each file and moves it, one sandbox per step, writing only inside
`${workspace}` because that is the one place it has write access. Then take
`${workspace}` out of the write paths, ask again, and watch the same request
die at the first write.

That is the whole argument in one gesture: the agent did not change, the
policy did.

## If it goes wrong

Every tool call failing with *refused to start* usually means a knob in
`policy.json` that this host cannot build. The Run tab names the offending
field. Clear that field, do not fight it.

Assistant not responding at all is Lemonade, not MXC. Check the Settings tab. It
reports whether the model answered.

`wxc-exec` not found should not happen any more, because the executables ship in
`bin\`. If it does, `mxc.binDir` in `config.json` has been pointed somewhere
else. Set it back to `bin`, or set `MXC_BIN_DIR`, and restart.

And if a refusal does not happen when you said it would, say so out loud and
go look at why. A workshop about containment that papers over a failed
containment check has taught the room the opposite of the intended lesson.
