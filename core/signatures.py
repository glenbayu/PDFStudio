"""Persistent user signature library stored in LOCALAPPDATA."""
from __future__ import annotations

import os
import re
import tempfile
import time


def signatures_dir() -> str:
    override = os.environ.get("PDFSTUDIO_SIGNATURES_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        return override
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if not base:
        base = tempfile.gettempdir()
    path = os.path.join(base, "PDFStudio", "signatures")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = os.path.join(tempfile.gettempdir(), "PDFStudio-signatures")
        os.makedirs(path, exist_ok=True)
    return path


def list_signatures() -> list[dict]:
    """Return saved signatures newest first: [{'name', 'path', 'mtime'}]."""
    folder = signatures_dir()
    items = []
    try:
        names = os.listdir(folder)
    except Exception:
        return items
    for name in names:
        if not name.lower().endswith(".png"):
            continue
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            mtime = 0.0
        label = os.path.splitext(name)[0].replace("_", " ").strip() or "Tanda Tangan"
        items.append({"name": label, "path": full, "mtime": mtime})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def save_signature_image(qimage, name: str = "") -> str:
    """Save a QImage as PNG into the persistent signature library."""
    folder = signatures_dir()
    clean = re.sub(r"[^a-zA-Z0-9_\- ]+", "", (name or "").strip()).strip()
    if not clean:
        clean = f"ttd_{time.strftime('%Y%m%d_%H%M%S')}"
    clean = clean.replace(" ", "_")
    path = os.path.join(folder, f"{clean}.png")
    idx = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{clean}_{idx}.png")
        idx += 1
    if not qimage.save(path, "PNG"):
        raise OSError(f"Gagal menyimpan tanda tangan ke {path}")
    return path


def delete_signature(path: str) -> bool:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
            return True
    except OSError:
        pass
    return False
