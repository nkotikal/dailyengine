; Inno Setup script for Daily Digest.
; Build the exe first (pyinstaller DailyDigest.spec), then compile this with
; Inno Setup 6:  ISCC.exe installer.iss  ->  Output\DailyDigest-Setup.exe
;
; Installs per-user (no admin needed), registers two Scheduled Tasks (server at
; logon + the 07:00 daily email), creates a Start-menu shortcut, and seeds a
; .env in %APPDATA%\DailyDigest for the user to fill in their keys.

#define AppName "Daily Digest"
#define AppExe "DailyDigest.exe"
#define AppVersion "1.0.0"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\DailyDigest
DefaultGroupName=Daily Digest
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=DailyDigest-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}

[Files]
; The entire PyInstaller onedir output.
Source: "dist\DailyDigest\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Daily Digest"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall Daily Digest"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Daily Digest"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "autostart"; Description: "Start the app automatically at logon (so the dashboard is always available)"
Name: "morningmail"; Description: "Email the digest every morning at 7:00 AM"

[Run]
; Seed a .env the user can edit (only if one isn't already there), then open it.
Filename: "{cmd}"; Parameters: "/c if not exist ""{userappdata}\DailyDigest\.env"" ( mkdir ""{userappdata}\DailyDigest"" 2>nul & copy ""{app}\.env.example"" ""{userappdata}\DailyDigest\.env"" )"; Flags: runhidden
Filename: "notepad.exe"; Parameters: """{userappdata}\DailyDigest\.env"""; Description: "Open .env to add your OpenAI key and email settings"; Flags: postinstall skipifsilent

; Register the at-logon server task (runs the windowed exe; no console).
Filename: "schtasks"; Parameters: "/Create /TN ""DailyDigestServer"" /TR ""'{app}\{#AppExe}'"" /SC ONLOGON /F"; Flags: runhidden; Tasks: autostart
; Register the daily 07:00 email task.
Filename: "schtasks"; Parameters: "/Create /TN ""DailyDigestEmail"" /TR ""'{app}\{#AppExe}' --send"" /SC DAILY /ST 07:00 /F"; Flags: runhidden; Tasks: morningmail

; Offer to launch the dashboard right after install.
Filename: "{app}\{#AppExe}"; Description: "Launch Daily Digest now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "schtasks"; Parameters: "/Delete /TN ""DailyDigestServer"" /F"; Flags: runhidden; RunOnceId: "DelServerTask"
Filename: "schtasks"; Parameters: "/Delete /TN ""DailyDigestEmail"" /F"; Flags: runhidden; RunOnceId: "DelEmailTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
