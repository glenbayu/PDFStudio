; PDF Studio - Inno Setup 6 Installer Script (per-user, no admin required)
#define MyAppName "PDF Studio"
#define MyAppVersion "1.2"
#define MyAppPublisher "PDF Studio"
#define MyAppExeName "PDFStudio.exe"
#define MyAppProgId "PDFStudio.Document"

[Setup]
AppId={{8E2D7A4C-5B91-4E3A-9C12-6F0A3D8B1E24}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\PDFStudio
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=PDFStudio-Setup-{#MyAppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "pdfassoc"; Description: "Register PDF Studio in Windows &Open with && Default Apps for .pdf files"; GroupDescription: "File association:"

[Files]
Source: "..\dist\PDFStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "PDF reader & editor desktop"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "PDF reader & editor desktop"; Tasks: desktopicon

[Registry]
; Per-user .pdf file association ("Open with PDF Studio" + Settings -> Default Apps)
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF Document (PDF Studio)"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"",0"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\{#MyAppProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppProgId}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\PDFStudio\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\PDFStudio\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "PDF editor dan pembaca desktop untuk Windows"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\PDFStudio\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyAppProgId}"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "PDFStudio"; ValueData: "Software\PDFStudio\Capabilities"; Flags: uninsdeletevalue; Tasks: pdfassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
