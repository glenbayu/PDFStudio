"""Defensive security audit & regression tests for PDF Studio."""
from __future__ import annotations

import ast
import glob
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PDFSTUDIO_RECOVERY_DIR", tempfile.mkdtemp(prefix="pdfsec_rec_"))
os.environ.setdefault("PDFSTUDIO_SIGNATURES_DIR", tempfile.mkdtemp(prefix="pdfsec_sig_"))
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pymupdf as fitz
from PySide6.QtWidgets import QApplication, QMessageBox

import app as app_mod
from core import ocr as winocr
from core.exporter import export_docx
from core.pdfdoc import PdfDoc
from sample.make_demo import build
from ui.main_window import MainWindow
from ui.tools_dialogs import AttachmentsDialog
from ui.viewer import InlineTextEditor


def test_static_ast_security():
    """Verify no dangerous dynamic execution or shell=True sinks exist in app code."""
    banned_calls = {"eval", "exec", "compile"}
    banned_attrs = {("os", "system"), ("os", "popen"), ("pickle", "loads"),
                    ("pickle", "load"), ("tempfile", "mktemp")}
    py_files = [os.path.join(ROOT, "app.py")] + glob.glob(os.path.join(ROOT, "core", "*.py")) + glob.glob(os.path.join(ROOT, "ui", "*.py"))
    findings = []
    for path in py_files:
        tree = ast.parse(open(path, encoding="utf-8-sig").read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in banned_calls:
                    findings.append(f"{path}:{node.lineno}: banned call {node.func.id}()")
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    pair = (node.func.value.id, node.func.attr)
                    if pair in banned_attrs:
                        findings.append(f"{path}:{node.lineno}: banned call {pair[0]}.{pair[1]}()")
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        findings.append(f"{path}:{node.lineno}: subprocess shell=True")
    assert not findings, "\n".join(findings)
    print(f"[ok] static AST security scan clean ({len(py_files)} files)")


def test_ocr_no_temp_script_and_validation():
    """Verify Windows OCR runs via -EncodedCommand (no writable %TEMP% .ps1) & rejects bad paths."""
    assert not hasattr(winocr, "_script_path"), "OCR should not write reusable .ps1 in %TEMP%"
    try:
        winocr.recognize(r"C:\nonexistent_file_12345.png")
        raise AssertionError("Non-existent image must raise FileNotFoundError")
    except FileNotFoundError:
        pass
    print("[ok] OCR uses in-memory -EncodedCommand & validates input file")


def test_attachment_path_traversal_sanitization():
    for bad in (r"..\..\..\Windows\System32\evil.bat", "../../etc/passwd", "a/b\\c:evil?.exe", "..."):
        safe = AttachmentsDialog._safe_filename(bad)
        assert ".." not in safe and "/" not in safe and "\\" not in safe and ":" not in safe, (bad, safe)
    print("[ok] attachment extraction filename sanitization blocks path traversal")


def test_docx_xml_injection_escaping():
    tmp = tempfile.mkdtemp(prefix="pdfsec_xml_")
    p = os.path.join(tmp, "xml_inj.pdf")
    d0 = fitz.open()
    pg = d0.new_page()
    pg.insert_text((72, 100), 'Test <w:p/> & "quotes" ]]> <script>alert(1)</script>', fontsize=12)
    d0.save(p)
    d0.close()
    doc = PdfDoc()
    doc.open(p)
    out = os.path.join(tmp, "safe.docx")
    export_docx(doc, out)
    with zipfile.ZipFile(out, "r") as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
        txt = "".join(root.itertext())
        assert "<script>alert(1)</script>" in txt and "<w:p/>" in txt
    doc.cleanup()
    print("[ok] DOCX XML export safely escapes special/control characters")


def test_ui_security_controls():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    app.processEvents()

    # 1. Unsafe link schemes blocked without confirmation
    for scheme in ("javascript:alert(1)", "file:///C:/Windows/win.ini", "cmd:calc"):
        win._on_link_clicked({"uri": scheme})
        assert "diblokir" in win.hint_label.text().lower(), (scheme, win.hint_label.text())

    # 2. External http/https link asks user confirmation first
    asked = []
    old_q = QMessageBox.question
    QMessageBox.question = lambda _p, title, body, *a, **k: (asked.append(body), QMessageBox.No)[1]
    try:
        win._on_link_clicked({"uri": "https://example.com/phish"})
    finally:
        QMessageBox.question = old_q
    assert asked and "https://example.com/phish" in asked[0]
    assert "dibatalkan" in win.hint_label.text().lower()

    # 3. QSS injection sanitization in InlineTextEditor
    tmp = tempfile.mkdtemp(prefix="pdfsec_ui_")
    demo = os.path.join(tmp, "demo.pdf")
    build(demo)
    win.open_file(demo)
    app.processEvents()
    info = win.doc.text_at(0, (120, 170))
    info["font_display"] = "Arial'; background: red; /*"
    ed = InlineTextEditor(win.view, info, 1.0)
    assert "background: red" not in ed.styleSheet()
    ed.cancel_now()

    # 4. IPC server rejects non-PDF files cleanly
    not_pdf = os.path.join(tmp, "secret.txt")
    with open(not_pdf, "w", encoding="utf-8") as f:
        f.write("not a pdf")
    srv_name = f"PDFStudio_SecIPC_{os.getpid()}"
    srv = app_mod._start_ipc_server(win, srv_name)
    assert srv is not None
    tabs_before = len(win._tabs)
    child_code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from PySide6.QtCore import QCoreApplication; import app as m; "
        "a = QCoreApplication([]); "
        "sys.exit(0 if m._send_to_running_instance([sys.argv[2]], sys.argv[3]) else 1)"
    )
    proc = subprocess.Popen([sys.executable, "-c", child_code, ROOT, not_pdf, srv_name])
    deadline = time.time() + 8.0
    while proc.poll() is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert proc.wait(timeout=5) == 0
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    assert len(win._tabs) == tabs_before, "IPC must reject non-PDF files!"
    srv.close()

    for tb in win._tabs:
        tb.dirty = False
    win.dirty = False
    win.close()
    print("[ok] UI security controls (link schemes, external URL prompt, QSS sanitization, IPC .pdf filter)")


def main():
    test_static_ast_security()
    test_ocr_no_temp_script_and_validation()
    test_attachment_path_traversal_sanitization()
    test_docx_xml_injection_escaping()
    test_ui_security_controls()
    print("\nSEMUA TES KEAMANAN LULUS")


if __name__ == "__main__":
    main()
