# PDF Studio uninstaller (per-user)
$ErrorActionPreference = 'SilentlyContinue'
$AppName = 'PDF Studio'
$dest = if ($PSScriptRoot) { $PSScriptRoot } else { Join-Path $env:LOCALAPPDATA 'Programs\PDFStudio' }
if (-not (Test-Path $dest)) { $dest = Join-Path $env:LOCALAPPDATA 'Programs\PDFStudio' }

Write-Host "Menghapus $AppName ..." -ForegroundColor Cyan

# stop running instance
Get-Process PDFStudio -ErrorAction SilentlyContinue | Stop-Process -Force

# shortcuts
$desktop = [Environment]::GetFolderPath('Desktop')
@(
    (Join-Path $desktop "$AppName.lnk"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk")
) | ForEach-Object { if (Test-Path $_) { Remove-Item $_ -Force } }

# registry
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFStudio' -Recurse -Force
Remove-Item 'HKCU:\Software\Classes\PDFStudio.Document' -Recurse -Force
Remove-ItemProperty -Path 'HKCU:\Software\Classes\.pdf\OpenWithProgids' -Name 'PDFStudio.Document' -Force
Remove-Item 'HKCU:\Software\PDFStudio' -Recurse -Force
Remove-ItemProperty -Path 'HKCU:\Software\RegisteredApplications' -Name 'PDFStudio' -Force

# app data (settings + crash logs)
Remove-Item (Join-Path $env:APPDATA 'PDFStudio') -Recurse -Force
Remove-Item (Join-Path $env:LOCALAPPDATA 'PDFStudio') -Recurse -Force

# delete the install folder after this script exits
$safeTarget = $dest.Replace("'", "''")
Start-Process -WindowStyle Hidden -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-Command', "Start-Sleep -Seconds 1; Remove-Item -LiteralPath '$safeTarget' -Recurse -Force"
)

Write-Host "$AppName telah dihapus." -ForegroundColor Green
Start-Sleep -Seconds 1
