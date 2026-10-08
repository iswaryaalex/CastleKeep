# bin: the MXC executables

Everything CastleKeep shells out to lives here, so the folder is portable.
Copy `castlekeep\` to another machine and it still has an executor; nothing
depends on a sibling `node_modules` any more.

`config.json` ships with `mxc.binDir = "bin"`, and `core/mxc.py` also looks
here on its own even if that value is edited away.

## What is here

```
bin\x64\        the executables for 64-bit Intel and AMD. This is the one
bin\arm64\      the same set for ARM64 Windows
LICENSE.md      Microsoft's licence. It travels with the binaries.
MXC-SDK-README.md   the SDK's own documentation, verbatim
```

Inside each arch folder, the one CastleKeep actually invokes is
**`wxc-exec.exe`**. The rest are its dependencies and are resolved relative to
it, which is why the whole folder is copied rather than the single file:

| file | what it is |
| --- | --- |
| `wxc-exec.exe` | the executor. Takes a JSON config, builds a container, runs one command, tears it down. |
| `wxc-host-prep.exe` | one-time host preparation |
| `wxc-windows-sandbox-daemon.exe`, `wxc-windows-sandbox-guest.exe` | the Windows Sandbox backend |
| `wxc-wslc-daemon.exe`, `wslcsdk.dll`, `lxc-exec` | the WSL container backend |
| `winhttp-proxy-shim.exe`, `wxc-test-proxy.exe`, `unix-test-proxy` | network interception |
| `plm.exe`, `mxc-diagnostic-console.exe` | lifecycle and diagnostics |

CastleKeep uses only `--probe`, `--dry-run` and a base64 config. It never
passes `--audit`, which turns restrictions off.

## Provenance

Copied from `@microsoft/mxc-sdk` as installed in the parent folder. Two files
in that package were deliberately **not** copied: a `wxc-exec.t3.bak` left over
from a local binary swap, and a `probe-*.json` that was cached for one specific
machine name. Shipping either would mean shipping somebody else's host.

The version here is whatever was installed at copy time. If a newer SDK lands,
replace the arch folder wholesale rather than individual files, because the executor
and its daemons are built together.

## Checking it works

```
& ".\bin\x64\wxc-exec.exe" --probe
```

That prints the containment tier this machine can actually give you. If it
does not run, nothing else in CastleKeep will either, and `python verify.py`
will say so in more detail.
