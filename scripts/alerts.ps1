# Scheduled work for IndiaBloom, run from Windows Task Scheduler on this PC.
#
#   -Mode check   alerts only: prices, moves, news (run every 15 minutes on weekdays)
#   -Mode daily   after the Indian close: NSE deals, corporate events, then alerts.
#                 On Sundays also refreshes fundamentals and the holdings history.
#
# Why this runs locally: alert rules, the watchlist and the fundamentals/events
# caches are personal or git-ignored, so GitHub cannot produce them. The GitHub
# Action only maintains the ledger and the tracked deals history.
#
# Optional steps (deals, events, fundamentals) do not stop the run; the alerts step
# does. Each step is retried a few times because the PC may still be connecting.
# Output goes to data\alerts\runner.log.

param(
    [ValidateSet("check", "daily")]
    [string]$Mode = "check",
    [int]$Attempts = 3,
    [int]$WaitSeconds = 60
)

Set-Location (Join-Path $PSScriptRoot "..")
$logFile = Join-Path $PSScriptRoot "..\data\alerts\runner.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

function Test-HasRules {
    # True when data\alerts.json holds at least one rule. A missing or unreadable file counts as no rules.
    $rulesFile = Join-Path $PSScriptRoot "..\data\alerts.json"
    if (-not (Test-Path $rulesFile)) { return $false }
    try {
        $rules = (Get-Content $rulesFile -Raw -Encoding utf8 | ConvertFrom-Json).rules
        return ($null -ne $rules -and @($rules).Count -gt 0)
    } catch {
        return $false
    }
}

function Write-Log([string]$Text) {
    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Text" -Encoding utf8
}

# Runs one CLI command with retries. Returns $true on success.
function Invoke-Step([string]$Name, [string[]]$CliArgs) {
    Write-Log "$Name start"
    for ($try = 1; $try -le $Attempts; $try++) {
        python -m indiabloom @CliArgs 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
        if ($LASTEXITCODE -eq 0) {
            Write-Log "$Name ok"
            return $true
        }
        Write-Log "$Name attempt $try failed (exit $LASTEXITCODE), waiting $WaitSeconds s"
        Start-Sleep -Seconds $WaitSeconds
    }
    Write-Log "$Name gave up after $Attempts attempts"
    return $false
}

if ($Mode -eq "check") {
    if (-not (Test-HasRules)) { exit 0 }  # nothing to check: stay quiet and do not log
    $ok = Invoke-Step "alerts check" @("alerts", "check")
    if (-not $ok) { exit 1 }
    exit 0
}

# daily: order matters. Deals and events are refreshed first so the alert check sees them.
Invoke-Step "deals" @("deals") | Out-Null
Invoke-Step "events" @("events", "--index", "nifty500", "--sleep", "0.3") | Out-Null
if ((Get-Date).DayOfWeek -eq "Sunday") {
    Invoke-Step "fundamentals" @("fundamentals", "--index", "nifty500", "--sleep", "0.3") | Out-Null
}
$ok = if (Test-HasRules) { Invoke-Step "alerts check" @("alerts", "check") } else { Write-Log "alerts check skipped: no rules"; $true }
Write-Log "daily done"
if (-not $ok) { exit 1 }
exit 0
