$ErrorActionPreference = "Stop"

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    throw "Dependencies are not installed. Run .\setup.ps1 first."
}

$LocalCudaLibraries = Join-Path $PSScriptRoot ".tools\cuda12-libs"
if ((Test-Path (Join-Path $LocalCudaLibraries "cublas64_12.dll")) -and
    (Test-Path (Join-Path $LocalCudaLibraries "cudnn64_9.dll"))) {
    $env:PATH = $LocalCudaLibraries + ";" + $env:PATH
    Write-Host "Using project-local CUDA 12 and cuDNN 9 libraries." -ForegroundColor Green
}

& .\.venv\Scripts\python.exe run.py
