; ═════════════════════════════════════════════════════════════════════════════
; RR BILLING PRO v2.3.1 - Inno Setup Installer Script
; Build Date: 2026-06-24
; For: RR CCTV - Rental TV & PS Billing System
; ═════════════════════════════════════════════════════════════════════════════

#define MyAppName "RR BILLING PRO"
#define MyAppVersion "2.3.1"
#define MyAppPublisher "RR CCTV, Inc."
#define MyAppURL "https://www.rrcctv.online"
#define MyAppExeName "main.exe"

[Setup]
AppId={{A4605966-F3CC-4DA2-9E3D-CD66177081F6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=C:\BillingPSkuDesktop\inno_build\app\logo.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=no
DisableProgramGroupPage=no
DisableWelcomePage=no
PrivilegesRequired=admin
OutputBaseFilename=RR_BILLING_PRO_v2.3.1_Setup
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} - Rental TV & PS Billing System

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "sendto"; Description: "Add to Send To menu"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ── Main Application ────────────────────────────────────────────────────────
Source: "C:\BillingPSkuDesktop\inno_build\app\main.exe"; DestDir: "{app}"; Flags: ignoreversion

; ── Essential Assets ────────────────────────────────────────────────────────
Source: "C:\BillingPSkuDesktop\inno_build\app\logo.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\BillingPSkuDesktop\inno_build\app\logo.ico"; DestDir: "{app}"; Flags: ignoreversion

; ── Configuration Files (user can customize) ────────────────────────────────
Source: "C:\BillingPSkuDesktop\inno_build\app\rr_billing_config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\BillingPSkuDesktop\inno_build\app\rr_billing_license.json"; DestDir: "{app}"; Flags: ignoreversion

; ── Security & Update Keys ──────────────────────────────────────────────────
Source: "C:\BillingPSkuDesktop\inno_build\app\update_pubkey.pem"; DestDir: "{app}"; Flags: ignoreversion

; ── Git Repository (for Git update feature) ──────────────────────────────────
Source: "C:\BillingPSkuDesktop\inno_build\app\.git\*"; DestDir: "{app}\.git"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; ── File Associations ──────────────────────────────────────────────────────
Root: HKCR; Subkey: ".rr"; ValueType: string; ValueName: ""; ValueData: "RRBillingFile"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "RRBillingFile"; ValueType: string; ValueName: ""; ValueData: "RR Billing File"; Flags: uninsdeletekey
Root: HKCR; Subkey: "RRBillingFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "RRBillingFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

; ── RR Billing Profile ─────────────────────────────────────────────────────
Root: HKCR; Subkey: "RRBillingProfile"; ValueType: string; ValueName: ""; ValueData: "RR Billing Profile"; Flags: uninsdeletekey
Root: HKCR; Subkey: "RRBillingProfile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "RRBillingProfile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\logo.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: dirifempty; Name: "{app}"
Type: dirifempty; Name: "{group}"
