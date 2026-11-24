# Verifies the installer end-to-end (install -> shortcuts -> launch -> uninstall).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stage = Join-Path $env:TEMP 'pdfstudio_install_test'
$dest = Join-Path $env:LOCALAPPDATA 'Programs\PDFStudio'
$desktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PDF Studio.lnk'
$startLnk = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\PDF Studio.lnk'
$regKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFStudio'

Write-Host "== stage ==" -ForegroundColor Cyan
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item (Join-Path $root 'dist\PDFStudio') (Join-Path $stage 'PDFStudio') -Recurse
Copy-Item (Join-Path $root 'installer\install.ps1') $stage
Copy-Item (Join-Path $root 'installer\uninstall.ps1') $stage

Write-Host "== install ==" -ForegroundColor Cyan
& (Join-Path $stage 'install.ps1') -Silent
if (-not (Test-Path (Join-Path $dest 'PDFStudio.exe'))) { throw 'exe tidak terpasang' }
if (-not (Test-Path $desktopLnk)) { throw 'shortcut desktop tidak ada' }
if (-not (Test-Path $startLnk)) { throw 'shortcut start menu tidak ada' }
if (-not (Test-Path $regKey)) { throw 'registry uninstall tidak ada' }
Write-Host "   files + shortcuts + registry OK" -ForegroundColor Green

Write-Host "== launch installed exe selftest ==" -ForegroundColor Cyan
$p = Start-Process -FilePath (Join-Path $dest 'PDFStudio.exe') -ArgumentList '--selftest' -PassThru -Wait
if ($p.ExitCode -ne 0) { throw "selftest exit $($p.ExitCode)" }
Write-Host "   exit 0 OK" -ForegroundColor Green

Write-Host "== uninstall ==" -ForegroundColor Cyan
& (Join-Path $dest 'uninstall.ps1')
Start-Sleep -Seconds 4
if (Test-Path $dest) { throw 'folder instalasi masih ada' }
if (Test-Path $desktopLnk) { throw 'shortcut desktop masih ada' }
if (Test-Path $startLnk) { throw 'shortcut start menu masih ada' }
if (Test-Path $regKey) { throw 'registry masih ada' }
Remove-Item $stage -Recurse -Force
Write-Host "   bersih, tidak ada sisa" -ForegroundColor Green
Write-Host "INSTALLER TEST LULUS" -ForegroundColor Green
