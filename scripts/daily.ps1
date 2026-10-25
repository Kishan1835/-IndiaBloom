# Daily routine for the forward signal ledger. Runs at logon (see README).
#
#   -Mode log    records predictions. Refuses to run after the Indian open
#                for the target session (the CLI enforces this).
#   -Mode score  scores predictions whose session has traded. Safe at any time.
#
# At logon the network may not be ready, so the python command is retried for
# up to ~5 minutes before giving up.

param(
    [ValidateSet("log", "score")]
    [string]$Mode = "log",
    [int]$Attempts = 5,
    [int]$WaitSeconds = 60
)

Set-Location (Join-Path $PSScriptRoot "..")
$logFile = Join-Path $PSScriptRoot "..\data\ledger\daily.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) | Out-Null

if ($Mode -eq "log") {
    $command = @("-m", "indiabloom", "log-signals", "--index", "nifty500", "--top", "20")
} else {
    $command = @("-m", "indiabloom", "score-signals", "--recent", "10")
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$stamp] $Mode start"

for ($try = 1; $try -le $Attempts; $try++) {
    python @command *>> $logFile
    if ($LASTEXITCODE -eq 0) {
        break
    }
    Add-Content -Path $logFile -Value "attempt $try failed (exit $LASTEXITCODE); retrying in $WaitSeconds s"
    Start-Sleep -Seconds $WaitSeconds
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$stamp] $Mode done"
Add-Content -Path $logFile -Value ""
