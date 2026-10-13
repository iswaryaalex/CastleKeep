<#
    phase1-all.ps1 - run every Phase 1 step back to back and show the output.

    This is the whole terminal walkthrough with no pauses, so you can see in one
    scroll what this host actually does. It is a diagnostic, not the demo: in
    front of a room you want the steps one at a time, because the silences are
    where people think.

    What it does NOT do: claim success. Each step declares what it expects, the
    script classifies what really happened, and any disagreement is printed as
    UNEXPECTED and counted at the end. A step that was supposed to be refused
    and wasn't is the single most important thing this script can tell you, so
    it is never softened into a pass.

    It never passes --audit. --audit turns the restrictions OFF for the run,
    which would make every containment step below pass for the wrong reason.

      .\workshop\phase1-all.ps1
      .\workshop\phase1-all.ps1 -SkipLab          # lab already built
      .\workshop\phase1-all.ps1 -SkipHostAttack   # don't run the unsandboxed one
      .\workshop\phase1-all.ps1 -Exe C:\path\to\wxc-exec.exe
#>

[CmdletBinding()]
param(
    [string] $Exe,
    [string] $Lab = "C:\SanctumLab",
    [switch] $SkipLab,
    [switch] $SkipHostAttack,
    [string] $LogFile
)

# Native tools write to stderr as a matter of course. Under a stricter
# preference PowerShell would turn the first such line into a terminating
# error and the run would stop on the step that is working correctly.
$ErrorActionPreference = "Continue"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$WorkshopDir = $PSScriptRoot
if (-not $LogFile) {
    $LogFile = Join-Path $ProjectDir ("PHASE1-RUN-{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
}

$script:Lines = New-Object System.Collections.Generic.List[string]
$script:Results = New-Object System.Collections.Generic.List[object]

function Say {
    param([string] $Text = "", [string] $Colour = "Gray")
    Write-Host $Text -ForegroundColor $Colour
    $script:Lines.Add($Text)
}

function Rule {
    param([string] $Text)
    Say ""
    Say ("=" * 78) "DarkGray"
    Say $Text "White"
    Say ("=" * 78) "DarkGray"
}

# ---------------------------------------------------------------- the binary

function Find-Exe {
    if ($Exe) {
        if (-not (Test-Path $Exe)) { throw "No wxc-exec.exe at $Exe" }
        return (Resolve-Path $Exe).Path
    }
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
    $roots = @()
    if ($env:MXC_BIN_DIR) { $roots += $env:MXC_BIN_DIR }
    $roots += (Join-Path $ProjectDir "bin")
    $roots += (Join-Path $ProjectDir "..\node_modules\@microsoft\mxc-sdk\bin")
    $roots += (Join-Path $env:LOCALAPPDATA "Microsoft\MXC\bin")
    foreach ($r in $roots) {
        foreach ($c in @((Join-Path $r "$arch\wxc-exec.exe"), (Join-Path $r "wxc-exec.exe"))) {
            if (Test-Path $c) { return (Resolve-Path $c).Path }
        }
    }
    throw "wxc-exec.exe not found. Looked under: $($roots -join '; ') - see bin\README.md"
}

# ------------------------------------------------------------- classifier
# Deliberately the same three outcomes core\mxc.py uses, because a step that
# reads differently here than it does in the app would be worse than useless.
#
#   refused-to-start : MXC would not build the sandbox. Nothing ran.
#   blocked          : the sandbox ran and the policy stopped it reaching something.
#   ok               : the command ran and exited clean.
#   failed           : it ran and failed on its own merits.

function Get-Outcome {
    param([int] $Code, [string] $Text)

    $refusePatterns = @(
        'is not supported by',
        'are not (yet )?supported on Windows',
        'requires schema version',
        'offending_?[Ff]ield',
        'SCHEMA_VIOLATION',
        'UNSUPPORTED_FIELD',
        'failed to (create|build) (the )?(sandbox|container)',
        'refused to start'
    )
    foreach ($p in $refusePatterns) {
        if ($Text -match $p) { return "refused-to-start" }
    }

    $blockPatterns = @(
        'Access is denied',
        'cannot find the file specified',
        'cannot find the path specified',
        'The system cannot find',
        'Could not resolve host',
        'Failed to connect',
        'Connection refused',
        'curl: \(\d+\)'
    )
    foreach ($p in $blockPatterns) {
        if ($Text -match $p) { return "blocked" }
    }

    if ($Code -eq 0) { return "ok" }
    return "failed"
}

# ------------------------------------------------------------------ runner

function Invoke-Step {
    param(
        [string]   $Number,
        [string]   $Title,
        [string]   $Point,       # the one sentence this step exists to prove
        [string[]] $CliArgs,     # arguments to wxc-exec. Not $Args: that is an
                                 # automatic variable and shadowing it is a trap.
        [string]   $Expect       # ok | blocked | refused-to-start | any
    )

    Rule ("STEP {0}  {1}" -f $Number, $Title)
    Say $Point "DarkGray"
    Say ""
    Say ("  > " + ((@($ExePath) + $CliArgs) -join " ")) "Cyan"
    Say ""

    $started = Get-Date
    try {
        $raw = & $ExePath @CliArgs 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
        }
        $code = $LASTEXITCODE
    } catch {
        $raw = $_.Exception.Message
        $code = -1
    }
    $ms = [int]((Get-Date) - $started).TotalMilliseconds
    $text = ($raw | Out-String)

    foreach ($line in ($text -split "`r?`n")) {
        if ($line.Trim().Length) { Say ("    " + $line) "Gray" }
    }

    # A report step like --probe is not pass or fail, and running its prose
    # through the classifier would misread the tier list it prints as a refusal.
    if ($Expect -eq "any") {
        $outcome = "report"
        $agree = $true
    } else {
        $outcome = Get-Outcome -Code $code -Text $text
        $agree = ($outcome -eq $Expect)
    }

    Say ""
    Say ("  exit {0}   {1} ms   outcome: {2}   expected: {3}" -f $code, $ms, $outcome, $Expect) "DarkGray"
    if ($agree) {
        Say $(if ($Expect -eq "any") { "  READ THIS ONE, it is information not a verdict" } else { "  AS EXPECTED" }) "Green"
    } else {
        Say ("  UNEXPECTED - this step expected '{0}' and got '{1}'" -f $Expect, $outcome) "Red"
    }

    $script:Results.Add([pscustomobject]@{
        Step = $Number; Title = $Title; Exit = $code
        Outcome = $outcome; Expected = $Expect
        Verdict = $(if ($Expect -eq "any") { "info" } elseif ($agree) { "as expected" } else { "UNEXPECTED" })
        Ms = $ms
    })
}

function Cfg { param([string] $Name) Join-Path $WorkshopDir $Name }

# =========================================================================

$ExePath = Find-Exe

Rule "Sanctum Phase 1, every step back to back"
Say ("  binary     {0}" -f $ExePath) "Gray"
Say ("  lab        {0}" -f $Lab) "Gray"
Say ("  transcript {0}" -f $LogFile) "Gray"
Say ("  host       {0}  {1}" -f $env:COMPUTERNAME, $env:PROCESSOR_ARCHITECTURE) "Gray"
Say ("  started    {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) "Gray"

# ---- 1 ------------------------------------------------------------------
Rule "STEP 1  Build the lab"
Say "Synthetic company folder. The secret in private\ is a decoy string." "DarkGray"
if ($SkipLab) {
    Say ""
    Say "  skipped (-SkipLab)" "Yellow"
} else {
    Say ""
    $setup = Join-Path $WorkshopDir "lab-setup.ps1"
    Say ("  > powershell -ExecutionPolicy Bypass -File {0}" -f $setup) "Cyan"
    Say ""
    & powershell -NoProfile -ExecutionPolicy Bypass -File $setup 2>&1 |
        ForEach-Object { Say ("    " + $_) "Gray" }
}
if (-not (Test-Path (Join-Path $Lab "private\api-key.txt"))) {
    Say ""
    Say "  The lab is not there. Everything below will fail for the wrong reason." "Red"
}

# ---- 2 ------------------------------------------------------------------
Invoke-Step -Number "2" -Title "Probe the host" `
    -Point "Reports what this machine can actually enforce. Nothing is spawned." `
    -CliArgs @("--probe") -Expect "any"

# ---- 3 ------------------------------------------------------------------
Invoke-Step -Number "3" -Title "Validate without running" `
    -Point "Parses the config and stops. A non-zero exit here is a refusal to start." `
    -CliArgs @((Cfg "01-hello.json"), "--dry-run") -Expect "ok"

# ---- 4 ------------------------------------------------------------------
Invoke-Step -Number "4" -Title "Spawn one for real" `
    -Point "Container created, one command run, container destroyed." `
    -CliArgs @((Cfg "01-hello.json")) -Expect "ok"

# ---- 5a -----------------------------------------------------------------
Invoke-Step -Number "5a" -Title "Read inside the grant" `
    -Point "public\ is granted, so this is an ordinary successful read." `
    -CliArgs @((Cfg "02-read-granted.json")) -Expect "ok"

# ---- 5b -----------------------------------------------------------------
Invoke-Step -Number "5b" -Title "Reach one folder sideways" `
    -Point "Identical grant list, different target. The file simply is not there." `
    -CliArgs @((Cfg "03-read-ungranted.json")) -Expect "blocked"

# ---- 5c -----------------------------------------------------------------
# The orphan. It is the only config that exercises the third outcome, and
# whether this host refuses it or quietly ignores deniedPaths is exactly the
# kind of thing you want to find out here rather than on stage.
Invoke-Step -Number "5c" -Title "Ask for deniedPaths" `
    -Point "If this host cannot enforce a deny list it should refuse to start, not degrade." `
    -CliArgs @((Cfg "04-deny-paths.json")) -Expect "refused-to-start"

# ---- 6 ------------------------------------------------------------------
Rule "STEP 6  The injection, with nothing in the way"
Say "Runs on your real host, unsandboxed. The decoy secret is supposed to print." "DarkGray"
if ($SkipHostAttack) {
    Say ""
    Say "  skipped (-SkipHostAttack)" "Yellow"
    $script:Results.Add([pscustomobject]@{
        Step = "6"; Title = "Injection, unsandboxed"; Exit = $null
        Outcome = "skipped"; Expected = "ok"; Verdict = "skipped"; Ms = 0
    })
} else {
    Say ""
    Say "  > Get-Content $Lab\public\meeting-notes.txt" "Cyan"
    Say "  > Get-Content $Lab\private\api-key.txt" "Cyan"
    Say ""
    $notes = Get-Content (Join-Path $Lab "public\meeting-notes.txt") -ErrorAction SilentlyContinue
    foreach ($l in $notes) { Say ("    " + $l) "Gray" }
    Say ""
    Say "    ---- the agent now does what the document told it to ----" "DarkGray"
    Say ""
    $key = Get-Content (Join-Path $Lab "private\api-key.txt") -ErrorAction SilentlyContinue
    foreach ($l in $key) { Say ("    " + $l) "Red" }
    Say ""
    if ($key) {
        Say "  AS EXPECTED - the secret is on screen and nothing went wrong." "Yellow"
        $v = "as expected"
    } else {
        Say "  The key did not read. Check the lab was built." "Red"
        $v = "UNEXPECTED"
    }
    $script:Results.Add([pscustomobject]@{
        Step = "6"; Title = "Injection, unsandboxed"; Exit = 0
        Outcome = $(if ($key) { "ok" } else { "failed" }); Expected = "ok"
        Verdict = $v; Ms = 0
    })
}

# ---- 7 ------------------------------------------------------------------
Invoke-Step -Number "7" -Title "The same injection, inside the sandbox" `
    -Point "The payload is still read and still obeyed. The read it triggers is what fails." `
    -CliArgs @((Cfg "07-injection.json")) -Expect "blocked"

# ---- 8a -----------------------------------------------------------------
Invoke-Step -Number "8a" -Title "Network denied" `
    -Point "curl to example.com with egress denied." `
    -CliArgs @((Cfg "05-net-deny.json")) -Expect "blocked"

# ---- 8b -----------------------------------------------------------------
Invoke-Step -Number "8b" -Title "Network allowed" `
    -Point "The same curl, one line of policy apart." `
    -CliArgs @((Cfg "06-net-allow.json")) -Expect "ok"

# ------------------------------------------------------------------ summary

Rule "SUMMARY"
$table = $script:Results | Format-Table Step, Title, Exit, Outcome, Expected, Verdict -AutoSize | Out-String
foreach ($l in ($table -split "`r?`n")) { if ($l.Trim().Length) { Say $l "Gray" } }

$bad = @($script:Results | Where-Object { $_.Verdict -eq "UNEXPECTED" })
$skipped = @($script:Results | Where-Object { $_.Verdict -eq "skipped" })
Say ""
if ($bad.Count -eq 0) {
    Say ("All {0} steps behaved as expected." -f $script:Results.Count) "Green"
} else {
    Say ("{0} step(s) did not behave as expected:" -f $bad.Count) "Red"
    foreach ($b in $bad) {
        Say ("  {0}  {1}  expected {2}, got {3}" -f $b.Step, $b.Title, $b.Expected, $b.Outcome) "Red"
    }
    Say ""
    Say "Read these before describing this setup as contained. A containment" "Yellow"
    Say "step that did not refuse is a finding, not a flaky test." "Yellow"
}
if ($skipped.Count) { Say ("{0} step(s) skipped." -f $skipped.Count) "Yellow" }

Set-Content -Path $LogFile -Value $script:Lines -Encoding UTF8
Say ""
Say ("Transcript: {0}" -f $LogFile) "DarkGray"
