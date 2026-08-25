<#
.SYNOPSIS
    Bring the whole local stack up with one command.

.DESCRIPTION
    A thin wrapper around scripts/dev.sh so the stack starts from PowerShell as
    well as from a POSIX shell. The logic lives in the bash script alone:
    duplicating it here would mean two implementations drifting apart, and Git
    Bash ships with Git for Windows, which this repo already requires.

    Every argument is passed through unchanged.

    This file is deliberately ASCII-only and saved with a BOM. Windows
    PowerShell 5.1 decodes a BOM-less script using the system ANSI codepage, so
    a stray non-ASCII character renders as mojibake and, inside a string the
    script matches on, would change behaviour.

.EXAMPLE
    .\scripts\dev.ps1

.EXAMPLE
    .\scripts\dev.ps1 --fresh --force
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'dev.sh'

if (-not (Test-Path -LiteralPath $script)) {
    Write-Error "Cannot find $script"
    exit 1
}

# Windows typically has three things called bash.exe on PATH and two of them are
# the WSL launcher (System32\bash.exe and the WindowsApps alias). Running this
# script under WSL is wrong even where a distro is installed: it would look for
# Linux python, node and ODBC drivers, none of which are the ones the stack
# uses. With no distro it fails as "execvpe /bin/bash failed 2", naming neither
# WSL nor the real problem. So reject those outright.
function Test-IsWslShim {
    param([string]$Path)
    if (-not $Path) { return $false }
    return ($Path -match '\\Windows\\(System32|Sysnative)\\bash\.exe$') -or
           ($Path -match '\\WindowsApps\\bash\.exe$')
}

function Test-LooksLikeGitBash {
    param([string]$Path)
    if (-not $Path) { return $false }
    return $Path -match '\\Git\\(usr\\)?bin\\bash\.exe$'
}

# Returns 'ok', or a short reason the candidate was rejected. Never throws: a
# candidate that cannot be evaluated must not abort the search.
function Get-BashRejection {
    param([string]$Path)

    if (-not $Path) { return 'empty path' }
    try {
        if (-not (Test-Path -LiteralPath $Path)) { return 'not found' }
    }
    catch { return 'not found' }
    if (Test-IsWslShim $Path) { return 'WSL launcher, not Git Bash' }

    # Executing the candidate is the strongest check, but it must never produce
    # a false negative, so it is advisory. Two 5.1 traps are avoided here:
    # `2>&1` on a native command raises NativeCommandError under
    # ErrorActionPreference='Stop', and `$LASTEXITCODE` is unreliable when a
    # pipeline is stopped early by Select-Object.
    $version = $null
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $version = (& $Path --version 2>$null | Select-Object -First 1)
    }
    catch { $version = $null }
    finally { $ErrorActionPreference = $previous }

    if ($version -and ($version -match 'GNU bash')) { return 'ok' }
    # Probe inconclusive (antivirus, a stopped pipeline, an odd console host).
    # Trust the install location rather than rejecting a working bash.
    if (Test-LooksLikeGitBash $Path) { return 'ok' }

    if ($version) { return "not GNU bash: $version" }
    return 'could not run it, and it is not in a Git install directory'
}

function Get-BashCandidates {
    $candidates = [System.Collections.Generic.List[string]]::new()

    # Git for Windows first: it is the one that can actually run this script.
    # `git --exec-path` lands in libexec/git-core, and the install root is some
    # way above it, so walk up rather than assuming a fixed depth.
    try {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($git) {
            $execPath = $null
            try { $execPath = (& git --exec-path 2>$null | Select-Object -First 1) } catch { }
            if ($execPath) {
                $dir = ($execPath -replace '/', '\')
                for ($i = 0; $i -lt 5 -and $dir; $i++) {
                    $candidates.Add((Join-Path $dir 'bin\bash.exe'))
                    $candidates.Add((Join-Path $dir 'usr\bin\bash.exe'))
                    $dir = Split-Path -Parent $dir
                }
            }
            # git.exe usually lives in <root>\cmd or <root>\bin.
            $gitRoot = Split-Path -Parent (Split-Path -Parent $git.Source)
            if ($gitRoot) {
                $candidates.Add((Join-Path $gitRoot 'bin\bash.exe'))
                $candidates.Add((Join-Path $gitRoot 'usr\bin\bash.exe'))
            }
        }
    }
    catch { }

    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs", 'C:\Program Files')) {
        if ($base) {
            $candidates.Add((Join-Path $base 'Git\bin\bash.exe'))
            $candidates.Add((Join-Path $base 'Git\usr\bin\bash.exe'))
        }
    }

    # Anything on PATH last, after the WSL shims have been filtered out.
    try {
        foreach ($cmd in @(Get-Command bash -All -ErrorAction SilentlyContinue)) {
            if ($cmd.Path) { $candidates.Add($cmd.Path) }
            elseif ($cmd.Source) { $candidates.Add($cmd.Source) }
        }
    }
    catch { }

    return $candidates | Where-Object { $_ } | Select-Object -Unique
}

$attempts = [System.Collections.Generic.List[string]]::new()
$bash = $null
foreach ($candidate in Get-BashCandidates) {
    $reason = Get-BashRejection $candidate
    if ($reason -eq 'ok') { $bash = $candidate; break }
    $attempts.Add(("  {0}  [{1}]" -f $candidate, $reason))
}

if (-not $bash) {
    $tried = if ($attempts.Count) { ($attempts -join "`n") } else { '  (no candidates found)' }
    Write-Error @"
Could not find a usable bash.

Windows ships a bash.exe that only launches WSL, which cannot run this script.
Git for Windows provides the one that can:

    winget install --id Git.Git

Candidates tried:
$tried

You can always run the underlying script directly from Git Bash:

    bash scripts/dev.sh
"@
    exit 1
}

Write-Verbose "Using bash at $bash"

Push-Location $root
try {
    # Ctrl+C has to reach the bash process so its trap runs and stops both
    # servers. Start-Process would detach it and leave them orphaned, so this
    # calls bash in the foreground and inherits the console.
    if ($Arguments) {
        & $bash './scripts/dev.sh' @Arguments
    }
    else {
        & $bash './scripts/dev.sh'
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
