Param(
    [string]$InnoSetupPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$issPath = Join-Path $scriptDir 'rr_billing_setup.iss'

if (-not (Test-Path $issPath)) {
    Write-Error "Installer script not found: $issPath"
    exit 1
}

if (-not (Test-Path $InnoSetupPath)) {
    Write-Warning "Inno Setup compiler not found at: $InnoSetupPath"
    Write-Host "Install Inno Setup from https://jrsoftware.org/isinfo.php then rerun this script."
    Write-Host "Or run: & \"$InnoSetupPath\" \"$issPath\""
    exit 1
}

Write-Host "Building installer with Inno Setup..."
& $InnoSetupPath $issPath

if ($LASTEXITCODE -eq 0) {
    Write-Host "Installer built successfully."
    Write-Host "See output in: $(Resolve-Path ..\dist\installer)"
} else {
    Write-Error "Installer build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}
