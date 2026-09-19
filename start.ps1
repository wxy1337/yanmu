$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LocalCudaLibraries = Join-Path $ProjectRoot ".tools\cuda12-libs"
$HfHome = Join-Path $ProjectRoot ".tools\hf-home"
$RequiredCudaDlls = @("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Dependencies are not installed. Run .\setup.ps1 first."
}
try {
    & $VenvPython -c "import sys" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment Python check failed."
    }
} catch {
    throw "Existing .venv cannot run. Run .\setup.ps1 to rebuild it with project Python."
}

$missingCudaDlls = @(
    foreach ($dll in $RequiredCudaDlls) {
        if (-not (Test-Path (Join-Path $LocalCudaLibraries $dll))) {
            $dll
        }
    }
)

if ($missingCudaDlls.Count -eq 0) {
    $env:PATH = $LocalCudaLibraries + ";" + $env:PATH
    Write-Host "Using project-local CUDA 12 and cuDNN 9 libraries." -ForegroundColor Green
} else {
    Write-Host ("Project-local CUDA libraries are incomplete: " + ($missingCudaDlls -join ", ")) -ForegroundColor Yellow
    Write-Host "Run .\setup.ps1 to download CUDA/cuDNN, or YanMu will fall back to CPU where possible." -ForegroundColor Yellow
}

$env:HF_HOME = $HfHome
$env:HF_HUB_CACHE = Join-Path $HfHome "hub"
$env:HF_HUB_DISABLE_XET = "1"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

& $VenvPython (Join-Path $ProjectRoot "run.py")
if ($LASTEXITCODE -ne 0) {
    throw "YanMu failed to start. Check the error above."
}
