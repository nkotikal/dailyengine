# Registers a Windows Scheduled Task that emails the daily digest at 07:00 every
# day (the "cron" for the digest). Runs hidden via WSL; no always-on server needed.
# Re-run any time to update. Tries Register-ScheduledTask, then falls back to schtasks.

$ErrorActionPreference = "Stop"
$taskName = "DailyDigestEmail"
$vbs = "C:\Users\nkotikal\Desktop\bldr\tools\send_digest_hidden.vbs"
$time = "07:00"

if (-not (Test-Path $vbs)) { Write-Error "Launcher not found: $vbs"; exit 1 }

$run = "wscript.exe `"$vbs`""

function Register-ViaCmdlet {
    $action  = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "Emails the daily digest at $time." -Force | Out-Null
}

try {
    Register-ViaCmdlet
    Write-Host "Registered scheduled task '$taskName' (daily at $time) via cmdlet."
} catch {
    Write-Host "Cmdlet registration failed ($($_.Exception.Message)); trying schtasks..."
    schtasks /Create /TN $taskName /TR $run /SC DAILY /ST $time /F | Out-Null
    Write-Host "Registered scheduled task '$taskName' (daily at $time) via schtasks."
}

Write-Host ""
Write-Host "Run it now to test:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "                or:  schtasks /Run /TN '$taskName'"
