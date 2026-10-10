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
import time

from . import agents as agents_mod

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

    Shared by write_file and by every tool that produces a draft or an invite.

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
                 needs=None, danger=False, agent="computer-assist", paths=None,
                 folder_enum=False):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.build = build
        self.shell = shell
        self.needs = needs or []
        self.danger = danger
        # True for the record tools, whose 'folder' argument can only ever be
        # one of three names and which one depends on who is asking.
        self.folder_enum = folder_enum
        # fn(args, ctx) -> {"read": [...], "write": [...]}: the paths this call
        # is about to touch. Used ONLY to explain a refusal after MXC has
        # already made it - never to pre-empt one. The difference matters:
        # checking here would be checking in the layer the whole exercise
        # argues you cannot trust, but staying silent afterwards leaves the
        # model guessing which grant was missing, and it guesses badly.
        # Windows is no help here - PowerShell reports a refused
        # mailbox\labels as "Access to the path 'C:\Users' is denied".
        self.paths = paths
        # Which subagent may ask for this. A single id, a tuple of ids, or "*"
        # for any. "*" exists because "can this thing reach the network" is a
        # question worth asking of every agent, not just the one that manages
        # files. A tuple exists because the four personas have identically
        # shaped hands - they differ in what their policy grants, which is
        # exactly the distinction worth keeping visible.
        self.agent = agent

    def for_agent(self, agent_id):
        if self.agent == "*":
            return True
        if isinstance(self.agent, (tuple, list, set, frozenset)):
            return agent_id in self.agent
        return self.agent == agent_id

    def agent_label(self):
        """How the Control Panel names the owner of this tool."""
        if self.agent == "*":
            return "*"
        if isinstance(self.agent, (tuple, list, set, frozenset)):
            return ", ".join(sorted(self.agent))
        return self.agent

    def schema(self, agent_id=None):
        props = self.parameters.get("properties", {})
        if self.folder_enum and agent_id:
            # Name the three folders this particular agent actually has,
            # rather than describing them in prose and hoping.
            #
            # Measured, not guessed: asked "what have my vitals done", a 2B
            # model called list_records(folder="health") - the name of the
            # VAULT, which is not a folder at all - got a failure, and retried
            # the identical call. A free-text argument invites that, and no
            # amount of "defaults to your own data folder" in a description
            # competes with an enum the sampler cannot step outside of.
            rec = agents_mod.get(agent_id)
            folders = [f for f in (rec.get("dataFolder"), "invites", "outbox") if f]
            props = dict(props)
            props["folder"] = {
                "type": "string",
                "enum": folders,
                "description": "Which of your folders. '%s' is your own data; "
                               "invites and outbox are what you produce. "
                               "Defaults to '%s'." % (folders[0], folders[0]),
            }
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object",
                           "properties": props,
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
    # Summary lines, not bare file names. An agent that has to read
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
    pretends the original was removed, because it was not, and a mailbox pane
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


# -- the personas' own world ------------------------------------------------
#
# One set of hands, four agents. health, finance, coding and the computer
# assistant all read records and produce invites and drafts; what differs is
# which folder is theirs and what their policy grants them inside it.
#
# The folder is resolved from ctx["agentVault"], which the Agent sets from the
# registry. It is deliberately NOT an argument the model supplies: a persona
# asking to read "../finance/ledger" would be refused by MXC anyway, but
# letting the model name the root at all would make every refusal a story
# about a typo rather than about a grant.
#
# As everywhere else in this file, nothing here validates a path.

def _vault_dir(ctx, *parts):
    base = (ctx or {}).get("agentVault") or ""
    return os.path.join(base, *[str(p) for p in parts if p])


def _data_folder(a, ctx):
    """The folder a record tool is about to read. Defaults to this agent's own
    data folder, so the model does not have to know the name to get started."""
    return a.get("folder") or (ctx or {}).get("agentData") or "records"


def _b_list_records(a, ctx=None):
    # id | date | title, not bare file names. An agent that has to open every
    # record to find out what it is burns its whole tool budget on the listing,
    # and maxToolCallsPerTurn is 8.
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-ChildItem -LiteralPath %s -Filter *.json -File | Sort-Object Name | "
        "ForEach-Object {"
        "  $r = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json;"
        "  '{0} | {1} | {2}' -f $_.BaseName, $r.date, $r.title }"
        % _psq(_vault_dir(ctx, _data_folder(a, ctx))))


def _b_read_record(a, ctx=None):
    name = str(a.get("id") or "")
    if not name.lower().endswith(".json"):
        name += ".json"
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-Content -LiteralPath %s -Raw"
        % _psq(_vault_dir(ctx, _data_folder(a, ctx), name)))


def _b_search_records(a, ctx=None):
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "Get-ChildItem -LiteralPath %s -Filter *.json -File | ForEach-Object {"
        "  $raw = Get-Content -LiteralPath $_.FullName -Raw;"
        "  if ($raw -match [regex]::Escape(%s)) {"
        "    $r = $raw | ConvertFrom-Json;"
        "    '{0} | {1}' -f $_.BaseName, $r.title } }"
        % (_psq(_vault_dir(ctx, _data_folder(a, ctx))),
           _psq(str(a.get("query") or ""))))


def _source_of(ctx):
    return (ctx or {}).get("agentId") or "agent"


def _b_create_invite(a, ctx=None):
    """An invitation, in this agent's own invites folder.

    `source` and `sourceId` are what let the base agent's merge say which
    agent an event came from, and what stop it merging the same invitation
    twice. Stamped here rather than at merge time because the merge reads
    these files across a policy boundary and should not have to infer
    anything about where they came from."""
    source = _source_of(ctx)
    invite = {
        "id": _slug("invite-" + (a.get("title") or "meeting")),
        "kind": "invite",
        "source": source,
        "title": a.get("title") or "",
        "date": a.get("date") or "",
        "start": a.get("start") or "",
        "end": a.get("end") or "",
        "location": a.get("location") or "",
        "attendees": a.get("attendees") or "",
        "notes": a.get("notes") or "",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "waiting for the base agent to pick it up",
    }
    return ps_write(_vault_dir(ctx, "invites", invite["id"] + ".json"),
                    json.dumps(invite, indent=2))


def _b_draft_message(a, ctx=None):
    """A message for the person to send, in this agent's own outbox.

    Written in the same shape as a mailbox message - from, subject, snippet,
    body - so the merge is a straight copy and the global mail view does not
    need to know which agent produced it in order to draw it."""
    source = _source_of(ctx)
    body = a.get("body") or ""
    msg = {
        "id": _slug("msg-" + source + "-" + (a.get("subject") or "message")),
        "kind": "message",
        "source": source,
        "from": "%s agent" % source,
        "to": a.get("to") or "",
        "subject": a.get("subject") or "",
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "snippet": body.strip().replace("\n", " ")[:140],
        "body": body,
        "status": "draft - not sent",
    }
    return ps_write(_vault_dir(ctx, "outbox", msg["id"] + ".json"),
                    json.dumps(msg, indent=2))


# -- the base agent's merge -------------------------------------------------

def _sources(ctx):
    """Every persona's two outgoing folders, as absolute paths.

    Built from the registry, so adding a fifth persona means editing agents.py
    and nothing here.

    Both the agent id and the vault folder name come back, and they are not
    always the same string - the computer assistant has kept the id
    'computer-assist' since before any of this existed and lives in
    vault\\pc-assist. The id is what an event gets stamped with, because that
    is what the UI looks a face and a label up by; the folder name is what a
    refusal has to be reported against, because that is the path somebody has
    to go and put in their policy file."""
    root = (ctx or {}).get("vault") or ""
    out = []
    for rec in agents_mod.REGISTRY:
        v = rec.get("vault")
        if not v:
            continue
        out.append((rec["id"], v, os.path.join(root, v, "invites"),
                    os.path.join(root, v, "outbox")))
    return out


def _b_sync_vaults(a, ctx=None):
    """Collect every persona's invites and drafts into the global view.

    One sandbox, one pass, four personas. Three things are worth defending:

    * Each persona is wrapped in its own try/catch and a failure is RECORDED,
      not raised. If it raised, taking one folder out of the base agent's
      paths.read would stop every other agent reaching the calendar too - the
      demo would over-teach, and the counter would stop for a reason nobody
      could see. Instead the run succeeds, reports which source was refused
      and why, and the bubble says so in the agent's own words.

    * Merging an invite is a read-modify-write of the day file, so the base
      agent needs calendar on BOTH paths.read and paths.write. That is not an
      accident of the implementation - a collector that can write a calendar
      it cannot read would overwrite every event already on it. So the script
      PROVES the calendar is enumerable before it writes a single byte, and
      reports a refusal rather than merging into a file it could not read.

    * Nothing is gated on Test-Path. Test-Path answers "access denied" with
      $false, exactly as it answers "not there" - which would turn a refusal
      into a silent skip and let this tool report a clean zero while the
      policy was stopping it. Every folder is enumerated with -ErrorAction
      Stop instead, and Windows' own message is what gets reported. vault.
      ensure() creates all eight of these folders at startup, so a folder that
      cannot be listed has been refused, not lost.

    * Dedupe is by sourceId, not by file name or by deleting the original.
      This tier cannot delete (see _ps_file_message), the persona has no grant
      on the calendar, and the invite file stays where it was - so the same
      invitation gets merged exactly once across any number of syncs.

    Output is one line of JSON, parsed by basecamp.py.
    """
    mail = (ctx or {}).get("mailbox") or ""
    rows = []
    for agent_id, vault_name, invites, outbox in _sources(ctx):
        rows.append("@{name=%s;vault=%s;invites=%s;outbox=%s}"
                    % (_psq(agent_id), _psq(vault_name),
                       _psq(invites), _psq(outbox)))
    return shell_ps(
        "$ErrorActionPreference='Stop';"
        "$cal={cal}; $drafts={drafts};"
        "$inv=0; $drf=0; $refused=New-Object System.Collections.ArrayList;"
        "function Note($src,$vault,$stage,$msg) {{ [void]$refused.Add("
        "  [pscustomobject]@{{ source=$src; vault=$vault; stage=$stage;"
        "    error=$msg }}) }};"
        # Prove the calendar is readable before writing anything into it.
        "$calDays=@{{}}; $calOk=$false;"
        "try {{"
        "  foreach ($c in @(Get-ChildItem -LiteralPath $cal -Filter *.json -File"
        "      -ErrorAction Stop)) {{ $calDays[$c.Name]=$true }};"
        "  $calOk=$true }}"
        "catch {{ Note '(global)' 'mailbox' 'calendar' $_.Exception.Message }};"
        "$sources=@({rows});"
        "foreach ($s in $sources) {{"
        # ---- invitations -> the global calendar
        "  if ($calOk) {{ try {{"
        "    foreach ($f in @(Get-ChildItem -LiteralPath $s.invites -Filter *.json"
        "        -File -ErrorAction Stop)) {{"
        "      $i = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json;"
        "      if (-not $i.date) {{ continue }};"
        "      $name = $i.date + '.json'; $day = Join-Path $cal $name;"
        "      if ($calDays.ContainsKey($name)) {{"
        "        $d = Get-Content -LiteralPath $day -Raw | ConvertFrom-Json }}"
        "      else {{"
        "        $d = [pscustomobject]@{{ id=$i.date; date=$i.date; events=@() }} }};"
        "      $have = @(@($d.events) | Where-Object {{ $_ -and $_.sourceId -eq $i.id }});"
        "      if ($have.Count -gt 0) {{ continue }};"
        "      $ev = [pscustomobject]@{{ start=$i.start; end=$i.end;"
        "            title=$i.title; location=$i.location;"
        "            attendees=$i.attendees; notes=$i.notes;"
        "            source=$s.name; sourceId=$i.id }};"
        "      $merged = @(@($d.events) | Where-Object {{ $_ }}) + @($ev);"
        "      $d.events = @($merged | Sort-Object start);"
        "      [IO.File]::WriteAllText($day, ($d | ConvertTo-Json -Depth 6));"
        "      $calDays[$name]=$true; $inv++ }} }}"
        "  catch {{ Note $s.name $s.vault 'invites' $_.Exception.Message }} }};"
        # ---- outbox -> the global drafts
        "  try {{"
        "    $here=@{{}};"
        "    foreach ($e in @(Get-ChildItem -LiteralPath $drafts -Filter *.json"
        "        -File -ErrorAction Stop)) {{ $here[$e.Name]=$true }};"
        "    foreach ($f in @(Get-ChildItem -LiteralPath $s.outbox -Filter *.json"
        "        -File -ErrorAction Stop)) {{"
        "      if ($here.ContainsKey($f.Name)) {{ continue }};"
        "      Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $drafts $f.Name);"
        "      $drf++ }} }}"
        "  catch {{ Note $s.name $s.vault 'outbox' $_.Exception.Message }} }};"
        "Write-Output ([pscustomobject]@{{ invites=$inv; drafts=$drf;"
        "  refused=@($refused) }} | ConvertTo-Json -Depth 4 -Compress)".format(
            cal=_psq(os.path.join(mail, "calendar")),
            drafts=_psq(os.path.join(mail, "drafts")),
            rows=",".join(rows)))


# -- what each tool is about to touch ---------------------------------------
#
# Declared, not inferred. These feed the refusal explanation in agent.py and
# nothing else - no tool consults them before running.

def _p(read=(), write=()):
    return {"read": [x for x in read if x], "write": [x for x in write if x]}


def _pl_folder(a, ctx):
    return _p(read=[_mail_dir(ctx, a.get("folder") or "inbox")])


def _pl_calendar(a, ctx):
    return _p(read=[_mail_dir(ctx, "calendar")])


def _pl_drafts(a, ctx):
    return _p(write=[_mail_dir(ctx, "drafts")])


def _pl_archive(a, ctx):
    # Both ends. The copy needs the destination; the tombstone that replaces
    # the original needs the source.
    return _p(write=[_mail_dir(ctx, "archive"),
                     _mail_dir(ctx, a.get("folder") or "inbox")])


def _pl_label(a, ctx):
    # The labels root, not the leaf - filing under a new label creates a
    # directory inside it, which is a write to the parent.
    return _p(write=[_mail_dir(ctx, "labels"),
                     _mail_dir(ctx, a.get("folder") or "inbox")])


def _pl_read_arg(a, ctx):
    return _p(read=[a.get("path")])


def _pl_write_arg(a, ctx):
    return _p(write=[a.get("path")])


def _pl_move(a, ctx):
    return _p(write=[a.get("source"), a.get("destination")])


def _pl_records(a, ctx):
    return _p(read=[_vault_dir(ctx, _data_folder(a, ctx))])


def _pl_invites(a, ctx):
    return _p(write=[_vault_dir(ctx, "invites")])


def _pl_outbox(a, ctx):
    return _p(write=[_vault_dir(ctx, "outbox")])


def _pl_sync(a, ctx):
    # Everything the merge touches, both ends. The calendar is on BOTH lists
    # because merging an event into a day file means reading the day back
    # first - a grant to write it without a grant to read it would quietly
    # replace every event already there.
    read, write = [], []
    for _, _vault, invites, outbox in _sources(ctx):
        read += [invites, outbox]
    mail = (ctx or {}).get("mailbox") or ""
    read.append(os.path.join(mail, "calendar"))
    write += [os.path.join(mail, "calendar"), os.path.join(mail, "drafts")]
    return _p(read=read, write=write)


# Every persona has the same five hands. They differ in what their policy lets
# those hands reach, which is the only difference worth having.
PERSONAS = tuple(agents_mod.persona_ids())


CATALOGUE = [
    Tool("list_files", "List the files and folders at a path on this machine.",
         {"properties": {"path": _str("Absolute Windows path to list.")},
          "required": ["path"]},
         _b_list_files, paths=_pl_read_arg, shell="cmd", needs=["read access to that path"]),

    Tool("read_file", "Read the contents of a text file.",
         {"properties": {"path": _str("Absolute Windows path of the file."),
                         "maxLines": {"type": "integer",
                                      "description": "How many lines to read. Default 200."}},
          "required": ["path"]},
         _b_read_file, paths=_pl_read_arg, shell="powershell", needs=["read access to that file"]),

    Tool("write_file", "Create or overwrite a text file.",
         {"properties": {"path": _str("Absolute Windows path to write."),
                         "content": _str("The full text to write.")},
          "required": ["path", "content"]},
         _b_write_file, paths=_pl_write_arg, shell="powershell", needs=["write access to that path"]),

    Tool("move_file", "Move or rename a file.",
         {"properties": {"source": _str("Absolute path of the file to move."),
                         "destination": _str("Absolute destination path.")},
          "required": ["source", "destination"]},
         _b_move_file, paths=_pl_move, shell="cmd",
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

    # -- base agent: mail -------------------------------------------------------

    Tool("list_messages", "List the message ids in a mailbox folder. Start here, "
                          "then read the ones that look relevant.",
         {"properties": {"folder": _str("inbox, archive, drafts or private. "
                                        "Default inbox.")},
          "required": []},
         _b_list_messages, paths=_pl_folder, shell="powershell", agent="base",
         needs=["read access to that mailbox folder"]),

    Tool("read_message", "Read one message as JSON: sender, subject, date, "
                         "labels and full body.",
         {"properties": {"id": _str("The message id, as returned by "
                                    "list_messages, with or without .json."),
                         "folder": _str("Which folder it is in. Default inbox.")},
          "required": ["id"]},
         _b_read_message, paths=_pl_folder, shell="powershell", agent="base",
         needs=["read access to that mailbox folder"]),

    Tool("search_mail", "Find messages containing a phrase. Returns the file "
                        "names that matched, not the messages themselves.",
         {"properties": {"query": _str("The phrase to look for. Case insensitive."),
                         "folder": _str("Which folder to search. Default inbox.")},
          "required": ["query"]},
         _b_search_mail, paths=_pl_folder, shell="powershell", agent="base",
         needs=["read access to that mailbox folder"]),

    Tool("archive_message", "Move a message out of the inbox into archive.",
         {"properties": {"id": _str("The message id to archive."),
                         "folder": _str("Where it is now. Default inbox.")},
          "required": ["id"]},
         _b_archive_message, paths=_pl_archive, shell="powershell", agent="base",
         needs=["write access to the source folder AND to the archive folder"]),

    Tool("label_message", "File a message under a label.",
         {"properties": {"id": _str("The message id to file."),
                         "label": _str("The label to file it under."),
                         "folder": _str("Where it is now. Default inbox.")},
          "required": ["id", "label"]},
         _b_label_message, paths=_pl_label, shell="powershell", agent="base",
         needs=["write access to the source folder AND to the labels folder"]),

    Tool("draft_reply", "Write a reply into the drafts folder. This never sends "
                        "anything - the person sends it themselves.",
         {"properties": {"id": _str("The message id being replied to."),
                         "to": _str("Recipient address."),
                         "subject": _str("Subject line."),
                         "body": _str("The full text of the reply.")},
          "required": ["subject", "body"]},
         _b_draft_reply, paths=_pl_drafts, shell="powershell", agent="base",
         needs=["write access to the drafts folder"]),

    # -- base agent: calendar ---------------------------------------------------

    Tool("list_events", "Read the calendar. Without a date this returns every "
                        "day held, each tagged with its file name.",
         {"properties": {"date": _str("A single day as YYYY-MM-DD. Omit for "
                                      "everything.")},
          "required": []},
         _b_list_events, paths=_pl_calendar, shell="powershell", agent="base",
         needs=["read access to the calendar folder"]),

    Tool("find_free_slot", "Read the calendar so you can work out where the gaps "
                           "are. Returns the booked events, not the gaps.",
         {"properties": {"date": _str("A single day as YYYY-MM-DD. Omit for "
                                      "everything.")},
          "required": []},
         _b_find_free_slot, paths=_pl_calendar, shell="powershell", agent="base",
         needs=["read access to the calendar folder"]),

    Tool("draft_invite", "Write a meeting invitation into drafts. This never "
                         "sends anything.",
         {"properties": {"title": _str("Meeting title."),
                         "date": _str("Day as YYYY-MM-DD."),
                         "start": _str("Start time as HH:MM."),
                         "end": _str("End time as HH:MM."),
                         "attendees": _str("Comma-separated addresses.")},
          "required": ["title", "date", "start"]},
         _b_draft_invite, paths=_pl_drafts, shell="powershell", agent="base",
         needs=["write access to the drafts folder"]),

    Tool("sync_vaults", "Collect every agent's pending invitations and drafted "
                        "messages into the global calendar and mail view. Runs "
                        "on its own every few seconds; call it when you want it "
                        "to happen right now.",
         {"properties": {}, "required": []},
         _b_sync_vaults, paths=_pl_sync, shell="powershell", agent="base",
         needs=["read access to every agent's invites and outbox folders, and "
                "read AND write access to the global calendar and drafts"]),

    # -- the four personas: their own records ---------------------------------
    #
    # One definition each, shared by all four agents. Which folder these reach
    # is set per agent from the registry, not by the model.

    Tool("list_records", "List what is in one of your folders: id, date and "
                         "title for each record. Start here, then read the ones "
                         "that look relevant.",
         {"properties": {"folder": _str("Which of your folders to list. "
                                        "Defaults to your own data folder. "
                                        "'invites' and 'outbox' also work.")},
          "required": []},
         _b_list_records, paths=_pl_records, shell="powershell", agent=PERSONAS,
         folder_enum=True, needs=["read access to that folder"]),

    Tool("read_record", "Read one whole record as JSON.",
         {"properties": {"id": _str("The record id, as returned by "
                                    "list_records, with or without .json."),
                         "folder": _str("Which folder it is in. Defaults to "
                                        "your own data folder.")},
          "required": ["id"]},
         _b_read_record, paths=_pl_records, shell="powershell", agent=PERSONAS,
         folder_enum=True, needs=["read access to that folder"]),

    Tool("search_records", "Find records containing a phrase. Returns the ids "
                           "and titles that matched, not the records themselves.",
         {"properties": {"query": _str("The phrase to look for. Case insensitive."),
                         "folder": _str("Which folder to search. Defaults to "
                                        "your own data folder.")},
          "required": ["query"]},
         _b_search_records, paths=_pl_records, shell="powershell", agent=PERSONAS,
         folder_enum=True, needs=["read access to that folder"]),

    Tool("create_invite", "Put a calendar invitation in your invites folder. "
                          "The always-on agent picks it up and puts it on the "
                          "shared calendar. Read the record with the real date "
                          "and time in it first.",
         {"properties": {"title": _str("What the event is called."),
                         "date": _str("Day as YYYY-MM-DD."),
                         "start": _str("Start time as HH:MM."),
                         "end": _str("End time as HH:MM."),
                         "location": _str("Where it is."),
                         "attendees": _str("Comma-separated names or addresses."),
                         "notes": _str("Anything to bring or prepare.")},
          "required": ["title", "date", "start"]},
         _b_create_invite, paths=_pl_invites, shell="powershell", agent=PERSONAS,
         needs=["write access to your invites folder"]),

    Tool("draft_message", "Put a message in your outbox for the person to send. "
                          "This never sends anything.",
         {"properties": {"to": _str("Recipient."),
                         "subject": _str("Subject line."),
                         "body": _str("The full text of the message.")},
          "required": ["subject", "body"]},
         _b_draft_message, paths=_pl_outbox, shell="powershell", agent=PERSONAS,
         needs=["write access to your outbox folder"]),
]

BY_NAME = {t.name: t for t in CATALOGUE}


def for_agent(agent_id):
    """Every tool a subagent is allowed to ask for, before the policy gate.

    Two separate questions, and conflating them is how you end up unable to
    explain a refusal: this one is "does this agent have hands of this shape
    at all", and policy.tools is "is this particular hand switched off right
    now". The health agent never sees list_processes; it is not off, it is
    not part of what the health agent is."""
    if not agent_id:
        return list(CATALOGUE)
    return [t for t in CATALOGUE if t.for_agent(agent_id)]


def enabled_tools(policy, agent_id=None):
    gate = (policy or {}).get("tools") or {}
    return [t for t in for_agent(agent_id) if gate.get(t.name, not t.danger)]


def schemas(policy, agent_id=None):
    return [t.schema(agent_id) for t in enabled_tools(policy, agent_id)]


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
            "agent": t.agent_label(),
            "parameters": t.parameters.get("properties", {}),
        })
    return out


def build_command(name, arguments, ctx=None):
    t = BY_NAME.get(name)
    if not t:
        raise KeyError(name)
    return t.build(arguments or {}, ctx), t
