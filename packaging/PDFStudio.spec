# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PDF Studio (Windows, windowed app)."""

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

hidden = (
    ["pymupdf", "fitz", "pyhanko", "asn1crypto", "cryptography",
     "core.ocr", "core.signatures", "core.exporter", "ui.workers",
     # cryptography >= 50 keeps the Rust bindings in a single extension module
     # that the upstream PyInstaller hook does not collect yet.
     "cryptography.hazmat.bindings._rust"]
    + collect_submodules("pyhanko")
    + collect_submodules("pyhanko_certvalidator")
)

excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtBluetooth", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest",
    "PySide6.QtSql", "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtPositioning",
    "PySide6.QtNfc", "PySide6.QtSvgWidgets", "PySide6.QtOpenGL",
    "numpy", "onnxruntime", "pymupdf4llm", "pymupdf_layout", "pymupdf_layout",
    "tkinter", "unittest", "pydoc_data", "PIL", "matplotlib", "IPython",
]

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "assets", "app.ico"), "assets"),
        (os.path.join(ROOT, "sample", "demo.pdf"), "sample"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "app.ico"),
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PDFStudio",
)
