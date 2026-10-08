"""
core/tools.py - the agent's hands.

Every tool is one short Windows command. Every tool call spawns its own
one-shot MXC sandbox, runs that command inside it, and throws the sandbox
away. Nothing persists between calls, so the policy that applies is always
the policy that was on disk when the call started.

Two deliberate decisions worth defending out loud:

  * Paths are NOT validated here. If the model asks to read a file it should
    not be able to read, the request goes straight through to MXC and MXC
    refuses it. Checking in the agent would be checking in exactly the layer
    the whole session argues you cannot trust.

  * Commands are built with explicit, fully quoted executable paths and, for
    anything with structure, PowerShell's -EncodedCommand. wxc-exec rejects
    unquoted Windows paths containing spaces at parse time, and -EncodedCommand
    sidesteps every layer of quoting between here and the shell.
"""

import base64
import json
import os

CMD = r"%s\System32\cmd.exe"
PWSH = r"%s\System32\WindowsPowerShell\v1.0\powershell.exe"
CURL = r"%s\System32\curl.exe"


def _windir():
    return os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"


def _q(s):
    return '"%s"' % str(s).replace('"', '""')


def cmd_line(*parts):
    return " ".join(parts)


def shell_cmd(inner):
    return cmd_line(_q(CMD % _windir()), "/d", "/c", inner)


def shell_ps(script):
    """PowerShell with the script base64'd as UTF-16LE. No quoting to get
    wrong, and the script can be as long and as nested as it likes."""
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return cmd_line(_q(PWSH % _windir()), "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

class Tool(object):
    def __init__(self, name, description, parameters, build, shell="cmd",
                 needs=None, danger=False):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.build = build
        self.shell = shell
        self.needs = needs or []
        self.danger = danger

    def schema(self):
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object",
                           "properties": self.parameters.get("properties", {}),
                           "required": self.parameters.get("required", [])},
        }}


def _str(desc):
    return {"type": "string", "description": desc}


# -- builders ---------------------------------------------------------------

def _b_list_files(a):
    path = a.get("path") or "."
    return shell_cmd("dir /b /a %s" % _q(path))


def _b_read_file(a):
    path = a.get("path") or ""
    n = int(a.get("maxLines") or 200)
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-Content -LiteralPath %s -TotalCount %d -ErrorAction Stop | "
        "ForEach-Object { $_ }" % (_psq(path), n))


def _b_write_file(a):
    path = a.get("path") or ""
    content = a.get("content") or ""
    b = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "$b=[Convert]::FromBase64String('%s');"
        "[IO.File]::WriteAllBytes(%s,$b);"
        "Write-Output ('wrote ' + $b.Length + ' bytes to ' + %s)"
        % (b, _psq(path), _psq(path)))


def _b_move_file(a):
    return shell_cmd("move /y %s %s" % (_q(a.get("source") or ""),
                                        _q(a.get("destination") or "")))


def _b_device_info(a):
    # Pure .NET only. No WMI, no CIM, no RPC - those need privileges an
    # AppContainer does not have, and failing for that reason would teach
    # the wrong lesson.
    return shell_ps(
        "$o=[ordered]@{"
        "  machine=[Environment]::MachineName;"
        "  user=[Environment]::UserName;"
        "  os=[Environment]::OSVersion.VersionString;"
        "  is64bit=[Environment]::Is64BitOperatingSystem;"
        "  processors=[Environment]::ProcessorCount;"
        "  cpu=$env:PROCESSOR_IDENTIFIER;"
        "  arch=$env:PROCESSOR_ARCHITECTURE;"
        "  clr=[Environment]::Version.ToString();"
        "  uptimeHours=[math]::Round([Environment]::TickCount64/3600000,1);"
        "  workingSet=[Environment]::WorkingSet"
        "}; $o | ConvertTo-Json -Compress")


def _b_disk_space(a):
    return shell_ps(
        "[IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady } | "
        "ForEach-Object { [ordered]@{ drive=$_.Name; type=$_.DriveType.ToString();"
        " totalGB=[math]::Round($_.TotalSize/1GB,1);"
        " freeGB=[math]::Round($_.AvailableFreeSpace/1GB,1);"
        " percentFree=[math]::Round(100*$_.AvailableFreeSpace/$_.TotalSize,1) } } | "
        "ConvertTo-Json -Compress")


def _b_list_processes(a):
    top = int(a.get("top") or 15)
    return shell_ps(
        "Get-Process | Sort-Object -Property WorkingSet64 -Descending | "
        "Select-Object -First %d | ForEach-Object { [ordered]@{ name=$_.ProcessName;"
        " id=$_.Id; memoryMB=[math]::Round($_.WorkingSet64/1MB,1) } } | "
        "ConvertTo-Json -Compress" % top)


def _b_fetch_url(a):
    url = a.get("url") or ""
    return cmd_line(_q(CURL % _windir()), "-sS", "--max-time", "10", "-L", _q(url))


def _b_run_command(a):
    return shell_cmd(a.get("command") or "")


def _psq(s):
    return "'" + str(s).replace("'", "''") + "'"


CATALOGUE = [
    Tool("list_files", "List the files and folders at a path on this machine.",
         {"properties": {"path": _str("Absolute Windows path to list.")},
          "required": ["path"]},
         _b_list_files, shell="cmd", needs=["read access to that path"]),

    Tool("read_file", "Read the contents of a text file.",
         {"properties": {"path": _str("Absolute Windows path of the file."),
                         "maxLines": {"type": "integer",
                                      "description": "How many lines to read. Default 200."}},
          "required": ["path"]},
         _b_read_file, shell="powershell", needs=["read access to that file"]),

    Tool("write_file", "Create or overwrite a text file.",
         {"properties": {"path": _str("Absolute Windows path to write."),
                         "content": _str("The full text to write.")},
          "required": ["path", "content"]},
         _b_write_file, shell="powershell", needs=["write access to that path"]),

    Tool("move_file", "Move or rename a file.",
         {"properties": {"source": _str("Absolute path of the file to move."),
                         "destination": _str("Absolute destination path.")},
          "required": ["source", "destination"]},
         _b_move_file, shell="cmd",
         needs=["write access to both the source and the destination"]),

    Tool("device_info", "Get basic facts about this device: OS version, CPU, "
                        "memory in use, uptime.",
         {"properties": {}, "required": []},
         _b_device_info, shell="powershell", needs=["PowerShell inside the sandbox"]),

    Tool("disk_space", "Report free and total space on every ready drive.",
         {"properties": {}, "required": []},
         _b_disk_space, shell="powershell", needs=["PowerShell inside the sandbox"]),

    Tool("list_processes", "List the processes using the most memory.",
         {"properties": {"top": {"type": "integer",
                                 "description": "How many to list. Default 15."}},
          "required": []},
         _b_list_processes, shell="powershell",
         needs=["process enumeration, which an AppContainer may restrict"]),

    Tool("fetch_url", "Fetch a URL over the network. Use this to check whether "
                      "the device can reach the internet.",
         {"properties": {"url": _str("Full http or https URL.")},
          "required": ["url"]},
         _b_fetch_url, shell="curl", needs=["outbound network set to allow"]),

    Tool("run_command", "Run an arbitrary Windows command. Off by default.",
         {"properties": {"command": _str("The command line to run under cmd.exe.")},
          "required": ["command"]},
         _b_run_command, shell="cmd", needs=["whatever the command touches"],
         danger=True),
]

BY_NAME = {t.name: t for t in CATALOGUE}


def enabled_tools(policy):
    gate = (policy or {}).get("tools") or {}
    return [t for t in CATALOGUE if gate.get(t.name, not t.danger)]


def schemas(policy):
    return [t.schema() for t in enabled_tools(policy)]


def describe(policy):
    """For the Control Panel: every tool, whether it is on, and what it needs."""
    gate = (policy or {}).get("tools") or {}
    out = []
    for t in CATALOGUE:
        out.append({
            "name": t.name,
            "description": t.description,
            "enabled": bool(gate.get(t.name, not t.danger)),
            "shell": t.shell,
            "needs": t.needs,
            "danger": t.danger,
            "parameters": t.parameters.get("properties", {}),
        })
    return out


def build_command(name, arguments):
    t = BY_NAME.get(name)
    if not t:
        raise KeyError(name)
    return t.build(arguments or {}), t
