# Scheduled alert checks for watched stocks. Run it from Windows Task Scheduler.
#
#   -Mode check   price, move and news alerts (run every 15 minutes on weekdays)
#   -Mode daily   refresh NSE deals, then check all alerts (once a day, after 18:00 IST)
#
# Fired alerts are appended to data\alerts\log.csv. The check runs the same CLI as
# `python -m indiabloom alerts check`, so the rules in data\alerts.json are the source.
# Network failures are retried a few times, since the PC may still be connecting.

param(
    [ValidateSet("check", "daily")]
    [string]$Mode = "check",
    [int]$Attempts = 3,
    [int]$WaitSeconds = 60
)

Set-Location (Join-Path $PSScriptRoot "..")
$logFile = Join-Path $PSScriptRoot "..\data\alerts\runner.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

if ($Mode -eq "daily") {
    $steps = @(
        @("-m", "indiabloom", "alerts", "check", "--refresh")
    )
} else {
    $steps = @(
        @("-m", "indiabloom", "alerts", "check")
    )
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$stamp] $Mode start"

foreach ($command in $steps) {
    $ok = $false
    for ($try = 1; $try -le $Attempts; $try++) {
        python @command 2>&1 | Tee-Object -FilePath $logFile -Append
        if ($LASTEXITCODE -eq 0) { $ok = $true; break }
        Add-Content -Path $logFile -Value "attempt $try failed, waiting $WaitSeconds s"
        Start-Sleep -Seconds $WaitSeconds
    }
    if (-not $ok) {
        Add-Content -Path $logFile -Value "gave up after $Attempts attempts: $($command -join ' ')"
        exit 1
    }
}

Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Mode done"
