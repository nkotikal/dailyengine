' Sends the daily digest via WSL with no visible window.
' Invoked by the "DailyDigestEmail" scheduled task. Output is appended to
' data/digest/send.log so each run can be inspected.
Set sh = CreateObject("WScript.Shell")
sh.Run "wsl.exe -d Ubuntu -e bash -lc ""cd /mnt/c/Users/nkotikal/Desktop/bldr && python3 tools/send_digest.py >> data/digest/send.log 2>&1""", 0, False
