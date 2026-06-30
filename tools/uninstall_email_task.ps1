# Removes the daily digest email scheduled task.
$taskName = "DailyDigestEmail"
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    Write-Host "Removed scheduled task '$taskName'."
} catch {
    schtasks /Delete /TN $taskName /F 2>$null
    Write-Host "Removed scheduled task '$taskName' (or it did not exist)."
}
