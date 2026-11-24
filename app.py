"""PDF Studio - entry point.

Run from source:   python app.py [file.pdf]
Build executable:  powershell -ExecutionPolicy Bypass -File build.ps1
"""
from __future__ import annotations

import json
import os
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from ui import theme
from ui.main_window import MainWindow

IPC_SERVER_NAME = "PDFStudio_SingleInstance_v1"
IPC_MAX_BYTES = 65536
IPC_MAX_FILES = 20


def _send_to_running_instance(files: list[str], server_name: str = IPC_SERVER_NAME) -> bool:
    """Forward CLI file arguments to an already-running PDF Studio instance."""
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if not sock.waitForConnected(250):
        return False
    payload = json.dumps({"files": files[:IPC_MAX_FILES]}).encode("utf-8") + b"\n"
    sock.write(payload)
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.waitForReadyRead(500)
    sock.disconnectFromServer()
    return True


def _start_ipc_server(win: MainWindow, server_name: str = IPC_SERVER_NAME) -> QLocalServer | None:
    server = QLocalServer(win)
    server.setSocketOptions(QLocalServer.UserAccessOption)
    if not server.listen(server_name):
        QLocalServer.removeServer(server_name)
        if not server.listen(server_name):
            return None

    def _on_new_connection():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is None:
                continue
            raw = bytes(conn.read(IPC_MAX_BYTES))
            if not raw:
                conn.waitForReadyRead(500)
                raw += bytes(conn.read(IPC_MAX_BYTES))
            conn.write(b"OK")
            conn.flush()
            conn.waitForBytesWritten(200)
            conn.close()
            try:
                data = json.loads(raw.decode("utf-8", "replace").strip()) if raw else {}
            except Exception:
                data = {}
            files = data.get("files") if isinstance(data, dict) else []
            if isinstance(files, list):
                for p in files[:IPC_MAX_FILES]:
                    if (isinstance(p, str) and p.lower().endswith(".pdf")
                            and os.path.isfile(p)):
                        win.open_file(p)
            if win.isMinimized():
                win.showNormal()
            win.raise_()
            win.activateWindow()

    server.newConnection.connect(_on_new_connection)
    return server


def _crash_log(text: str) -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.dirname(sys.executable)
    folder = os.path.join(base, "PDFStudio")
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "crash.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n" + "=" * 70 + "\n")
        return path
    except Exception:
        return ""


def main() -> int:
    selftest = "--selftest" in sys.argv
    if selftest:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication(sys.argv)
    app.setApplicationName("PDF Studio")
    app.setApplicationDisplayName("PDF Studio")
    app.setOrganizationName("PDFStudio")
    app.setWindowIcon(QIcon(theme.app_pixmap(256)))

    if selftest:
        return run_selftest(app)

    cli_files = [os.path.abspath(a) for a in sys.argv[1:]
                 if not a.startswith("-") and a.lower().endswith(".pdf") and os.path.exists(a)]

    if not os.environ.get("PDFSTUDIO_MULTI_INSTANCE"):
        if _send_to_running_instance(cli_files):
            return 0

    win = MainWindow()
    if not os.environ.get("PDFSTUDIO_MULTI_INSTANCE"):
        win._ipc_server = _start_ipc_server(win)
    win.show()

    for arg in cli_files:
        win.open_file(arg)

    return app.exec()


def run_selftest(app) -> int:
    """Verify the frozen bundle end to end and write a log next to TEMP."""
    import tempfile

    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    tmp = tempfile.mkdtemp(prefix="pdfstudio_selftest_")
    log: list[str] = []
    code = 0
    try:
        import pymupdf as fitz  # noqa: F401
        from core.pdfdoc import PdfDoc, make_self_signed_pfx

        demo = os.path.join(base, "sample", "demo.pdf")
        if not os.path.exists(demo):
            raise FileNotFoundError(f"demo tidak ada: {demo}")

        doc = PdfDoc()
        doc.open(demo)
        log.append(f"open ok: {doc.page_count} pages")
        log.append(f"ocr engine: {PdfDoc.ocr_engine_name() or 'tidak tersedia'}")
        pix = doc.render(0, 1.4)
        log.append(f"render ok: {pix.width}x{pix.height}")
        doc.annot_text_markup(0, (55, 165, 400, 183), "highlight", (1, 0.85, 0.1))
        doc.add_text(0, (60, 620, 400, 650), "selftest", 14)
        doc.add_note(0, (430, 200), "selftest note")
        out = os.path.join(tmp, "out.pdf")
        doc.save_as(out)
        log.append(f"save ok: {os.path.getsize(out)} bytes")
        doc.close()

        pfx = os.path.join(tmp, "cert.pfx")
        make_self_signed_pfx(pfx, "PDF Studio Selftest", "test1234")
        doc = PdfDoc()
        doc.open(out)
        signed = os.path.join(tmp, "signed.pdf")
        doc.digital_sign(signed, 0, (330, 160, 470, 230), pfx, "test1234", "selftest")
        log.append(f"pades ok: {os.path.getsize(signed)} bytes")
        doc.close()

        from ui.main_window import MainWindow

        win = MainWindow()
        win.resize(1280, 820)
        win.show()
        win.open_file(demo)
        app.processEvents()
        shot = os.path.join(tmp, "shot.png")
        win.grab().save(shot, "PNG")
        log.append(f"ui ok: screenshot {os.path.getsize(shot)} bytes")
        win.dirty = False
        win.doc.close()
        win.close()
        log.append("SELFTEST LULUS")
    except Exception:
        code = 1
        log.append(traceback.format_exc())
        log.append("SELFTEST GAGAL")

    path = os.path.join(tempfile.gettempdir(), "pdfstudio_selftest.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(log))
    except Exception:
        pass
    print(path)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        detail = traceback.format_exc()
        path = _crash_log(detail)
        try:
            box = QMessageBox(QMessageBox.Critical, "PDF Studio berhenti",
                              "Terjadi kesalahan tak terduga.\n\n"
                              f"Log disimpan di:\n{path}\n\n{detail[-1200:]}")
            box.exec()
        except Exception:
            pass
        raise
