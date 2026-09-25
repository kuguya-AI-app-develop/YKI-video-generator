#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Plan,
    [switch]$SkipModels,
    [switch]$Repair
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$LockPath = Join-Path $ProjectRoot 'config/models.lock.json'
$StatePath = Join-Path $ProjectRoot 'runtime/install-state.json'
$Manifest = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Write-Step([string]$Message) {
    Write-Host "`n[YKI-video-generator] $Message" -ForegroundColor Cyan
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Executable $($Arguments -join ' ')"
    }
}

function Get-Asset([string]$Id) {
    $Matches = @($Manifest.assets | Where-Object { $_.id -eq $Id })
    if ($Matches.Count -ne 1) { throw "Expected exactly one asset named '$Id' in $LockPath" }
    return $Matches[0]
}

function Get-ProjectPath([string]$RelativePath) {
    $Result = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $RelativePath))
    $Prefix = $ProjectRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $Result.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Manifest path escapes the project: $RelativePath"
    }
    return $Result
}

function Test-AssetFile($Asset, [string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne [long]$Asset.size) { return $false }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Asset.sha256
}

function Save-BootstrapAsset($Asset) {
    $Destination = Get-ProjectPath $Asset.path
    if (Test-AssetFile $Asset $Destination) { return $Destination }
    New-Item -ItemType Directory -Path (Split-Path $Destination -Parent) -Force | Out-Null
    if (Test-Path -LiteralPath $Destination) {
        Move-Item -LiteralPath $Destination -Destination ($Destination + '.invalid-' + [Guid]::NewGuid().ToString('N'))
    }
    $Partial = $Destination + '.part'
    $CurlPath = (Get-Command curl.exe -ErrorAction Stop).Source
    Write-Step "Downloading verified bootstrap: $($Asset.id)"
    Invoke-Checked $CurlPath @('--fail', '--location', '--retry', '5', '--retry-delay', '3', '--connect-timeout', '30', '--continue-at', '-', '--output', $Partial, $Asset.url)
    if (-not (Test-AssetFile $Asset $Partial)) {
        Move-Item -LiteralPath $Partial -Destination ($Partial + '.invalid-' + [Guid]::NewGuid().ToString('N'))
        throw "Bootstrap size or SHA256 mismatch. The invalid download was preserved; run Install-Windows.bat again."
    }
    Move-Item -LiteralPath $Partial -Destination $Destination
    return $Destination
}

function Expand-RuntimeAsset($Asset, [string]$DestinationRelative, [string]$RequiredName, [switch]$Flatten, [switch]$SevenZip) {
    $Destination = Get-ProjectPath $DestinationRelative
    $Marker = Join-Path $Destination ('.installed-' + $Asset.id + '.sha256')
    $Existing = @(Get-ChildItem -LiteralPath $Destination -Filter $RequiredName -File -Recurse -ErrorAction SilentlyContinue)
    if (-not $Repair -and (Test-Path -LiteralPath $Marker) -and $Existing.Count -gt 0) {
        if ((Get-Content -LiteralPath $Marker -Raw).Trim() -eq $Asset.sha256) {
            return
        }
    }
    $ArchivePath = Get-ProjectPath $Asset.path
    if (-not (Test-AssetFile $Asset $ArchivePath)) { throw "Invalid archive: $ArchivePath" }
    $Stage = Get-ProjectPath ('runtime/staging/' + $Asset.id + '-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Stage -Force | Out-Null
    Write-Step "Extracting $($Asset.id) (this can take several minutes)"
    if ($SevenZip) {
        Invoke-Checked $script:AppPython @('-m', 'py7zr', 'x', $ArchivePath, $Stage)
    } else {
        Expand-Archive -LiteralPath $ArchivePath -DestinationPath $Stage -Force
    }
    $RequiredFiles = @(Get-ChildItem -LiteralPath $Stage -Filter $RequiredName -File -Recurse)
    if ($RequiredFiles.Count -ne 1) {
        throw "Archive must contain exactly one $RequiredName; found $($RequiredFiles.Count). Extraction retained at $Stage"
    }
    $Source = $Stage
    if ($Flatten) { $Source = Split-Path $RequiredFiles[0].FullName -Parent }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    # Keep verified source archives and staging files so interrupted extraction is recoverable.
    Get-ChildItem -LiteralPath $Source -Force | Copy-Item -Destination $Destination -Recurse -Force
    $Asset.sha256 | Set-Content -LiteralPath $Marker -Encoding ASCII
}

function Get-MissingVcRuntimeDlls {
    $LlamaDirectory = Join-Path $ProjectRoot 'runtime/llama'
    $SystemDirectory = [Environment]::SystemDirectory
    foreach ($Name in @('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll')) {
        if (-not (Test-Path -LiteralPath (Join-Path $LlamaDirectory $Name) -PathType Leaf) -and
            -not (Test-Path -LiteralPath (Join-Path $SystemDirectory $Name) -PathType Leaf)) {
            $Name
        }
    }
}

function Install-MissingVcRuntime {
    $MissingDlls = @(Get-MissingVcRuntimeDlls)
    if ($MissingDlls.Count -eq 0) { return $false }
    Write-Step "Missing Microsoft VC++ runtime: $($MissingDlls -join ', ')"
    # Microsoft publishes this rolling x64 URL, so verify Authenticode instead
    # of pretending a fixed old checksum represents the latest system runtime.
    # https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist
    $SourceUrl = 'https://aka.ms/vc14/vc_redist.x64.exe'
    $ReceiptId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $InstallerPath = Join-Path $ProjectRoot ('runtime/downloads/vc_redist.x64-' + $ReceiptId + '.exe')
    $InstallerLog = Join-Path $ProjectRoot ('runtime/logs/vc-redist-' + $ReceiptId + '.log')
    $ReceiptPath = Join-Path $ProjectRoot ('runtime/logs/vc-redist-' + $ReceiptId + '.json')
    New-Item -ItemType Directory -Path (Split-Path $InstallerPath -Parent) -Force | Out-Null
    $CurlPath = (Get-Command curl.exe -ErrorAction Stop).Source
    Invoke-Checked $CurlPath @('--fail', '--location', '--proto', '=https', '--proto-redir', '=https', '--retry', '5', '--connect-timeout', '30', '--output', $InstallerPath, $SourceUrl)
    $Signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
    if ($Signature.Status -ne 'Valid' -or $null -eq $Signature.SignerCertificate -or
        $Signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) -ne 'Microsoft Corporation' -or
        $Signature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        throw "Refusing to execute VC++ installer: a valid Microsoft Corporation signature is required (status: $($Signature.Status)). File retained at $InstallerPath"
    }
    $Receipt = [ordered]@{
        source_url = $SourceUrl
        downloaded_at = [DateTime]::UtcNow.ToString('o')
        path = $InstallerPath
        sha256 = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
        file_version = (Get-Item -LiteralPath $InstallerPath).VersionInfo.FileVersion
        signer = $Signature.SignerCertificate.Subject
        certificate_thumbprint = $Signature.SignerCertificate.Thumbprint
        signature_status = [string]$Signature.Status
        missing_dlls = $MissingDlls
        installer_log = $InstallerLog
        exit_code = $null
        normalized_exit_code = $null
    }
    $Receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
    Write-Step 'Installing verified Microsoft VC++ x64 system runtime. Windows may ask for administrator approval (UAC).'
    Write-Host "This updates shared Windows runtime libraries. Automatic restart is disabled. Log: $InstallerLog"
    try {
        # Start-Process joins its argument array; quote the log path explicitly
        # for installation directories containing spaces (valid Windows paths cannot contain quotes).
        $InstallerArguments = @('/install', '/passive', '/norestart', '/log', ('"' + $InstallerLog + '"'))
        $Process = Start-Process -FilePath $InstallerPath -ArgumentList $InstallerArguments -Verb RunAs -PassThru -Wait
        $RawExitCode = [int]$Process.ExitCode
        $Process.Dispose()
    } catch {
        throw "The Microsoft VC++ installer did not run or UAC was declined. Rerun Install-Windows.bat when administrator approval is available. Receipt: $ReceiptPath. Details: $($_.Exception.Message)"
    }
    $UnsignedCode = [BitConverter]::ToUInt32([BitConverter]::GetBytes($RawExitCode), 0)
    $ExitCode = $UnsignedCode
    # The bootstrapper can return HRESULT_FROM_WIN32 (for example 0x80070666).
    if (($UnsignedCode -band 4294901760L) -eq 2147942400L) { $ExitCode = $UnsignedCode -band 65535L }
    $Receipt.exit_code = $RawExitCode
    $Receipt.normalized_exit_code = $ExitCode
    $Receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
    if ($ExitCode -eq 3010 -or $ExitCode -eq 1641) {
        Write-Host "Microsoft VC++ installation succeeded and requires a Windows restart (exit $ExitCode)."
        return $true
    }
    if ($ExitCode -eq 1638) {
        Write-Host 'Microsoft reports another VC++ version is already installed; checking required DLLs before continuing.'
    } elseif ($ExitCode -ne 0) {
        throw "Microsoft VC++ installation failed (exit $RawExitCode, normalized $ExitCode). See $InstallerLog and $ReceiptPath"
    }
    $Remaining = @(Get-MissingVcRuntimeDlls)
    if ($Remaining.Count -gt 0) {
        throw "Microsoft VC++ DLLs remain missing: $($Remaining -join ', '). Repair the installed x64 runtime using Microsoft's installer, then retry. Log: $InstallerLog"
    }
    return $false
}

if ($Plan) {
    $RuntimeBytes = ($Manifest.assets | Where-Object { $_.group -eq 'runtime' } | Measure-Object -Property size -Sum).Sum
    $ModelBytes = ($Manifest.assets | Where-Object { $_.group -eq 'models' } | Measure-Object -Property size -Sum).Sum
    Write-Host "Project: $ProjectRoot"
    Write-Host "Python: $($Manifest.runtime.python_version); uv: $($Manifest.runtime.uv_version)"
    Write-Host "ComfyUI: $($Manifest.runtime.comfy_version); llama.cpp: $($Manifest.runtime.llama_tag) (CUDA 13.3)"
    Write-Host ('Runtime downloads: {0:N2} GiB; model downloads: {1:N2} GiB' -f ($RuntimeBytes / 1GB), ($ModelBytes / 1GB))
    Write-Host 'Application tools, caches and Python stay under runtime/. No global Python PATH or registration changes.'
    Write-Host 'If required VC++ DLLs are missing, the verified official Microsoft system runtime installer runs (UAC may be required).'
    Write-Host 'Windows 11 x64, NVIDIA GPU, nvidia-smi CUDA Version / CUDA UMD Version >= 13.3 required. RTX 5090 32 GB is the primary target.'
    Write-Host 'Lower-memory GPUs are experimental; see config/experimental-4070s-32gb.json for RTX 4070 Super 12 GB / 32 GB RAM settings. Real generation is not yet validated.'
    Write-Host 'Models include Qwen, H3 and Chinese/English Kokoro TTS. Allow at least 100 GiB of free disk space.'
    exit 0
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not [Environment]::Is64BitProcess) {
    throw 'Installation requires 64-bit Windows PowerShell on Windows 11. Use -Plan to inspect the install manifest.'
}
if ([Environment]::OSVersion.Version.Build -lt 22000) { throw 'Windows 11 or newer is required.' }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$InstallMutex = $null
$HasMutex = $false
$RuntimeLock = $null
$HasRuntimeLock = $false
$TranscriptStarted = $false
try {
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'runtime') -Force | Out-Null
    $PathHasher = [Security.Cryptography.SHA256]::Create()
    try { $ProjectHash = [BitConverter]::ToString($PathHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($ProjectRoot))).Replace('-', '').Substring(0, 16) }
    finally { $PathHasher.Dispose() }
    $InstallMutex = New-Object Threading.Mutex($false, ('Local\AIGC-Install-' + $ProjectHash))
    try { $HasMutex = $InstallMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $HasMutex = $true }
    if (-not $HasMutex) { throw 'Another installer for this project is already running.' }
    # The app holds this same byte-range lock while running. Keep the handle open
    # throughout installation so an app cannot start between a check and repair.
    try {
        $RuntimeLock = [IO.File]::Open((Join-Path $ProjectRoot 'runtime/.studio-runtime.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
        $RuntimeLock.Lock(0, 1)
        $HasRuntimeLock = $true
        if ($RuntimeLock.Length -eq 0) { $RuntimeLock.WriteByte(48); $RuntimeLock.Flush() }
    } catch {
        throw "Cannot acquire the project runtime lock. Stop the video creator with Ctrl+C in its launcher console before installing or repairing, then retry. Details: $($_.Exception.Message)"
    }
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'runtime/logs') -Force | Out-Null
    $LogPath = Join-Path $ProjectRoot ('runtime/logs/install-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    Start-Transcript -LiteralPath $LogPath | Out-Null
    $TranscriptStarted = $true
    Push-Location $ProjectRoot
    [ordered]@{ schema_version = 1; status = 'installing'; started_at = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8

    Write-Step 'Checking GPU, driver and available disk space'
    $NvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $NvidiaSmi) { throw 'NVIDIA driver was not found. Install the current NVIDIA Studio driver, reboot, then retry: https://www.nvidia.com/en-us/drivers/' }
    $GpuSummary = & $NvidiaSmi.Source
    if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed (exit $LASTEXITCODE). Repair or update the NVIDIA driver and reboot." }
    $GpuText = $GpuSummary -join "`n"
    if ($GpuText -notmatch 'CUDA(?:\s+UMD)?\s+Version\s*:\s*(\d+\.\d+)') { throw 'Cannot determine driver CUDA compatibility from nvidia-smi. Expected a numeric CUDA Version or CUDA UMD Version.' }
    if ([version]$Matches[1] -lt [version]'13.3') {
        throw "The bundled llama.cpp needs driver CUDA compatibility >= 13.3; detected $($Matches[1]). Update the NVIDIA Studio driver and reboot: https://www.nvidia.com/en-us/drivers/"
    }
    Write-Host "Detected driver CUDA compatibility $($Matches[1]); satisfies the required >= 13.3."
    $GpuRows = & $NvidiaSmi.Source '--query-gpu=name,memory.total,driver_version' '--format=csv,noheader,nounits'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read GPU details.' }
    $HasEnoughVram = $false
    foreach ($Row in $GpuRows) {
        Write-Host $Row
        $Columns = $Row -split ','
        if ($Columns.Count -ge 2 -and [int]$Columns[1].Trim() -ge 30000) { $HasEnoughVram = $true }
    }
    if (-not $HasEnoughVram) {
        Write-Warning 'GPU memory is below the primary 32 GB target. Lower-memory operation is experimental and real generation is not yet validated. Use config/experimental-4070s-32gb.json for RTX 4070 Super 12 GB / 32 GB RAM; CPU/disk offloading may be slow or run out of memory.'
    }
    $Drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($ProjectRoot).Substring(0, 1))
    # Count missing archive/model bytes and budget extraction plus Python wheels separately.
    $MissingBytes = [long]0
    foreach ($Asset in $Manifest.assets) {
        if ($SkipModels -and $Asset.group -eq 'models') { continue }
        $Candidate = Get-ProjectPath $Asset.path
        if (-not (Test-Path -LiteralPath $Candidate) -or (Get-Item -LiteralPath $Candidate).Length -ne [long]$Asset.size) {
            $MissingBytes += [long]$Asset.size
        }
    }
    $NeededBytes = $MissingBytes + 35GB
    if (-not $SkipModels -and $MissingBytes -gt 50GB) { $NeededBytes = [Math]::Max($NeededBytes, 100GB) }
    if ($Drive.Free -lt $NeededBytes) {
        throw ('Insufficient disk space: {0:N1} GiB free; at least {1:N1} GiB needed for remaining downloads, environments and extraction.' -f ($Drive.Free / 1GB), ($NeededBytes / 1GB))
    }
    $RamBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    Write-Host ('System RAM: {0:N1} GiB' -f ($RamBytes / 1GB))
    if ($RamBytes -lt 60GB) {
        Write-Warning 'Less than 60 GiB system RAM detected. Use the low-memory experimental settings in config/experimental-4070s-32gb.json. CPU/disk offloading may be slow or run out of memory; successful generation is not guaranteed.'
    }

    # Native Python wheels may also need the CRT; repair it before importing any packages.
    if (Install-MissingVcRuntime) {
        [ordered]@{
            schema_version = 1
            status = 'reboot-required'
            reason = 'Microsoft VC++ runtime installation requires a Windows restart.'
            updated_at = [DateTime]::UtcNow.ToString('o')
            log_path = $LogPath
        } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
        Write-Step 'Restart Windows, then run Start-Windows.bat again. Verified downloads will be reused.'
        exit 3010
    }

    $env:UV_CACHE_DIR = Join-Path $ProjectRoot 'runtime/cache/uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $ProjectRoot 'runtime/python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $ProjectRoot 'runtime/python-bin'
    $env:UV_PYTHON_INSTALL_REGISTRY = '0'
    $env:UV_PYTHON_INSTALL_BIN = '0'
    $env:UV_NO_CONFIG = '1'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    $env:HF_HOME = Join-Path $ProjectRoot 'runtime/cache/huggingface'
    $env:TORCH_HOME = Join-Path $ProjectRoot 'runtime/cache/torch'

    $UvAsset = Get-Asset 'uv-bootstrap'
    $null = Save-BootstrapAsset $UvAsset
    Expand-RuntimeAsset $UvAsset 'runtime/uv' 'uv.exe' -Flatten
    $Uv = Join-Path $ProjectRoot 'runtime/uv/uv.exe'
    Write-Step 'Installing isolated Python and application dependencies'
    Invoke-Checked $Uv @('python', 'install', $Manifest.runtime.python_version, '--no-bin', '--no-registry')
    $AppEnv = Join-Path $ProjectRoot 'runtime/app-env'
    $script:AppPython = Join-Path $AppEnv 'Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $script:AppPython)) {
        Invoke-Checked $Uv @('venv', '--python', $Manifest.runtime.python_version, '--managed-python', $AppEnv)
    }
    Invoke-Checked $Uv @('pip', 'install', '--python', $script:AppPython, '--require-hashes', '-r', (Join-Path $ProjectRoot 'requirements-windows.lock'))

    Write-Step 'Downloading pinned application runtimes'
    Invoke-Checked $script:AppPython @('-m', 'app', 'download', '--group', 'runtime')
    Expand-RuntimeAsset (Get-Asset 'llama-runtime') 'runtime/llama' 'llama-server.exe' -Flatten
    Expand-RuntimeAsset (Get-Asset 'llama-cuda') 'runtime/llama' 'cudart64_13.dll' -Flatten
    Expand-RuntimeAsset (Get-Asset 'ffmpeg') 'runtime/ffmpeg' 'ffmpeg.exe'

    Expand-RuntimeAsset (Get-Asset 'comfy-portable') 'runtime/comfy-portable' 'python.exe' -SevenZip
    Write-Step 'Checking installed executables and CUDA support'
    try { Invoke-Checked (Join-Path $ProjectRoot 'runtime/llama/llama-server.exe') @('--version') }
    catch { throw "llama.cpp could not start. Check the driver and missing-DLL message. If a Microsoft VC++ DLL is missing, install the x64 runtime from https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist then rerun the installer. Details: $($_.Exception.Message)" }
    $Ffmpeg = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'runtime/ffmpeg') -Filter 'ffmpeg.exe' -File -Recurse)[0].FullName
    Invoke-Checked $Ffmpeg @('-version')
    $ComfyPython = Join-Path $ProjectRoot 'runtime/comfy-portable/ComfyUI_windows_portable/python_embeded/python.exe'
    $ComfyMain = Join-Path $ProjectRoot 'runtime/comfy-portable/ComfyUI_windows_portable/ComfyUI/main.py'
    if (-not (Test-Path -LiteralPath $ComfyMain)) { throw "Unexpected ComfyUI portable layout: $ComfyMain is missing." }
    # A script path avoids PowerShell 5.1 stripping quotes inside Python -c source.
    Invoke-Checked $ComfyPython @('-s', (Join-Path $PSScriptRoot 'check_cuda.py'))

    if (-not $SkipModels) {
        Write-Step 'Downloading models with SHA256 verification (large download; interrupted transfers can resume)'
        Invoke-Checked $script:AppPython @('-m', 'app', 'download', '--group', 'models')
        Invoke-Checked $script:AppPython @('-m', 'app', 'extract', '--id', 'tts-kokoro')
        Write-Step 'Running final installation diagnostics'
        Invoke-Checked $script:AppPython @('-m', 'app', 'doctor', '--json')
    }
    $State = [ordered]@{
        schema_version = 1
        status = $(if ($SkipModels) { 'runtime-only' } else { 'ready' })
        installed_at = [DateTime]::UtcNow.ToString('o')
        manifest_sha256 = (Get-FileHash -LiteralPath $LockPath -Algorithm SHA256).Hash.ToLowerInvariant()
        requirements_sha256 = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'requirements-windows.lock') -Algorithm SHA256).Hash.ToLowerInvariant()
        bootstrap_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
        cuda_check_sha256 = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'check_cuda.py') -Algorithm SHA256).Hash.ToLowerInvariant()
        python_version = $Manifest.runtime.python_version
        llama_tag = $Manifest.runtime.llama_tag
        comfy_version = $Manifest.runtime.comfy_version
        model_downloads_complete = -not $SkipModels
        log_path = $LogPath
    }
    $State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
    if ($SkipModels) { Write-Step 'Runtime installation complete. Run Install-Windows.bat without -SkipModels to install models.' }
    else { Write-Step 'Installation complete. Double-click Start-Windows.bat to open the video creator.' }
} catch {
    Write-Host "`nINSTALLATION FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Verified downloads are retained. Resolve the reported problem and run Install-Windows.bat again.'
    if ($TranscriptStarted) { Write-Host "Install log: $LogPath" }
    exit 1
} finally {
    if ($TranscriptStarted) { Stop-Transcript | Out-Null; Pop-Location }
    if ($null -ne $RuntimeLock) {
        try { if ($HasRuntimeLock) { $RuntimeLock.Unlock(0, 1) } }
        finally { $RuntimeLock.Dispose() }
    }
    if ($HasMutex) { $InstallMutex.ReleaseMutex() }
    if ($null -ne $InstallMutex) { $InstallMutex.Dispose() }
}
