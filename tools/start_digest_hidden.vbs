' Launches the Daily Digest server inside WSL with no visible window.
' Invoked at logon by the "DailyDigestServer" scheduled task.
Set sh = CreateObject("WScript.Shell")
sh.Run "wsl.exe -d Ubuntu -e bash -lc ""bash '/mnt/c/Users/nkotikal/Desktop/bldr/tools/start_digest_server.sh'""", 0, False
