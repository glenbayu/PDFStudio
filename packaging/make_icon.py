"""Generate the Windows .ico (multi-size, PNG-compressed) for PDF Studio."""
from __future__ import annotations

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication

from ui.theme import app_pixmap

SIZES = [16, 24, 32, 48, 64, 128, 256]


def png_bytes(size: int) -> bytes:
    pm = app_pixmap(size)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


def main(out: str) -> None:
    images = [(s, png_bytes(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    data = b""
    for size, blob in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        data += blob
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(header + entries + data)
    print(f"{out} ({os.path.getsize(out)/1024:.1f} KB)")


if __name__ == "__main__":
    app = QGuiApplication([])
    main(sys.argv[1] if len(sys.argv) > 1 else "assets/app.ico")
