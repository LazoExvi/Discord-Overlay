; Inno Setup script: per-user installer, no admin rights, Start Menu shortcut.
; Compiled by scripts/build_windows.ps1 -Installer and by the release workflow.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceRoot
  #define SourceRoot "..\dist\DiscordOverlay"
#endif
#define ProductName "Discord Overlay"

[Setup]
AppId={{4C6E9B2A-8D1F-4F3B-9A7E-2B5C8D0E1F63}
AppName={#ProductName}
AppVersion={#AppVersion}
AppVerName={#ProductName} {#AppVersion}
AppPublisher=LazoExvi
DefaultDirName={localappdata}\Programs\DiscordOverlay
DefaultGroupName={#ProductName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=output
OutputBaseFilename=DiscordOverlay-Setup-{#AppVersion}
SetupIconFile=..\discord_overlay\assets\icon.ico
UninstallDisplayIcon={app}\DiscordOverlay.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#ProductName}
VersionInfoProductVersion={#AppVersion}
VersionInfoDescription={#ProductName} installer

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#ProductName}"; Filename: "{app}\DiscordOverlay.exe"
Name: "{group}\Uninstall {#ProductName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\DiscordOverlay.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DiscordOverlay.exe"; Description: "Launch {#ProductName}"; Flags: nowait postinstall skipifsilent

; Settings under %LOCALAPPDATA%\DiscordOverlay are deliberately left in place on uninstall.
