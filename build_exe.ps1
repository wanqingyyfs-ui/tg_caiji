$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

# Build Chinese app name without non-ASCII PowerShell string literals.
# Name: Wanqing TG group/channel collector
$appName = -join ([char[]](0x4E07, 0x9752, 0x0054, 0x0047, 0x7FA4, 0x9891, 0x91C7, 0x96C6))

if (!(Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Virtual environment not found. Creating .venv..."
    python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller pillow

python .\tools\make_icon.py

if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }

pyinstaller `
  --noconfirm `
  --clean `
  --name $appName `
  --console `
  --icon "assets\app_icon.ico" `
  --add-data "collector\templates;collector\templates" `
  --add-data "collector\static;collector\static" `
  --add-data "assets;assets" `
  --hidden-import "uvicorn.logging" `
  --hidden-import "uvicorn.loops" `
  --hidden-import "uvicorn.loops.auto" `
  --hidden-import "uvicorn.protocols" `
  --hidden-import "uvicorn.protocols.http" `
  --hidden-import "uvicorn.protocols.http.auto" `
  --hidden-import "uvicorn.protocols.websockets" `
  --hidden-import "uvicorn.protocols.websockets.auto" `
  --hidden-import "uvicorn.lifespan" `
  --hidden-import "uvicorn.lifespan.on" `
  collector_exe_launcher.py

$dist = Join-Path $PSScriptRoot ("dist\" + $appName)
New-Item -ItemType Directory -Force -Path (Join-Path $dist "data\sessions") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dist "exports") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dist "logs") | Out-Null

if (Test-Path ".env") {
    Copy-Item ".env" (Join-Path $dist ".env") -Force
}

if (Test-Path "data\collector.db") {
    Copy-Item "data\collector.db" (Join-Path $dist "data\collector.db") -Force
}

Get-ChildItem "data\sessions" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $dist "data\sessions\$($_.Name)") -Force
}

Write-Host ""
Write-Host "Icon file: assets\app_icon.ico"
Write-Host "Build completed: $dist"
Write-Host "Run exe: $dist\$appName.exe"
Write-Host "Keep .env, data and exports in the same folder as the exe."
