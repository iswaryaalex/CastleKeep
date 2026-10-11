# What a policy becomes

A policy file is not the file MXC reads. CastleKeep compiles it into an
`MXCConfiguration` document and hands that to `wxc-exec.exe` as base64 on the
command line, one fresh document per tool call. This page is the mapping.

There are five policy files in a stock install and they all compile through
this same page. Four of them are the agents' own, one per file in `profiles\`,
and those are what every tool call uses. The fifth is `policy.json` in the
root. No agent uses it. It is the host-wide default that the Run tab's dry
run, the dialect negotiation at startup and `verify.py` compile when the claim
being made is about the machine rather than about an agent.

An agent's profile carries a few keys this page does not list, for its name,
its creature, its tagline and its starter questions. The compiler reads only
the sections below and leaves the rest alone, which is why a profile can be a
policy without being a different kind of file.

You never have to trust this page. The Policy tab has a button marked **Show
the JSON that MXC actually receives**, and the Run tab prints the exact
document that was sent alongside whatever the sandbox did with it. Both follow
the agent picker, so what you are shown is the document that agent's next call
will send.

## The mapping

| policy field | MXCConfiguration | Notes |
|---|---|---|
| `containment` | `containment` | `processcontainer` is the only value worth setting here. |
| `paths.read` | `filesystem.readonlyPaths` | Variables expanded first. A path also listed under `write` is dropped from this list rather than sent twice. |
| `paths.write` | `filesystem.readwritePaths` | |
| `paths.deny` | `filesystem.deniedPaths` | **Usually dropped.** See below. |
| `network.outbound` | `network.egress.default` | `deny` / `allow`. Legacy dialect: `network.defaultPolicy` = `block` / `allow`. |
| `network.localNetwork` | `network.ingress.default` and `ingress.hostLoopback` | Legacy dialect: `network.allowLocalNetwork`. |
| `ui.allowWindows` | `ui.disable` | **Inverted.** `allowWindows: false` compiles to `disable: true`. |
| `ui.clipboard` | `ui.clipboard` | Straight through: `none`, `read`, `write`, `all`. |
| `ui.allowInputInjection` | `ui.injection` | |
| `limits.timeoutMs` | `process.timeout` | |
| `advanced.learningMode` | `processContainer.learningMode` | |
| `advanced.leastPrivilege` | `processContainer.leastPrivilege` | |
| `advanced.captureDenials` | `processContainer.captureDenials` | Needs a capture directory and native learning-mode support. |
| `advanced.allowDaclMutation` | `fallback.allowDaclMutation` | Permission to rewrite real ACEs on disk when the run lands on the DACL fallback. |
| `tools.*` | *nothing* | Host-side gate. A tool switched off here never reaches `wxc-exec` at all, so MXC never gets to refuse it. The four shipped profiles set this block identically on purpose: it is what makes the difference between the agents a containment result rather than an `if` statement. |

Two fields in the wire document have no source in the policy. `version` carries
the schema version, and `lifecycle.destroyOnExit` is always `true`. There is
no setting to make a CastleKeep sandbox outlive its one command, on purpose.

## Three fields that probably will not survive

CastleKeep probes the host at startup and leaves out fields it knows this
machine cannot enforce, adding a note next to the field in the Policy tab.
Three come up often.

`paths.deny` is rejected outright on the AppContainer backends. The refusal
text is "Paths are denied by default unless granted via readwritePaths or
readonlyPaths". That is the model talking, and it is a reasonable one. If you
want something unreachable, do not grant it. Note that the binary *refuses the
whole run* rather than ignoring the field, so a deny list you did not notice
is a sandbox that will not start.

Per-host network rules do not exist on Windows. Outbound is all or nothing.
There is nowhere to put an allowlist of hostnames, so CastleKeep does not offer
one.

`ingress.hostLoopback: allow` is unsupported on the AppContainer fallback.
This is the reason the agent loop and Lemonade both run on the host: a
sandboxed process on this tier cannot be relied on to reach a loopback port, so
a design that needs it is a design that breaks on most machines.

## The network dialect

`wxc-exec` has accepted two different network shapes across versions, and
mixing them is a parse error. At startup CastleKeep sends one `--dry-run` of
each and keeps whichever is accepted: modern (`egress`/`ingress`) first, then
legacy (`defaultPolicy`/`allowLocalNetwork`).

If both are rejected, the dialect is `none` and **the run carries no network
policy at all**. CastleKeep says so loudly, in red, and the Control Panel
reports outbound as "not enforced on this host" rather than repeating what the
policy asked for. A policy that asked for deny and got dropped is the
single most dangerous state this app can be in, so it is the one state that
refuses to be quiet about itself.

## Why send a field you know will be refused

Set `advanced.sendUnsupportedAnyway` to `true` and CastleKeep stops filtering.
Unsupported fields go on the wire, `wxc-exec` refuses the run, and the Run tab
shows you the structured refusal with `offendingField` pointing at the thing
you set. It is slower and it breaks every tool call, which is exactly why it
is useful in a room: it is the difference between being told a field is
unsupported and watching the binary say it.
