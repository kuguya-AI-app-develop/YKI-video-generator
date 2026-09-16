#requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$AppPython = Join-Path $ProjectRoot 'runtime/app-env/Scripts/python.exe'
$StatePath = Join-Path $ProjectRoot 'runtime/install-state.json'
$LockPath = Join-Path $ProjectRoot 'config/models.lock.json'
$Ready = $false
$RepairNeeded = $false
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:HF_HOME = Join-Path $ProjectRoot 'runtime/cache/huggingface'
$env:TORCH_HOME = Join-Path $ProjectRoot 'runtime/cache/torch'

try {
    if ((Test-Path -LiteralPath $AppPython) -and (Test-Path -LiteralPath $StatePath)) {
        try {
            $State = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            $ManifestHash = (Get-FileHash -LiteralPath $LockPath -Algorithm SHA256).Hash
            $RequirementsHash = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'requirements-windows.lock') -Algorithm SHA256).Hash
            $BootstrapHash = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'bootstrap.ps1') -Algorithm SHA256).Hash
            $CudaCheckHash = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'check_cuda.py') -Algorithm SHA256).Hash
            $Ready = (
                $State.status -eq 'ready' -and
                $State.manifest_sha256 -eq $ManifestHash -and
                $State.requirements_sha256 -eq $RequirementsHash -and
                $State.bootstrap_sha256 -eq $BootstrapHash -and
                $State.cuda_check_sha256 -eq $CudaCheckHash
            )
        } catch { $Ready = $false }
    }
    if ($Ready) {
        Write-Host '[YKI-video-generator] Checking the local installation.' -ForegroundColor Cyan
        Push-Location $ProjectRoot
        try {
            $DoctorOutput = & $AppPython -m app doctor --json | Out-String
            $Ready = $LASTEXITCODE -eq 0
            if (-not $Ready) { $RepairNeeded = $true; Write-Host $DoctorOutput }
        } finally { Pop-Location }
    }
    if (-not $Ready) {
        Write-Host '[YKI-video-generator] Installation is missing or the manifest changed. Starting the installer.' -ForegroundColor Cyan
        $BootstrapArguments = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'bootstrap.ps1'))
        if ($RepairNeeded) { $BootstrapArguments += '-Repair' }
        & powershell.exe @BootstrapArguments
        if ($LASTEXITCODE -eq 3010) {
            Write-Host '[YKI-video-generator] Microsoft VC++ was installed. Restart Windows, then run Start-Windows.bat again.' -ForegroundColor Yellow
            exit 3010
        }
        if ($LASTEXITCODE -ne 0) { throw 'Installation did not complete. See runtime/logs and the error above.' }
    }
    Push-Location $ProjectRoot
    try {
        Write-Host '[YKI-video-generator] Opening the local video creator. Keep this window open; press Ctrl+C to stop.' -ForegroundColor Cyan
        & $AppPython -m app serve --open
        if ($LASTEXITCODE -ne 0) { throw "Video creator exited with code $LASTEXITCODE." }
    } finally { Pop-Location }
} catch {
    Write-Host "`nSTART FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
