; RR Billing Pro installer script for Inno Setup
; Generates a Windows installer that copies the built exe and support files.

[Setup]
AppName=RR Billing Pro
AppVersion=2.1
DefaultDirName={pf64}\RR Billing Pro
DefaultGroupName=RR Billing Pro
DisableProgramGroupPage=yes
ShowLanguageDialog=no
OutputDir=..\dist\installer
OutputBaseFilename=RRBillingProSetup
Compression=lzma
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\RRBILLINGPRO\RRBILLINGPRO.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\rr_billing_config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\rr_billing_license.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\logo.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\update_pubkey.pem"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\RR Billing Pro"; Filename: "{app}\RRBILLINGPRO.exe"
Name: "{commondesktop}\RR Billing Pro"; Filename: "{app}\RRBILLINGPRO.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\RRBILLINGPRO.exe"; Description: "Launch RR Billing Pro"; Flags: nowait postinstall skipifsilent
