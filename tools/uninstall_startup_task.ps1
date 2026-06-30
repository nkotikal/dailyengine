# Removes the Daily Digest UI server auto-start (scheduled task + any old launcher)
# and stops a running server.
$taskName = "DailyDigestServer"
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    Write-Host "Removed scheduled task '$taskName'."
} catch {
    schtasks /Delete /TN $taskName /F 2>$null
    Write-Host "Removed scheduled task '$taskName' (or it did not exist)."
}
$old = Join-Path ([Environment]::GetFolderPath('Startup')) "DailyDigestServer.vbs"
if (Test-Path $old) { Remove-Item $old -Force; Write-Host "Removed old Startup-folder launcher." }
Write-Host "Stopping any running server..."
wsl.exe -e bash -lc "pkill -f '[s]erver.py'" 2>$null
Write-Host "Done."
