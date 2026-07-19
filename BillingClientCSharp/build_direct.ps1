$csc = "C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\Roslyn\csc.exe"
$refdir = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319"
$srcdir = "C:\Aplikasi VSC\BillingPSkuDesktop\BillingClientCSharp"
$outdir = "$srcdir\dist"

if (-not (Test-Path $outdir)) { New-Item -ItemType Directory -Path $outdir -Force | Out-Null }

$common = @(
    "/reference:$refdir\System.dll"
    "/reference:$refdir\System.Core.dll"
    "/reference:$refdir\Microsoft.CSharp.dll"
)

Write-Host "`n[1/3] Building BillingLockScreenUI..."
& $csc /target:winexe /platform:x64 /optimize+ `
    $common `
    "/reference:$refdir\System.Windows.Forms.dll" `
    "/reference:$refdir\System.Drawing.dll" `
    "/out:$outdir\BillingLockScreenUI.exe" `
    "$srcdir\BillingLockScreenUI\Program.cs" `
    "$srcdir\BillingLockScreenUI\LockScreenForm.cs"
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "OK - BillingLockScreenUI.exe`n"

Write-Host "[2/3] Building BillingClientService..."
& $csc /target:exe /platform:x64 /optimize+ `
    $common `
    "/reference:$refdir\System.Configuration.Install.dll" `
    "/reference:$refdir\System.ServiceProcess.dll" `
    "/reference:$refdir\System.IO.Pipes.dll" `
    "/out:$outdir\BillingClientService.exe" `
    "$srcdir\BillingClientService\Program.cs" `
    "$srcdir\BillingClientService\ServiceCore.cs" `
    "$srcdir\BillingClientService\DesktopLocker.cs"
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "OK - BillingClientService.exe`n"

Write-Host "[3/3] Building BillingClientApp..."
& $csc /target:winexe /platform:x64 /optimize+ `
    $common `
    "/reference:$refdir\System.Windows.Forms.dll" `
    "/reference:$refdir\System.Drawing.dll" `
    "/reference:$refdir\System.IO.Pipes.dll" `
    "/out:$outdir\BillingClientApp.exe" `
    "$srcdir\BillingClientApp\Program.cs" `
    "$srcdir\BillingClientApp\ClientAppForm.cs" `
    "$srcdir\BillingClientApp\DesktopLocker.cs"
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "OK - BillingClientApp.exe`n"

Write-Host "=== BUILD SELESAI! ==="
Write-Host "Output: $outdir"
