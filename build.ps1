# PDF Studio - satu perintah untuk build + installer
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "== 1/5 Menyiapkan virtual environment ==" -ForegroundColor Cyan
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    $py = 'py'
    try { & py -3.12 --version | Out-Null } catch { $py = 'python' }
    & $py -3.12 -m venv .venv
}

Write-Host "== 2/5 Memasang dependensi ==" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "== 3/5 Membuat ikon ==" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe packaging\make_icon.py assets\app.ico

Write-Host "== 4/5 Build executable (PyInstaller) ==" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe sample\make_demo.py sample\demo.pdf
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\PDFStudio.spec
if (-not (Test-Path 'dist\PDFStudio\PDFStudio.exe')) { throw 'Build gagal: exe tidak ditemukan.' }

Write-Host "     merampingkan bundle Qt..." -ForegroundColor DarkGray
& .\.venv\Scripts\python.exe packaging\trim.py dist\PDFStudio

Write-Host "     self-test executable..." -ForegroundColor DarkGray
$proc = Start-Process -FilePath 'dist\PDFStudio\PDFStudio.exe' -ArgumentList '--selftest' -PassThru -Wait
$log = Join-Path $env:TEMP 'pdfstudio_selftest.txt'
if ($proc.ExitCode -ne 0) {
    if (Test-Path $log) { Get-Content $log }
    throw 'Self-test executable gagal.'
}
Write-Host "     self-test lulus." -ForegroundColor Green

Write-Host "== 5/5 Membuat paket installer ==" -ForegroundColor Cyan
$iscc = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe'
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}

$setupExe = 'dist\PDFStudio-Setup-1.2.exe'
if ($iscc -and (Test-Path 'installer\PDFStudio.iss')) {
    Write-Host "     mengompilasi Windows Setup (.exe) via Inno Setup..." -ForegroundColor DarkGray
    if (Test-Path $setupExe) { Remove-Item $setupExe -Force }
    & $iscc /Q 'installer\PDFStudio.iss'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $setupExe)) {
        throw 'Kompilasi Inno Setup gagal.'
    }
}

$stage = 'dist\setup-stage'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item 'dist\PDFStudio' (Join-Path $stage 'PDFStudio') -Recurse
Copy-Item 'installer\install.ps1' $stage
Copy-Item 'installer\uninstall.ps1' $stage
Copy-Item 'installer\Install PDF Studio.cmd' $stage
Copy-Item 'README.md' $stage
Copy-Item 'LICENSE' $stage
Copy-Item 'THIRD-PARTY.md' $stage
$zip = 'dist\PDFStudio-Setup-1.2.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force
if (Test-Path 'build') { Remove-Item 'build' -Recurse -Force }

$zipSize = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "SELESAI" -ForegroundColor Green
Write-Host "  Portable     : dist\PDFStudio\PDFStudio.exe"
if (Test-Path $setupExe) {
    $exeSize = [math]::Round((Get-Item $setupExe).Length / 1MB, 1)
    Write-Host "  Setup Wizard : $setupExe ($exeSize MB)"
}
Write-Host "  Zip Portable : $zip ($zipSize MB)"
exit 0