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
    wrong, and the script can be as long and as nested as it likes.

    $ProgressPreference is silenced first, and that is not cosmetic. With a
    redirected stderr PowerShell serialises its streams as CLIXML, and the
    first thing it emits is a progress record for "Preparing modules for first
    use" - roughly 300 characters of XML before any real output. On a refusal
    that XML is what lands in the run's detail field, and detail is truncated
    at 400 characters on its way to the model. The agent would be told it was
    refused and then handed progress-bar XML as the reason.
    """
    script = "$ProgressPreference='SilentlyContinue';" + script
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return cmd_line(_q(PWSH % _windir()), "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc)


def ps_write(path, content):
    """Write arbitrary text to a file, through PowerShell, with the payload
    base64'd so no prose ever has to survive a layer of shell quoting.

    Shared by write_file and by the two triage tools that produce drafts.

    A cmd-only version of this - echo base64 into a scratch file, certutil
    -decode it back - looks attractive while PowerShell is unavailable, and is
    a dead end: wxc-exec parses `process.commandLine` itself to split the
    executable from its arguments, and a line containing ( ) > or && comes
    back as CreateProcessW failed: Access is denied. Anything with shell
    structure in it has to go through -EncodedCommand, which is what shell_ps
    already does."""
    b = base64.b64encode((content or "").encode("utf-8")).decode("ascii")
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "$b=[Convert]::FromBase64String('%s');"
        "[IO.File]::WriteAllBytes(%s,$b);"
        "Write-Output ('wrote ' + $b.Length + ' bytes to ' + %s)"
        % (b, _psq(path), _psq(path)))


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

class Tool(object):
    def __init__(self, name, description, parameters, build, shell="cmd",
                 needs=None, danger=False, agent="computer-assist"):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.build = build
        self.shell = shell
        self.needs = needs or []
        self.danger = danger
        # Which subagent may ask for this. "*" means any - fetch_url is shared
        # because "can this thing reach the network" is a question worth
        # asking of every agent, not just the one that manages files.
        self.agent = agent

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

def _b_list_files(a, ctx=None):
    path = a.get("path") or "."
    return shell_cmd("dir /b /a %s" % _q(path))


def _b_read_file(a, ctx=None):
    path = a.get("path") or ""
    n = int(a.get("maxLines") or 200)
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-Content -LiteralPath %s -TotalCount %d -ErrorAction Stop | "
        "ForEach-Object { $_ }" % (_psq(path), n))


def _b_write_file(a, ctx=None):
    return ps_write(a.get("path") or "", a.get("content") or "")


def _b_move_file(a, ctx=None):
    return shell_cmd("move /y %s %s" % (_q(a.get("source") or ""),
                                        _q(a.get("destination") or "")))


def _b_device_info(a, ctx=None):
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


def _b_disk_space(a, ctx=None):
    return shell_ps(
        "[IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady } | "
        "ForEach-Object { [ordered]@{ drive=$_.Name; type=$_.DriveType.ToString();"
        " totalGB=[math]::Round($_.TotalSize/1GB,1);"
        " freeGB=[math]::Round($_.AvailableFreeSpace/1GB,1);"
        " percentFree=[math]::Round(100*$_.AvailableFreeSpace/$_.TotalSize,1) } } | "
        "ConvertTo-Json -Compress")


def _b_list_processes(a, ctx=None):
    top = int(a.get("top") or 15)
    return shell_ps(
        "Get-Process | Sort-Object -Property WorkingSet64 -Descending | "
        "Select-Object -First %d | ForEach-Object { [ordered]@{ name=$_.ProcessName;"
        " id=$_.Id; memoryMB=[math]::Round($_.WorkingSet64/1MB,1) } } | "
        "ConvertTo-Json -Compress" % top)


def _b_fetch_url(a, ctx=None):
    url = a.get("url") or ""
    return cmd_line(_q(CURL % _windir()), "-sS", "--max-time", "10", "-L", _q(url))


def _b_run_command(a, ctx=None):
    return shell_cmd(a.get("command") or "")


def _psq(s):
    return "'" + str(s).replace("'", "''") + "'"


# -- mail and calendar ------------------------------------------------------
#
# These are PowerShell, not cmd, and that was measured rather than assumed.
# `dir` fails inside a sandbox on this hardware - verify.py reports Tool:
# list_files as a refusal, and has done since before any of this existed -
# because cmd's directory enumeration asks for an access an AppContainer read
# grant does not carry. Get-ChildItem on the same granted folder is fine.
# Run verify.py on your own box before changing any of this back.
#
# Mailbox paths are assembled here but NOT validated here, exactly as in the
# file tools above. If the model asks for a folder it has no grant for, the
# request goes to MXC and MXC refuses it. Checking it in this layer would be
# checking in the one layer the whole workshop argues you cannot trust.

def _mail_dir(ctx, *parts):
    base = (ctx or {}).get("mailbox") or os.path.join(os.getcwd(), "mailbox")
    return os.path.join(base, *[str(p) for p in parts if p])


def _msg_path(ctx, folder, msg_id):
    name = str(msg_id or "")
    if not name.lower().endswith(".json"):
        name += ".json"
    return _mail_dir(ctx, folder or "inbox", name)


def _b_list_messages(a, ctx=None):
    # Summary lines, not bare file names. A triage agent that has to read
    # every message to find out who sent it burns its whole tool budget on
    # the listing, and maxToolCallsPerTurn is 8.
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-ChildItem -LiteralPath %s -Filter *.json -File | "
        "Sort-Object Name -Descending | ForEach-Object {"
        "  $m = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json;"
        "  if ($m.tombstone) {"
        "    '{0} | (filed under {1})' -f $_.BaseName, $m.movedTo }"
        "  else {"
        "    '{0} | {1} | {2} | {3}' -f $_.BaseName, $m.date, $m.from, $m.subject }"
        "}" % _psq(_mail_dir(ctx, a.get("folder") or "inbox")))


def _b_read_message(a, ctx=None):
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-Content -LiteralPath %s -Raw"
        % _psq(_msg_path(ctx, a.get("folder") or "inbox", a.get("id"))))


def _b_search_mail(a, ctx=None):
    # Returns the matching ids and subjects, so the agent can decide what is
    # worth a read_message call rather than guessing from a file name.
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-ChildItem -LiteralPath %s -Filter *.json -File | ForEach-Object {"
        "  $raw = Get-Content -LiteralPath $_.FullName -Raw;"
        "  if ($raw -match [regex]::Escape(%s)) {"
        "    $m = $raw | ConvertFrom-Json;"
        "    '{0} | {1} | {2}' -f $_.BaseName, $m.from, $m.subject } }"
        % (_psq(_mail_dir(ctx, a.get("folder") or "inbox")),
           _psq(str(a.get("query") or ""))))


def _ps_file_message(src, dest_dir, dest_file, what):
    """Copy a message into another folder and tombstone the original.

    Copy-and-tombstone rather than Move-Item, because this tier cannot delete.
    A BFS read-write grant carries create and write but not DELETE, so
    Move-Item and cmd's `move` both come back 'Access is denied' even when the
    source and destination are inside the SAME granted folder. That is a
    property of the host, measured on it, not a policy anybody chose - and it
    is why the shipped move_file tool has never had a passing verify check.

    The tombstone is a real file saying where the message went. Nothing here
    pretends the original was removed, because it was not, and a triage pane
    that quietly hid a file the sandbox could not actually delete would be
    exactly the kind of lie this app exists to avoid. list_messages and the
    mailbox pane both skip tombstones, and both say so.

    Both ends still need their own write grant, so the policy lesson is
    unchanged: no grant on the destination, no filing.
    """
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        # Guarded, not -Force. New-Item -Force on a directory that already
        # exists still asks for create rights on the PARENT, and the parent
        # here is the mailbox root, which no sensible policy grants. The
        # archive folder is shipped, so this only ever fires for a new label.
        "if (-not (Test-Path -LiteralPath {dest_dir})) {{"
        "  New-Item -ItemType Directory -Path {dest_dir} | Out-Null }};"
        "Copy-Item -LiteralPath {src} -Destination {dest_file} -Force;"
        "$t = @{{ id = [IO.Path]::GetFileNameWithoutExtension({src});"
        "        tombstone = $true; movedTo = {what} }} | ConvertTo-Json -Compress;"
        "[IO.File]::WriteAllText({src}, $t);"
        "Write-Output ('filed under ' + {what})".format(
            src=_psq(src), dest_dir=_psq(dest_dir), dest_file=_psq(dest_file),
            what=_psq(what)))


def _b_archive_message(a, ctx=None):
    folder = a.get("folder") or "inbox"
    name = os.path.basename(_msg_path(ctx, folder, a.get("id")))
    return _ps_file_message(_msg_path(ctx, folder, a.get("id")),
                            _mail_dir(ctx, "archive"),
                            _mail_dir(ctx, "archive", name), "archive")


def _b_label_message(a, ctx=None):
    folder = a.get("folder") or "inbox"
    label = str(a.get("label") or "untagged")
    name = os.path.basename(_msg_path(ctx, folder, a.get("id")))
    return _ps_file_message(_msg_path(ctx, folder, a.get("id")),
                            _mail_dir(ctx, "labels", label),
                            _mail_dir(ctx, "labels", label, name),
                            "labels/" + label)


def _b_draft_reply(a, ctx=None):
    draft = {
        "id": _slug(a.get("subject") or "draft"),
        "inReplyTo": a.get("id") or "",
        "to": a.get("to") or "",
        "subject": a.get("subject") or "",
        "body": a.get("body") or "",
        "status": "draft - not sent",
    }
    return ps_write(_msg_path(ctx, "drafts", draft["id"]),
                    json.dumps(draft, indent=2))


def _b_list_events(a, ctx=None):
    day = a.get("date")
    if day:
        return shell_ps(
            "$ErrorActionPreference='Stop';"
            "Get-Content -LiteralPath %s -Raw"
            % _psq(_mail_dir(ctx, "calendar", str(day) + ".json")))
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-ChildItem -LiteralPath %s -Filter *.json -File | Sort-Object Name | "
        "ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }"
        % _psq(_mail_dir(ctx, "calendar")))


def _b_find_free_slot(a, ctx=None):
    # Same read as list_events. The gap-finding is the model's job, not a
    # shell one-liner's - and doing it in the sandbox would mean the model
    # trusting an answer it cannot check.
    return _b_list_events(a, ctx)


def _b_draft_invite(a, ctx=None):
    invite = {
        "id": _slug("invite-" + (a.get("title") or "meeting")),
        "title": a.get("title") or "",
        "date": a.get("date") or "",
        "start": a.get("start") or "",
        "end": a.get("end") or "",
        "attendees": a.get("attendees") or "",
        "status": "draft - not sent",
    }
    return ps_write(_msg_path(ctx, "drafts", invite["id"]),
                    json.dumps(invite, indent=2))


def _slug(s):
    out = "".join(c if (c.isalnum() or c in "-_") else "-"
                  for c in str(s).lower())[:60].strip("-")
    return out or "draft"


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
         _b_fetch_url, shell="curl", needs=["outbound network set to allow"],
         agent="*"),

    Tool("run_command", "Run an arbitrary Windows command. Off by default.",
         {"properties": {"command": _str("The command line to run under cmd.exe.")},
          "required": ["command"]},
         _b_run_command, shell="cmd", needs=["whatever the command touches"],
         danger=True),

    # -- triage: mail -------------------------------------------------------

    Tool("list_messages", "List the message ids in a mailbox folder. Start here, "
                          "then read the ones that look relevant.",
         {"properties": {"folder": _str("inbox, archive, drafts or private. "
                                        "Default inbox.")},
          "required": []},
         _b_list_messages, shell="powershell", agent="triage",
         needs=["read access to that mailbox folder"]),

    Tool("read_message", "Read one message as JSON: sender, subject, date, "
                         "labels and full body.",
         {"properties": {"id": _str("The message id, as returned by "
                                    "list_messages, with or without .json."),
                         "folder": _str("Which folder it is in. Default inbox.")},
          "required": ["id"]},
         _b_read_message, shell="powershell", agent="triage",
         needs=["read access to that mailbox folder"]),

    Tool("search_mail", "Find messages containing a phrase. Returns the file "
                        "names that matched, not the messages themselves.",
         {"properties": {"query": _str("The phrase to look for. Case insensitive."),
                         "folder": _str("Which folder to search. Default inbox.")},
          "required": ["query"]},
         _b_search_mail, shell="powershell", agent="triage",
         needs=["read access to that mailbox folder"]),

    Tool("archive_message", "Move a message out of the inbox into archive.",
         {"properties": {"id": _str("The message id to archive."),
                         "folder": _str("Where it is now. Default inbox.")},
          "required": ["id"]},
         _b_archive_message, shell="powershell", agent="triage",
         needs=["write access to the source folder AND to the archive folder"]),

    Tool("label_message", "File a message under a label.",
         {"properties": {"id": _str("The message id to file."),
                         "label": _str("The label to file it under."),
                         "folder": _str("Where it is now. Default inbox.")},
          "required": ["id", "label"]},
         _b_label_message, shell="powershell", agent="triage",
         needs=["write access to the source folder AND to the labels folder"]),

    Tool("draft_reply", "Write a reply into the drafts folder. This never sends "
                        "anything - the person sends it themselves.",
         {"properties": {"id": _str("The message id being replied to."),
                         "to": _str("Recipient address."),
                         "subject": _str("Subject line."),
                         "body": _str("The full text of the reply.")},
          "required": ["subject", "body"]},
         _b_draft_reply, shell="powershell", agent="triage",
         needs=["write access to the drafts folder"]),

    # -- triage: calendar ---------------------------------------------------

    Tool("list_events", "Read the calendar. Without a date this returns every "
                        "day held, each tagged with its file name.",
         {"properties": {"date": _str("A single day as YYYY-MM-DD. Omit for "
                                      "everything.")},
          "required": []},
         _b_list_events, shell="powershell", agent="triage",
         needs=["read access to the calendar folder"]),

    Tool("find_free_slot", "Read the calendar so you can work out where the gaps "
                           "are. Returns the booked events, not the gaps.",
         {"properties": {"date": _str("A single day as YYYY-MM-DD. Omit for "
                                      "everything.")},
          "required": []},
         _b_find_free_slot, shell="powershell", agent="triage",
         needs=["read access to the calendar folder"]),

    Tool("draft_invite", "Write a meeting invitation into drafts. This never "
                         "sends anything.",
         {"properties": {"title": _str("Meeting title."),
                         "date": _str("Day as YYYY-MM-DD."),
                         "start": _str("Start time as HH:MM."),
                         "end": _str("End time as HH:MM."),
                         "attendees": _str("Comma-separated addresses.")},
          "required": ["title", "date", "start"]},
         _b_draft_invite, shell="powershell", agent="triage",
         needs=["write access to the drafts folder"]),
]

BY_NAME = {t.name: t for t in CATALOGUE}


def for_agent(agent_id):
    """Every tool a subagent is allowed to ask for, before the policy gate.

    Two separate questions, and conflating them is how you end up unable to
    explain a refusal: this one is "does this agent have hands of this shape
    at all", and policy.tools is "is this particular hand switched off right
    now". A triage agent never sees list_processes; it is not off, it is not
    part of what triage is."""
    if not agent_id:
        return list(CATALOGUE)
    return [t for t in CATALOGUE if t.agent in ("*", agent_id)]


def enabled_tools(policy, agent_id=None):
    gate = (policy or {}).get("tools") or {}
    return [t for t in for_agent(agent_id) if gate.get(t.name, not t.danger)]


def schemas(policy, agent_id=None):
    return [t.schema() for t in enabled_tools(policy, agent_id)]


def describe(policy, agent_id=None):
    """For the Control Panel: every tool, whether it is on, and what it needs."""
    gate = (policy or {}).get("tools") or {}
    out = []
    for t in for_agent(agent_id):
        out.append({
            "name": t.name,
            "description": t.description,
            "enabled": bool(gate.get(t.name, not t.danger)),
            "shell": t.shell,
            "needs": t.needs,
            "danger": t.danger,
            "agent": t.agent,
            "parameters": t.parameters.get("properties", {}),
        })
    return out


def build_command(name, arguments, ctx=None):
    t = BY_NAME.get(name)
    if not t:
        raise KeyError(name)
    return t.build(arguments or {}, ctx), t
