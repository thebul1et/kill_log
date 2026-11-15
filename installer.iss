; Inno Setup script - builds a normal Windows installer around dist\RobRunDeathLog
[Setup]
AppName=Rob Run Death Log
AppVersion=1.0
DefaultDirName={autopf}\RobRunDeathLog
DefaultGroupName=Rob Run Death Log
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=RobRunDeathLog-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayName=Rob Run Death Log

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "autostart"; Description: "Start with Windows (waits quietly in the tray until Rob Run opens)"

[Files]
Source: "dist\RobRunDeathLog\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Rob Run Death Log"; Filename: "{app}\RobRunDeathLog.exe"
Name: "{autodesktop}\Rob Run Death Log"; Filename: "{app}\RobRunDeathLog.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "RobRunDeathLog"; ValueData: """{app}\RobRunDeathLog.exe"" --background"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\RobRunDeathLog.exe"; Description: "Open Rob Run Death Log now"; Flags: nowait postinstall skipifsilent
