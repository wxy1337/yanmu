param(
    [switch]$SkipCuda
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ToolsDir = Join-Path $ProjectRoot ".tools"
$DownloadsDir = Join-Path $ToolsDir "downloads"
$CudaLibrariesDir = Join-Path $ToolsDir "cuda12-libs"

$PythonVersion = "3.12.10"
$PythonDir = Join-Path $ToolsDir "python-$PythonVersion"
$PythonExe = Join-Path $PythonDir "python.exe"
$PythonInstallerUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"

$CudaPackages = @(
    @{
        Name = "CUDA Runtime 12.6"
        Url = "https://developer.download.nvidia.com/compute/cuda/redist/cuda_cudart/windows-x86_64/cuda_cudart-windows-x86_64-12.6.77-archive.zip"
        Required = @("cudart64_12.dll")
    },
    @{
        Name = "cuBLAS 12.6"
        Url = "https://developer.download.nvidia.com/compute/cuda/redist/libcublas/windows-x86_64/libcublas-windows-x86_64-12.6.4.1-archive.zip"
        Required = @("cublas64_12.dll", "cublasLt64_12.dll")
    },
    @{
        Name = "cuDNN 9 for CUDA 12"
        Url = "https://developer.download.nvidia.com/compute/cudnn/redist/cudnn/windows-x86_64/cudnn-windows-x86_64-9.10.2.21_cuda12-archive.zip"
        Required = @("cudnn64_9.dll")
    }
)

function New-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Save-Download {
    param(
        [string]$Url,
        [string]$Destination
    )

    if ((Test-Path $Destination) -and ((Get-Item $Destination).Length -gt 0)) {
        Write-Host "Using cached download: $Destination" -ForegroundColor DarkGray
        return
    }

    Write-Host "Downloading $Url" -ForegroundColor Cyan
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

function Install-ProjectPython {
    New-Directory $ToolsDir
    New-Directory $DownloadsDir

    if (Test-Path $PythonExe) {
        Write-Host "Project Python already installed: $PythonExe" -ForegroundColor Green
    } else {
        $installer = Join-Path $DownloadsDir "python-$PythonVersion-amd64.exe"
        Save-Download $PythonInstallerUrl $installer

        Write-Host "Installing Python $PythonVersion into $PythonDir" -ForegroundColor Cyan
        $arguments = @(
            "/quiet",
            "InstallAllUsers=0",
            "TargetDir=$PythonDir",
            "Include_launcher=0",
            "PrependPath=0",
            "Include_test=0",
            "Include_doc=0",
            "Shortcuts=0",
            "Include_pip=1"
        )
        $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Python installer failed with exit code $($process.ExitCode)."
        }
    }

    & $PythonExe -c "import ssl, sys; print(f'Python {sys.version.split()[0]} OK'); print(ssl.OPENSSL_VERSION)"
    & $PythonExe -m pip --version
}

function Install-CudaPackage {
    param([hashtable]$Package)

    $missing = @(
        foreach ($dll in $Package.Required) {
            if (-not (Test-Path (Join-Path $CudaLibrariesDir $dll))) {
                $dll
            }
        }
    )
    if ($missing.Count -eq 0) {
        Write-Host "$($Package.Name) already present." -ForegroundColor Green
        return
    }

    $fileName = Split-Path $Package.Url -Leaf
    $archive = Join-Path $DownloadsDir $fileName
    $extractDir = Join-Path $DownloadsDir ([IO.Path]::GetFileNameWithoutExtension($fileName))

    Save-Download $Package.Url $archive

    Write-Host "Extracting $($Package.Name)" -ForegroundColor Cyan
    New-Directory $extractDir
    tar -xf $archive -C $extractDir

    $dlls = Get-ChildItem -Path $extractDir -Recurse -Filter "*.dll" -File
    if (-not $dlls) {
        throw "No DLL files were found after extracting $fileName."
    }
    foreach ($dll in $dlls) {
        Copy-Item -LiteralPath $dll.FullName -Destination (Join-Path $CudaLibrariesDir $dll.Name) -Force
    }

    foreach ($dll in $Package.Required) {
        if (-not (Test-Path (Join-Path $CudaLibrariesDir $dll))) {
            throw "$($Package.Name) did not provide required DLL: $dll"
        }
    }
}

function Install-ProjectCudaLibraries {
    New-Directory $ToolsDir
    New-Directory $DownloadsDir
    New-Directory $CudaLibrariesDir

    foreach ($package in $CudaPackages) {
        Install-CudaPackage $package
    }

    $requiredDlls = @("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
    foreach ($dll in $requiredDlls) {
        $path = Join-Path $CudaLibrariesDir $dll
        if (-not (Test-Path $path)) {
            throw "Missing required CUDA DLL: $dll"
        }
    }
    Write-Host "Project CUDA libraries are ready: $CudaLibrariesDir" -ForegroundColor Green
}

Install-ProjectPython
if ($SkipCuda) {
    Write-Host "Skipped CUDA/cuDNN download." -ForegroundColor Yellow
} else {
    Install-ProjectCudaLibraries
}
