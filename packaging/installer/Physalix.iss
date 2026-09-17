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
AppName=Physalix
AppVersion={#AppVersion}
AppVerName=Physalix {#AppVersion}
VersionInfoVersion={#AppVersion}.0
DefaultDirName={autopf}\Physalix
DisableDirPage=no
DefaultGroupName=Physalix
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
UsePreviousAppDir=yes
UsePreviousTasks=yes
UninstallDisplayName=Physalix
UninstallDisplayIcon={app}\Physalix.exe
SetupIconFile=..\..\physalix\ui\resources\branding\icon_physalix.ico
OutputDir={#ArtifactDir}
OutputBaseFilename=Physalix-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ChangesAssociations=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Physalix"; Filename: "{app}\Physalix.exe"; WorkingDir: "{userdocs}"; AppUserModelID: "Physalix.Physalix"
Name: "{autodesktop}\Physalix"; Filename: "{app}\Physalix.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon; AppUserModelID: "Physalix.Physalix"

[Registry]
Root: HKCR; Subkey: ".physalix"; ValueType: string; ValueName: ""; ValueData: "Physalix.Project"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "Physalix.Project"; ValueType: string; ValueName: ""; ValueData: "Projet Physalix"; Flags: uninsdeletekey
Root: HKCR; Subkey: "Physalix.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Physalix.exe,0"
Root: HKCR; Subkey: "Physalix.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Physalix.exe"" ""%1"""

[Run]
Filename: "{app}\Physalix.exe"; Description: "Lancer Physalix"; WorkingDir: "{userdocs}"; Flags: nowait postinstall skipifsilent

; Intentionally no wildcard InstallDelete/UninstallDelete: preserve personal files.
; The stable AppId reuses the installation and its uninstall log on upgrade.
