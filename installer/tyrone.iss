; Inno Setup script - builds TyroneSetup-<version>.exe from the PyInstaller output.
; Per-user install (no admin rights needed).

#define AppVersion GetEnv("TYRONE_VERSION")
#if AppVersion == ""
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6E2C3F1B-6B7A-4E2B-9D4C-7A1F0C5E9A11}
AppName=Tyrone
AppVersion={#AppVersion}
AppPublisher=Tyrone
DefaultDirName={localappdata}\Programs\Tyrone
DefaultGroupName=Tyrone
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=TyroneSetup-{#AppVersion}
SetupIconFile=..\assets\tyrone.ico
UninstallDisplayIcon={app}\Tyrone.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "startup"; Description: "Start Tyrone when I sign in to Windows"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Options:"

[Files]
Source: "..\dist\Tyrone\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\Tyrone"; Filename: "{app}\Tyrone.exe"
Name: "{userstartup}\Tyrone"; Filename: "{app}\Tyrone.exe"; Tasks: startup
Name: "{userdesktop}\Tyrone"; Filename: "{app}\Tyrone.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Tyrone.exe"; Description: "Launch Tyrone"; Flags: nowait postinstall skipifsilent

; Your memory and settings live in %APPDATA%\Tyrone and are NOT removed on uninstall.
