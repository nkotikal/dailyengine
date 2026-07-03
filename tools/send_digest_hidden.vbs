' Sends the daily digest via WSL with no visible window.
' Self-locating: derives the WSL path from this script's own location, so it works
' wherever the repo is cloned. Invoked by the "DailyDigestEmail" scheduled task.
' Output is appended to data/digest/send.log so each run can be inspected.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
toolsDir = fso.GetParentFolderName(WScript.ScriptFullName)        ' e.g. C:\path\bldr\tools
drive = LCase(Left(toolsDir, 1))
wslTools = "/mnt/" & drive & Replace(Mid(toolsDir, 3), "\", "/")  ' /mnt/c/path/bldr/tools
sh.Run "wsl.exe -e bash -lc ""cd '" & wslTools & "/..' && python3 tools/send_digest.py >> data/digest/send.log 2>&1""", 0, False
