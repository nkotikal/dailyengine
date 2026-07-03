' Launches the Daily Digest server inside WSL with no visible window.
' Self-locating: derives the WSL path from this script's own location, so it works
' wherever the repo is cloned. Invoked at logon by the "DailyDigestServer" task.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
toolsDir = fso.GetParentFolderName(WScript.ScriptFullName)        ' e.g. C:\path\bldr\tools
drive = LCase(Left(toolsDir, 1))
wslTools = "/mnt/" & drive & Replace(Mid(toolsDir, 3), "\", "/")  ' /mnt/c/path/bldr/tools
sh.Run "wsl.exe -e bash -lc ""bash '" & wslTools & "/start_digest_server.sh'""", 0, False
