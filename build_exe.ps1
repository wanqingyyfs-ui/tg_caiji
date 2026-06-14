$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$appName = "万青TG群频采集"

if (!(Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "未找到 .venv，正在创建虚拟环境..."
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

$dist = Join-Path $PSScriptRoot "dist\$appName"
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
Write-Host "图标文件：assets\app_icon.ico"
Write-Host "打包完成：$dist"
Write-Host "双击运行：$dist\$appName.exe"
Write-Host "注意：.env、data、exports 都放在 exe 同目录，方便以后修改和备份。"
