; ═════════════════════════════════════════════════════════════════════════════
; RR BILLING PRO v2.3 - Inno Setup Installer Script
; Build Date: 2026-06-24
; For: RR CCTV - Rental TV & PS Billing System
; ═════════════════════════════════════════════════════════════════════════════

#define MyAppName "RR BILLING PRO"
#define MyAppVersion "2.3"
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
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=no
DisableProgramGroupPage=no
DisableWelcomePage=no
PrivilegesRequired=admin
OutputBaseFilename=RR_BILLING_PRO_v2.3_Setup
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
Source: "C:\BillingPSkuDesktop\dist\main.exe"; DestDir: "{app}"; Flags: ignoreversion

; ── Essential Assets ────────────────────────────────────────────────────────
Source: "C:\BillingPSkuDesktop\logo.png"; DestDir: "{app}"; Flags: ignoreversion

; ── Configuration Files (user can customize) ────────────────────────────────
Source: "C:\BillingPSkuDesktop\rr_billing_config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\BillingPSkuDesktop\rr_billing_license.json"; DestDir: "{app}"; Flags: ignoreversion

; ── Security & Update Keys ──────────────────────────────────────────────────
Source: "C:\BillingPSkuDesktop\update_pubkey.pem"; DestDir: "{app}"; Flags: ignoreversion

; ── Documentation ───────────────────────────────────────────────────────────
Source: "C:\BillingPSkuDesktop\DEPLOYMENT_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\BillingPSkuDesktop\GIT_UPDATE_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion

; ── Shortcuts ───────────────────────────────────────────────────────────────
Source: "C:\BillingPSkuDesktop\BUKA_APLIKASI.bat"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; Create data directories
Name: "{app}\backup"; Permissions: everyone-modify
Name: "{app}\logs"; Permissions: everyone-modify
Name: "{app}\data"; Permissions: everyone-modify

[Registry]
; Store installation path for updates
Root: HKLM; Subkey: "Software\RR CCTV\RR BILLING PRO"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: createvalueifdoesntexist uninsdeletekey
Root: HKLM; Subkey: "Software\RR CCTV\RR BILLING PRO"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: createvalueifdoesntexist

; File association for .myp files (billing profile)
Root: HKCR; Subkey: ".myp"; ValueType: string; ValueName: ""; ValueData: "RRBillingProfile"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "RRBillingProfile"; ValueType: string; ValueName: ""; ValueData: "RR Billing Profile"; Flags: uninsdeletekey
Root: HKCR; Subkey: "RRBillingProfile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "RRBillingProfile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.png"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\logo.png"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.png"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: dirifempty; Name: "{app}"
Type: dirifempty; Name: "{group}"
Type: files; Name: "{app}\*.log"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MsgBox('RR BILLING PRO v{#MyAppVersion} installation complete!' + #13#10 + #13#10 +
           'Installation Path: {app}' + #13#10 + #13#10 +
           'For updates, visit: {#MyAppURL}' + #13#10 +
           'For updates via Git: Use update command in app menu.',
           mbInformation, MB_OK);
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  MsgBox('Uninstalling RR BILLING PRO v{#MyAppVersion}.' + #13#10 +
         'Your data files in {app} will be preserved.', mbInformation, MB_OK);
  Result := True;
end;
