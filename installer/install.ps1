# PDF Studio installer (per-user, no admin needed)
param([switch]$Silent)
$ErrorActionPreference = 'Stop'
$AppName = 'PDF Studio'
$src = Join-Path $PSScriptRoot 'PDFStudio'
$exeSrc = Join-Path $src 'PDFStudio.exe'
if (-not (Test-Path $exeSrc)) {
    Write-Host "File aplikasi tidak ditemukan: $exeSrc" -ForegroundColor Red
    if (-not $Silent) { Read-Host "Tekan Enter untuk keluar" }
    exit 1
}

$dest = Join-Path $env:LOCALAPPDATA 'Programs\PDFStudio'
Write-Host "Memasang $AppName ke $dest ..." -ForegroundColor Cyan
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path $src '*') $dest -Recurse -Force

$exe = Join-Path $dest 'PDFStudio.exe'

# uninstaller
$uninst = Join-Path $dest 'uninstall.ps1'
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') $uninst -Force -ErrorAction SilentlyContinue

# shortcuts
$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
foreach ($dir in @($desktop, (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))) {
    $lnkPath = Join-Path $dir "$AppName.lnk"
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $dest
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = 'PDF editor desktop'
    $lnk.Save()
}

# add/remove programs entry
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFStudio'
New-Item -Path $key -Force | Out-Null
Set-ItemProperty -Path $key -Name DisplayName -Value $AppName
Set-ItemProperty -Path $key -Name DisplayVersion -Value '1.2'
Set-ItemProperty -Path $key -Name Publisher -Value 'PDF Studio'
Set-ItemProperty -Path $key -Name InstallLocation -Value $dest
Set-ItemProperty -Path $key -Name DisplayIcon -Value "$exe,0"
Set-ItemProperty -Path $key -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name NoRepair -Value 1 -Type DWord
Set-ItemProperty -Path $key -Name EstimatedSize -Value ([int]((Get-ChildItem $dest -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)) -Type DWord
Set-ItemProperty -Path $key -Name UninstallString -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$uninst`""

# Per-user .pdf file association ("Open with PDF Studio" + Default Apps)
$progId = 'PDFStudio.Document'
$clsBase = "HKCU:\Software\Classes\$progId"
New-Item -Path "$clsBase\DefaultIcon" -Force | Out-Null
New-Item -Path "$clsBase\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path $clsBase -Name '(Default)' -Value 'PDF Document (PDF Studio)'
Set-ItemProperty -Path "$clsBase\DefaultIcon" -Name '(Default)' -Value "`"$exe`",0"
Set-ItemProperty -Path "$clsBase\shell\open\command" -Name '(Default)' -Value "`"$exe`" `"%1`""

New-Item -Path 'HKCU:\Software\Classes\.pdf\OpenWithProgids' -Force | Out-Null
Set-ItemProperty -Path 'HKCU:\Software\Classes\.pdf\OpenWithProgids' -Name $progId -Value '' -Type String

$capKey = 'HKCU:\Software\PDFStudio\Capabilities'
New-Item -Path "$capKey\FileAssociations" -Force | Out-Null
Set-ItemProperty -Path $capKey -Name ApplicationName -Value $AppName
Set-ItemProperty -Path $capKey -Name ApplicationDescription -Value 'PDF editor dan pembaca desktop untuk Windows'
Set-ItemProperty -Path "$capKey\FileAssociations" -Name '.pdf' -Value $progId
New-Item -Path 'HKCU:\Software\RegisteredApplications' -Force | Out-Null
Set-ItemProperty -Path 'HKCU:\Software\RegisteredApplications' -Name 'PDFStudio' -Value 'Software\PDFStudio\Capabilities'

Write-Host ""
Write-Host "$AppName berhasil dipasang." -ForegroundColor Green
Write-Host "  Aplikasi : $exe"
Write-Host "  Shortcut : Desktop & Start Menu"
Write-Host "  File .pdf: Terdaftar di Open with & Default Apps"
Write-Host "  Uninstall: Settings > Apps > $AppName"
Write-Host ""
if (-not $Silent) {
    $answer = Read-Host "Buka aplikasi sekarang? (Y/n)"
    if ($answer -eq '' -or $answer -match '^[yY]') {
        Start-Process $exe
    }
}
