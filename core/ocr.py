"""Windows.Media.Ocr bridge.

Tesseract is optional. Windows 10/11 ships an OCR engine that works offline,
so PDF Studio can still give a scanned page a text layer even on machines
without Tesseract. This module drives that engine through Windows PowerShell
(WinRT is only reachable from .NET Framework there).

The public surface is tiny:

    available()  -> bool
    recognize(png_path) -> {"width": int, "height": int, "lines": [...]}
    engine_name() -> str

Every call is best-effort: any failure simply returns False / raises a
``RuntimeError`` that the UI reports as "OCR tidak tersedia".
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

_WINOCR_PS = r"""
$ErrorActionPreference = 'Stop'
$Path = $env:PDFSTUDIO_OCR_PATH
$Out = $env:PDFSTUDIO_OCR_OUT
$Probe = ($env:PDFSTUDIO_OCR_PROBE -eq '1')
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($Probe) {
    if ($null -eq $engine) { $obj = @{ ok = $false } }
    else { $obj = @{ ok = $true; lang = $engine.RecognizerLanguage.LanguageTag } }
    [IO.File]::WriteAllText($Out, ($obj | ConvertTo-Json -Compress), [Text.Encoding]::UTF8)
    exit 0
}
if ($null -eq $engine) { throw 'Windows OCR engine tidak tersedia.' }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = New-Object System.Collections.ArrayList
foreach ($line in $result.Lines) {
    $words = New-Object System.Collections.ArrayList
    foreach ($w in $line.Words) {
        $r = $w.BoundingRect
        [void]$words.Add(@{
            t = [string]$w.Text
            x = [double]$r.X
            y = [double]$r.Y
            w = [double]$r.Width
            h = [double]$r.Height
        })
    }
    [void]$lines.Add(@{ text = [string]$line.Text; words = $words.ToArray() })
}
$obj = @{
    ok = $true
    lang = $engine.RecognizerLanguage.LanguageTag
    width = [int]$decoder.PixelWidth
    height = [int]$decoder.PixelHeight
    lines = $lines.ToArray()
}
[IO.File]::WriteAllText($Out, ($obj | ConvertTo-Json -Depth 8 -Compress), [Text.Encoding]::UTF8)
$stream.Dispose()
"""

_ENCODED_SCRIPT = base64.b64encode(_WINOCR_PS.encode("utf-16-le")).decode("ascii")
_probe: dict | None = None


def _powershell() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    exe = os.path.join(root, "System32", "WindowsPowerShell", "v1.0",
                       "powershell.exe")
    if os.path.exists(exe):
        return exe
    return shutil.which("powershell") or ""


def _run(*, image_path: str = "", probe: bool = False, timeout: int = 180) -> dict:
    ps = _powershell()
    if not ps:
        raise RuntimeError("Windows PowerShell tidak ditemukan.")
    if not probe and (not image_path or not os.path.isfile(image_path)):
        raise FileNotFoundError("File gambar OCR tidak ditemukan.")
    fd, out = tempfile.mkstemp(prefix="winocr_", suffix=".json")
    os.close(fd)
    flags = 0
    if sys.platform == "win32":
        flags = 0x08000000  # CREATE_NO_WINDOW
    env = os.environ.copy()
    env["PDFSTUDIO_OCR_PATH"] = os.path.abspath(image_path) if image_path else ""
    env["PDFSTUDIO_OCR_OUT"] = out
    env["PDFSTUDIO_OCR_PROBE"] = "1" if probe else "0"
    try:
        proc = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-EncodedCommand", _ENCODED_SCRIPT],
            capture_output=True, timeout=timeout, creationflags=flags,
            stdin=subprocess.DEVNULL, env=env,
        )
        try:
            with open(out, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception:
            msg = (proc.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(msg or "Windows OCR tidak merespons.")
        if not data.get("ok"):
            raise RuntimeError("Windows OCR engine tidak tersedia.")
        return data
    finally:
        try:
            os.unlink(out)
        except Exception:
            pass


def available() -> bool:
    """True when Windows' built-in OCR can be used on this machine."""
    global _probe
    if _probe is None:
        if not sys.platform == "win32":
            _probe = {"ok": False}
        else:
            try:
                _probe = _run(probe=True, timeout=30)
            except Exception:
                _probe = {"ok": False}
    return bool(_probe.get("ok"))


def language() -> str:
    if _probe and _probe.get("ok"):
        return str(_probe.get("lang") or "")
    return ""


def engine_name() -> str:
    if available():
        lang = language()
        return f"OCR Windows ({lang})" if lang else "OCR Windows"
    return ""


def recognize(image_path: str) -> dict:
    """OCR a PNG/JPG file, returning words with pixel bounding boxes."""
    return _run(image_path=image_path)
