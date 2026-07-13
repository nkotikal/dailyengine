# Registers a Windows Scheduled Task that is the "cron" for Daily Digest - no
# always-on server required. It runs every 15 minutes through the day and sends
# whatever is DUE right now: the morning digest (once, at/after your send time),
# progress check-ins (at each configured slot), and the end-of-day recap. Each is
# cross-process de-duplicated, so frequent ticks never double-send.
# Runs hidden via WSL. Re-run any time to update. Tries Register-ScheduledTask,
# then falls back to schtasks.

$ErrorActionPreference = "Stop"
$taskName = "DailyDigestEmail"
# Self-locating: the launcher lives next to this installer (the repo's tools/ folder),
# so this works wherever the repo is cloned.
$vbs = Join-Path $PSScriptRoot "send_digest_hidden.vbs"
$startTime = "06:00"     # first tick; covers morning send + all check-in/recap times
$intervalMin = 15        # how often to check what's due
$durationHours = 17      # active window (06:00 -> ~23:00) so the 9pm recap is covered

if (-not (Test-Path $vbs)) { Write-Error "Launcher not found: $vbs"; exit 1 }

$run = "wscript.exe `"$vbs`""

function Register-ViaCmdlet {
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
    # Daily at $startTime, repeating every $intervalMin minutes for $durationHours.
    $trigger = New-ScheduledTaskTrigger -Daily -At $startTime
    $trigger.Repetition = (New-ScheduledTaskTrigger -Once -At $startTime `
        -RepetitionInterval (New-TimeSpan -Minutes $intervalMin) `
        -RepetitionDuration (New-TimeSpan -Hours $durationHours)).Repetition
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings `
        -Description "Sends the daily digest, progress check-ins, and end-of-day recap when each is due (checks every $intervalMin min)." `
        -Force | Out-Null
}

try {
    Register-ViaCmdlet
    Write-Host "Registered '$taskName' (every $intervalMin min from $startTime for $durationHours h) via cmdlet."
} catch {
    Write-Host "Cmdlet registration failed ($($_.Exception.Message)); trying schtasks..."
    schtasks /Create /TN $taskName /TR $run /SC MINUTE /MO $intervalMin /ST $startTime /F | Out-Null
    Write-Host "Registered '$taskName' (every $intervalMin min from $startTime) via schtasks."
}

Write-Host ""
Write-Host "It sends the morning digest, check-ins, and the recap when each is due."
Write-Host "Run it now to test:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "                or:  schtasks /Run /TN '$taskName'"
