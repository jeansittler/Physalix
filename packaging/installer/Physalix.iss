; Invoked by scripts/build_release.ps1. AppId must never change between releases.
#ifndef AppVersion
  #error AppVersion must be supplied by build_release.ps1
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build_release.ps1
#endif
#ifndef ArtifactDir
  #error ArtifactDir must be supplied by build_release.ps1
#endif

[Setup]
AppId={{807A4F23-674E-4CD3-9B57-D66B7B819B72}
AppName=Physalyx
AppVersion={#AppVersion}
AppVerName=Physalyx {#AppVersion}
VersionInfoVersion={#AppVersion}.0
AppPublisher=Jean Sittler
DefaultDirName={autopf}\Physalyx
DisableDirPage=no
DefaultGroupName=Physalyx
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
UsePreviousAppDir=yes
UsePreviousTasks=yes
UninstallDisplayName=Physalyx
UninstallDisplayIcon={app}\Physalyx.exe
SetupIconFile=..\..\physalix\ui\resources\branding\icon_physalix.ico
OutputDir={#ArtifactDir}
OutputBaseFilename=Physalyx-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ChangesAssociations=yes
#ifdef ExternalSignedUninstallerDir
SignedUninstaller=yes
SignedUninstallerDir={#ExternalSignedUninstallerDir}
#else
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#else
SignedUninstaller=no
#endif
#endif

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove only known 1.8.x program artifacts. Never delete projects or user data.
Type: files; Name: "{app}\Physalix.exe"
Type: files; Name: "{autoprograms}\Physalix.lnk"
Type: files; Name: "{autodesktop}\Physalix.lnk"

[Icons]
Name: "{autoprograms}\Physalyx"; Filename: "{app}\Physalyx.exe"; WorkingDir: "{userdocs}"; AppUserModelID: "Physalix.Physalix"
Name: "{autodesktop}\Physalyx"; Filename: "{app}\Physalyx.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon; AppUserModelID: "Physalix.Physalix"

[Registry]
Root: HKCR; Subkey: ".physalix"; ValueType: string; ValueName: ""; ValueData: "Physalix.Project"; Flags: uninsdeletevalue
Root: HKCR; Subkey: ".physalyx"; ValueType: string; ValueName: ""; ValueData: "Physalix.Project"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "Physalix.Project"; ValueType: string; ValueName: ""; ValueData: "Projet Physalyx"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Physalix.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Physalyx.exe,0"
Root: HKCR; Subkey: "Physalix.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Physalyx.exe"" ""%1"""

[Run]
Filename: "{app}\Physalyx.exe"; Description: "Lancer Physalyx"; WorkingDir: "{userdocs}"; Flags: nowait postinstall skipifsilent

; Intentionally no wildcard InstallDelete/UninstallDelete: preserve personal files.
; The stable AppId reuses the installation and its uninstall log on upgrade.
