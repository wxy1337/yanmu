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
    $content = Get-Content -LiteralPath $File -Encoding UTF8
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
    [IO.File]::WriteAllLines($File, [string[]]$newContent, [Text.UTF8Encoding]::new($false))
}

& $RuntimeScript -SkipCuda:$SkipCuda

if (-not (Test-Path -LiteralPath $ProjectPython)) {
    throw "Bundled Python is missing after runtime installation: $ProjectPython"
}
& $ProjectPython -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Bundled Python is not a usable 64-bit Python 3.10+ installation."
}

$needsVenv = $true
if (Test-Path -LiteralPath $VenvDir) {
    $basePrefix = ""
    if (Test-Path -LiteralPath $VenvPython) {
        try {
            $basePrefix = (& $VenvPython -c "import sys; print(sys.base_prefix)" 2>$null) | Select-Object -First 1
            if ($LASTEXITCODE -ne 0) {
                $basePrefix = ""
            }
        } catch {
            $basePrefix = ""
        }
    }

    $expectedPrefix = (Resolve-Path -LiteralPath $ProjectPythonDir).Path
    if ($basePrefix -and ([IO.Path]::GetFullPath($basePrefix).TrimEnd('\') -ieq $expectedPrefix.TrimEnd('\'))) {
        $needsVenv = $false
        Write-Host "Project virtual environment already uses bundled Python." -ForegroundColor Green
    } else {
        $resolvedRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
        $resolvedVenv = [IO.Path]::GetFullPath($VenvDir).TrimEnd('\')
        if ($resolvedVenv -ine "$resolvedRoot\.venv") {
            throw "Refusing to move a virtual environment outside the project."
        }
        $backup = Join-Path $ProjectRoot (".venv-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
        $resolvedBackup = [IO.Path]::GetFullPath($backup)
        if (-not $resolvedBackup.StartsWith("$resolvedRoot\", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to move .venv outside the project."
        }
        if (Test-Path -LiteralPath $backup) {
            throw "Backup path already exists: $backup"
        }
        Write-Host "Existing .venv is incompatible; moving it to $backup" -ForegroundColor Yellow
        Move-Item -LiteralPath $VenvDir -Destination $backup
    }
}

if ($needsVenv) {
    Write-Host "Creating virtual environment with project Python $PythonVersion" -ForegroundColor Cyan
    & $ProjectPython -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create .venv. Check the Python installation and free disk space."
    }
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Could not upgrade pip. Check the network connection."
}
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed. Check the error above and retry."
}
& $VenvPython -c "import fastapi, pydantic_core, pydantic_settings, faster_whisper, opencc, httpx, imageio_ffmpeg"
if ($LASTEXITCODE -ne 0) {
    throw "Dependency import check failed. Back up and rebuild .venv; it may mix Python versions."
}

$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item (Join-Path $ProjectRoot ".env.example") $envFile
    Write-Host "Created .env." -ForegroundColor Yellow

    $ffmpeg = (& $VenvPython -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())") | Select-Object -First 1
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ffmpeg)) {
        throw "The bundled FFmpeg executable could not be found."
    }

    Set-EnvValue $envFile "WHISPER_MODEL" "medium"
    Set-EnvValue $envFile "WHISPER_DEVICE" "auto"
    Set-EnvValue $envFile "WHISPER_COMPUTE_TYPE" "auto"
    Set-EnvValue $envFile "ACCELERATION_MODE" "auto"
    Set-EnvValue $envFile "GPU_VIDEO_ENCODER" "auto"
    if (-not $SkipCuda) {
        Set-EnvValue $envFile "CUDA_DLL_DIRECTORY" (Convert-ToEnvPath $CudaLibrariesDir)
    }
    Set-EnvValue $envFile "FFMPEG_BINARY" (Convert-ToEnvPath $ffmpeg)
    Set-EnvValue $envFile "TRANSLATION_TIMEOUT_SECONDS" "180"
} else {
    Write-Host "Keeping existing .env settings unchanged." -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $HfHome)) {
    New-Item -ItemType Directory -Force -Path $HfHome | Out-Null
}

Write-Host "Setup complete. Run .\start.ps1 to start YanMu." -ForegroundColor Green
