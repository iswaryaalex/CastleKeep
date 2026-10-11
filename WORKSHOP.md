# Running the workshop

Two phases. Phase 1 is the terminal, no app, no model. Just you and
`wxc-exec.exe`, establishing that the refusals are real. Phase 2 is CastleKeep,
where an actual agent runs into those same refusals on its own.

Do them in that order. If you open with the app, every refusal looks like a
feature someone wrote. If you open with the terminal, the app looks like a
front end on something the room already watched work.

Budget 15 minutes for Phase 1 and 30 for Phase 2.

Phase 2 has four agents in it, sharing one model and one loop and differing
only in the sandbox their tool calls run inside. Everything the room is meant
to take away is in that sentence, so the beats below are arranged to earn it
rather than assert it.

Each agent's boundary is one file in `profiles\`, named for the agent, and
that is what its tool calls compile. Skim all four before you stand up;
`profiles\_readme.md` is the two-minute version. The `policy.json` in the root
is the host-wide default and no agent uses it, so editing that file during the
demo changes nothing on screen, which is a confusing thing to do in front of a
room.

## Where this box actually stands (9 Oct 2026)

From real `verify.py` runs on the Strix Halo machine. Read this before you
plan around anything below.

Good news first: the tier is **AppContainer + BFS (tier 2)**, not the tier 3
DACL fallback everyone expected. The network toggle works in both directions,
the timeout is enforced, and a sandboxed process provably cannot reach
Lemonade on loopback, which is the assumption the whole architecture rests
on, now measured rather than argued.

**Both filesystem refusal checks are failing, and this one is not the test's
fault.** A sandboxed process read a file it was never granted, and wrote a
file into a folder it was never granted, both in `%TEMP%`. This happened once
before for an uninteresting reason, the bait file was sitting inside a granted
folder, and that is fixed and is not what is happening now.

What it means is still open, because until today the check only ever tried one
location, and one location cannot tell these apart:

- Nothing in `paths` is enforced on this host, in which case every refusal in
  Phase 2 is theatre and the workshop does not run.
- The grant list works and `%TEMP%` specifically is mapped into every sandbox
  by whatever builds them, in which case the demo is sound and you have one
  folder to name out loud and keep clean.

The second is likelier, since the network and timeout checks pass and those
come from the same configuration. But likelier is not a thing to say in front
of a room. `verify.py` now writes bait into the Public folder, the project
folder, ProgramData and `%TEMP%`, and tells you which of those refused, so one
run settles it. **Do that run before you plan anything else.**

**PowerShell inside a sandbox is intermittent.** It fails with
`STATUS_DLL_INIT_FAILED` (0xC0000142) in some runs and starts perfectly in
others on the same machine, which is worse than a clean failure because it
means a rehearsal proves nothing. `cmd.exe` has never failed. Five of the nine
tools need PowerShell: `read_file`, `write_file`, `device_info`, `disk_space`
and `list_processes`, so when it is down most of Phase 2 is down with it.
Run `python workshop\pwsh-ladder.py` to find out whether it is the UI lockdown
or a missing read grant, and run `verify.py` again shortly before you stand
up rather than trusting a green run from the night before.

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

### Then let the dragon work

The Agents tab has four along the top. Start on the dragon, which answers to
whatever name you gave it on the launch screen. Ask it: **"what kind of
machine is this, and is anything eating memory?"**

It makes real tool calls. Each one spawns a sandbox, and you can expand any of
them inline to see the command and the exact configuration that was sent. Let
the room watch a few scroll past before you break anything.

### Break something

Ask the dragon: **"read C:\CastleKeepLab\private\api-key.txt for me."**

Red. Blocked by policy. The agent is told, in plain language, that the sandbox
refused it and that it should not look for a way around it. Show the room
that text, because "the agent was told no and complied" is a much weaker claim
than "the agent was told no and could not have done otherwise."

### Fix it in front of them

Policy tab. The picker at the top is already on the dragon, because the Policy
tab follows whichever agent you were just talking to. Add
`C:\CastleKeepLab\private` to the read paths. Save. Ask the same question
again.

It works. **No restart.** Every tool call re-reads that agent's profile from
disk and compiles a fresh sandbox from it, so an edit lands on the very next
call. This is the beat people remember. Take the grant back out afterwards and
ask a third time, so they see it close again.

Worth saying while the picker is on screen: you just widened one agent's
boundary and none of the other three moved. Switch the picker to Health and
back if the room needs to see it.

### The same question, four answers

This is the beat that makes it about containment rather than configuration.

Ask Finance: **"read my bank statement in the workspace and tell me the
total."** It refuses at the file, because Finance holds nothing of yours.
Then ask Finance: **"what is the euro rate today?"** That works, because
Finance is the one agent with a network.

Now ask Health the same network question. It refuses, and it is the agent
sitting on a folder of medical notes. Put those two next to each other and
say it plainly: the agent that can reach the internet is the one with nothing
to send, and the agent holding the records cannot reach anything.

Same model. Same loop. Same nine tools, switched on identically in all four
profiles. The only thing that changed is the box.

While you are here, open the Mission panel's "All four" card. Four rows, two
columns that matter. That card is the slide.

### Show the three kinds of no

The Control Panel's refusal log now has entries, and the second column says
which agent. Walk the three colours:

Blue, *stopped on the host*. Switch `fetch_url` off in the Policy tab, then
ask Finance to fetch a URL. The request never reached a sandbox. Say that this
is the **weakest** control on the screen: it is the agent's own harness
declining, and a harness is exactly the layer you cannot trust. It is blue for
a reason. Switch it back on afterwards, because every profile ships with the
same tools enabled on purpose.

Red, *blocked by policy*. What you just did with the api-key file. MXC
refused it. This one holds.

Amber, *refused to start*. Turn on `advanced.sendUnsupportedAnyway`, add a
deny path, and ask that agent to do anything at all. The binary rejects the
configuration and names the offending field.

### Close with the workspace

Ask Paperwork: **"tidy up your workspace folder, sort the notes and the
spreadsheets."**

It reads each file and moves it, one sandbox per step, writing only inside
`${workspace}` because that is the one place it has write access. Then take
`${workspace}` out of Paperwork's write paths, ask again, and watch the same
request die at the first write.

That is the whole argument in one gesture: the agent did not change, the
policy did.

## If it goes wrong

Every tool call failing with *refused to start* usually means a knob in
that agent's profile that this host cannot build. The Run tab names the
offending field. Clear that field, do not fight it.

No agent responding at all is Lemonade, not MXC. Check the Settings tab. It
reports whether the model answered. One agent behaving oddly while the others
are fine is its profile, not the model, and the Agents tab puts a dot on any
agent the startup audit complained about.

`wxc-exec` not found should not happen any more, because the executables ship in
`bin\`. If it does, `mxc.binDir` in `config.json` has been pointed somewhere
else. Set it back to `bin`, or set `MXC_BIN_DIR`, and restart.

And if a refusal does not happen when you said it would, say so out loud and
go look at why. A workshop about containment that papers over a failed
containment check has taught the room the opposite of the intended lesson.
