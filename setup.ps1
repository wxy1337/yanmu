param(
    [switch]$SkipCuda
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$RuntimeScript = Join-Path $ProjectRoot "scripts\install-runtime.ps1"
$PythonVersion = "3.12.10"
$ProjectPythonDir = Join-Path $ProjectRoot ".tools\python-$PythonVersion"
$ProjectPython = Join-Path $ProjectPythonDir "python.exe"
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$CudaLibrariesDir = Join-Path $ProjectRoot ".tools\cuda12-libs"
$HfHome = Join-Path $ProjectRoot ".tools\hf-home"
$BundledFfmpeg = Join-Path $VenvDir "Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"

function Convert-ToEnvPath {
    param([string]$Path)
    return $Path.Replace("\", "/")
}

function Set-EnvValue {
    param(
        [string]$File,
        [string]$Key,
        [string]$Value
    )

    $line = "$Key=$Value"
    if (-not (Test-Path $File)) {
        Set-Content -Path $File -Value $line -Encoding UTF8
        return
    }

    $content = Get-Content -Path $File
    $updated = $false
    $newContent = foreach ($existing in $content) {
        if ($existing -match "^\s*$([regex]::Escape($Key))=") {
            $updated = $true
            $line
        } else {
            $existing
        }
    }
    if (-not $updated) {
        $newContent += $line
    }
    Set-Content -Path $File -Value $newContent -Encoding UTF8
}

& $RuntimeScript -SkipCuda:$SkipCuda

$needsVenv = $true
if (Test-Path $VenvPython) {
    try {
        $basePrefix = (& $VenvPython -c "import sys; print(sys.base_prefix)") | Select-Object -First 1
    } catch {
        $basePrefix = ""
    }
    $expectedPrefix = (Resolve-Path $ProjectPythonDir).Path
    if ($basePrefix -eq $expectedPrefix) {
        $needsVenv = $false
        Write-Host "Project virtual environment already uses bundled Python." -ForegroundColor Green
    } else {
        $backup = Join-Path $ProjectRoot (".venv-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        Write-Host "Existing .venv does not use bundled Python; moving it to $backup" -ForegroundColor Yellow
        Move-Item -LiteralPath $VenvDir -Destination $backup
    }
}

if ($needsVenv) {
    Write-Host "Creating virtual environment with project Python $PythonVersion" -ForegroundColor Cyan
    & $ProjectPython -m venv $VenvDir
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")

$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $ProjectRoot ".env.example") $envFile
    Write-Host "Created .env." -ForegroundColor Yellow
}

Set-EnvValue $envFile "WHISPER_MODEL" "medium"
Set-EnvValue $envFile "WHISPER_DEVICE" "cuda"
Set-EnvValue $envFile "WHISPER_COMPUTE_TYPE" "float16"
Set-EnvValue $envFile "ACCELERATION_MODE" "cuda"
Set-EnvValue $envFile "GPU_VIDEO_ENCODER" "auto"
Set-EnvValue $envFile "CUDA_DLL_DIRECTORY" (Convert-ToEnvPath $CudaLibrariesDir)
Set-EnvValue $envFile "FFMPEG_BINARY" (Convert-ToEnvPath $BundledFfmpeg)
Set-EnvValue $envFile "TRANSLATION_PROVIDER" "openai_compatible"
Set-EnvValue $envFile "TRANSLATION_BASE_URL" "https://api.openai.com/v1"
Set-EnvValue $envFile "TRANSLATION_API_KEY" ""
Set-EnvValue $envFile "TRANSLATION_MODEL" ""
Set-EnvValue $envFile "TRANSLATION_TIMEOUT_SECONDS" "180"

if (-not (Test-Path $HfHome)) {
    New-Item -ItemType Directory -Force -Path $HfHome | Out-Null
}

Write-Host "Setup complete. Run .\start.ps1 to start YanMu." -ForegroundColor Green
