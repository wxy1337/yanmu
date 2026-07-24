$ErrorActionPreference = "Stop"

$PythonCommand = Get-Command py -ErrorAction SilentlyContinue
if (-not $PythonCommand) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $PythonCommand) {
    throw "Python was not found. Install Python 3.10 or newer first."
}

if ($PythonCommand.Name -eq "py.exe") {
    & py -3 -m venv .venv
} else {
    & $PythonCommand.Source -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env. Configure a translation service when processing foreign videos." -ForegroundColor Yellow
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "System FFmpeg was not found; the bundled project runtime will be used." -ForegroundColor Yellow
}

Write-Host "Setup complete. Run .\start.ps1 to start YanMu." -ForegroundColor Green
