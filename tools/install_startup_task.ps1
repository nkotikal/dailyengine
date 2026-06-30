# Registers a Windows Scheduled Task that auto-starts the web UI / dashboard server
# at logon (hidden, via WSL, with a self-restart loop). The daily EMAIL is a
# separate task (install_email_task.ps1) and does not need this server.
# Re-run any time to update. Tries Register-ScheduledTask, then falls back to schtasks.

$ErrorActionPreference = "Stop"
$taskName = "DailyDigestServer"
$vbs = "C:\Users\nkotikal\Desktop\bldr\tools\start_digest_hidden.vbs"

if (-not (Test-Path $vbs)) { Write-Error "Launcher not found: $vbs"; exit 1 }

$run = "wscript.exe `"$vbs`""

# Remove any leftover Startup-folder launcher so there is a single mechanism.
$old = Join-Path ([Environment]::GetFolderPath('Startup')) "DailyDigestServer.vbs"
if (Test-Path $old) { Remove-Item $old -Force; Write-Host "Removed old Startup-folder launcher." }

function Register-ViaCmdlet {
    $action  = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero)   # never auto-kill (long-running server)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "Starts the Daily Digest / ResumeForge UI server at logon." -Force | Out-Null
}

try {
    Register-ViaCmdlet
    Write-Host "Registered scheduled task '$taskName' (at logon) via cmdlet."
} catch {
    Write-Host "Cmdlet registration failed ($($_.Exception.Message)); trying schtasks..."
    schtasks /Create /TN $taskName /TR $run /SC ONLOGON /F | Out-Null
    Write-Host "Registered scheduled task '$taskName' (at logon) via schtasks."
}

Write-Host ""
Write-Host "Start it now (without logging out):  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "UI will be at http://127.0.0.1:8765"
