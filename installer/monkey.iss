; RETIRED: Monkey now installs and updates through Velopack (see docs/UPDATES.md).
; Kept only because monkey/cleanup.py uses this AppId to find and uninstall old installs.
; Inno Setup script - builds MonkeySetup-<version>.exe from the PyInstaller output.
; Per-user install (no admin rights needed).

#define AppVersion GetEnv("MONKEY_VERSION")
#if AppVersion == ""
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6E2C3F1B-6B7A-4E2B-9D4C-7A1F0C5E9A11}
AppName=Monkey
AppVersion={#AppVersion}
AppPublisher=Monkey
DefaultDirName={localappdata}\Programs\Monkey
DefaultGroupName=Monkey
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=MonkeySetup-{#AppVersion}
SetupIconFile=..\assets\monkey.ico
UninstallDisplayIcon={app}\Monkey.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "startup"; Description: "Start Monkey when I sign in to Windows"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Options:"

[Files]
Source: "..\dist\Monkey\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\Monkey"; Filename: "{app}\Monkey.exe"
Name: "{userstartup}\Monkey"; Filename: "{app}\Monkey.exe"; Tasks: startup
Name: "{userdesktop}\Monkey"; Filename: "{app}\Monkey.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Monkey.exe"; Description: "Launch Monkey"; Flags: nowait postinstall skipifsilent

; Your memory and settings live in %APPDATA%\Monkey and are NOT removed on uninstall.
