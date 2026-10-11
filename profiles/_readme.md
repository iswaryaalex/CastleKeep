# profiles/

Four agents, four ordinary jobs. Same model, same loop, same nine tools. The
only thing that differs between them is the sandbox each one's tool calls run
inside.

| agent       | job                          | can read                       | can write | network |
|-------------|------------------------------|--------------------------------|-----------|---------|
| Diagnostics | how this machine is doing    | the device, no files           | nothing   | no      |
| Finance     | rates and prices             | no files                       | nothing   | yes     |
| Health      | your clinic notes            | one folder, `workspace\clinic` | nothing   | no      |
| Paperwork   | forms, bills and filing      | the whole workspace            | workspace | no      |

Read the last two columns together. Finance is the only agent that can reach
the internet and it is also the only agent with nothing of yours to send. That
pairing is the entire argument, and it is the reason the grid has four cells
instead of two.

The jobs were picked so the pairing lands rather than being a technicality.
The money agent is the one allowed online, and it is given no statements and no
spreadsheets, so the worst it can do is fetch a page and be wrong about it.
The agent that reads medical notes has no socket at all. The agent that can
overwrite a file can only see the folder it is allowed to overwrite.

Two pairs differ by exactly one thing each, which is what makes them worth
putting side by side. Diagnostics and Finance differ only on network. Health
and Paperwork differ only on write.

## The tool gate is the same in all four

Every profile has the identical `tools` block: everything on except
`run_command`. That is deliberate. The `tools` switch is a host-side gate, so a
tool turned off there never reaches a sandbox and MXC never sees it. If the
profiles differed there, the four boxes above would be enforced by an `if`
statement in Python, and the demo would prove nothing.

Leaving the gate open means Health really does call `write_file`, and the
refusal you see really did come from the container. Ask any of them to do
something outside its box and watch where the "no" comes from.

## What you will actually see when one is refused

At the BaseContainer tier a path you were not granted was never mapped into the
container, so the process is not told it is forbidden. The file simply is not
there, and the error reads `The system cannot find the file specified`, not
`Access is denied`. This surprises people. It is the same wall either way.

## A profile is a policy

Every field `COMPILED.md` documents works here and means the same thing. The
extra keys below ride along: the normaliser keeps top-level keys it does not
recognise, and the compiler reads only the sections it knows, so `title`,
`critter`, `persona` and the rest never reach the wire.

`policy.json` in the root is not one of these. No agent uses it. It is the
host-wide default that the Run tab's dry run, the dialect negotiation at
startup and `verify.py` compile when the claim is about the machine rather
than about an agent, and it stays in the Policy tab's picker under that name.

## Paths

`${workspace}` and the other variables expand the same way they do in
`policy.json`. See the `_readme` at the top of that file for the full list.

`workspace\clinic` is synthetic sample data written for this workshop. Every
name, date and number in it was invented. Point Health at a folder of real
notes only if you mean it, and never at one you would mind an agent reading
aloud.

## Each profile has a `task` and a `boundary`

`task` is the one-line label the agent bar shows: what the agent is for. It is
checked at build time for policy words and rejected if it has any, because the
Mission panel and the comparison card already say what an agent may do, and
saying it a third time in the place where you are choosing a job is noise.

`boundary` is the short form of the policy, and it is checked against the real
`paths` and `network` values. Widen a grant without updating the label and the
build stops.

## One profile has `named`

`diagnostics.json` sets `"named": true`, and it is the only one that may. That
is the agent the launch wizard names, so it answers on screen and in its own
system prompt to whatever was typed there. The other three take their `title`.

The rule lives in one function, `App.agent_label`, so the agent bar, the
transcript, the Mission panel and the roster each agent is handed about the
other three all give the same answer. If two profiles set `named`, the startup
audit says so and the app renders the complaint rather than crashing.

Give the dragon's job to a different profile and move the key with it. Leave
it on two files and the room is told to switch to an agent that is not in the
bar under that label.

## The `order` of the bar

`core/profiles.py` has an `ORDER` list naming the four. Anything in `profiles\`
that it does not name still loads, alphabetically, after them. The folder is
scanned rather than hardcoded, so a fifth file is a fifth agent with no Python
touched.

## Retiring a profile

Set `"superseded": true` and the loader skips the file. `records.json`,
`tidy.json` and `scout.json` are the earlier versions of Health, Paperwork and
Finance and are marked that way, which is why there are seven files here and
four agents. They can be deleted whenever you like.
