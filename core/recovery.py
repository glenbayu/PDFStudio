"""Autosave snapshots and crash recovery helpers (Qt free)."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time


def recovery_dir() -> str:
    override = os.environ.get("PDFSTUDIO_RECOVERY_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        return override
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if not base:
        base = tempfile.gettempdir()
    path = os.path.join(base, "PDFStudio", "recovery")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        path = os.path.join(tempfile.gettempdir(), "PDFStudio-recovery")
        os.makedirs(path, exist_ok=True)
    return path


def snapshot_key(original: str | None) -> str:
    seed = (original or "untitled").lower().encode("utf-8", "ignore")
    return hashlib.md5(seed).hexdigest()[:16]


def snapshot_paths(original: str | None) -> tuple[str, str]:
    key = snapshot_key(original)
    base = recovery_dir()
    return os.path.join(base, key + ".pdf"), os.path.join(base, key + ".json")


def write_snapshot(doc, *, page: int = 0, zoom: float = 1.0) -> dict | None:
    """Write a recovery PDF for *doc*; returns the metadata on success."""
    pdf_path, meta_path = snapshot_paths(doc.path)
    try:
        doc.snapshot_to(pdf_path)
        meta = {
            "original": doc.path or "",
            "name": os.path.basename(doc.path or "Tanpa Nama.pdf"),
            "page": int(page),
            "zoom": float(zoom),
            "saved_at": time.time(),
            "pages": int(doc.page_count),
            "snapshot": pdf_path,
        }
        tmp = meta_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        os.replace(tmp, meta_path)
        return meta
    except Exception:
        return None


def discard_snapshot(original: str | None) -> None:
    for path in snapshot_paths(original):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def list_snapshots() -> list[dict]:
    """Return every readable recovery snapshot, newest first."""
    base = recovery_dir()
    entries = []
    try:
        names = os.listdir(base)
    except Exception:
        return entries
    for name in names:
        if not name.endswith(".json"):
            continue
        meta_path = os.path.join(base, name)
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except Exception:
            continue
        pdf_path = meta.get("snapshot") or meta_path[:-5] + ".pdf"
        if not os.path.exists(pdf_path):
            continue
        meta["snapshot"] = pdf_path
        entries.append(meta)
    entries.sort(key=lambda m: m.get("saved_at", 0), reverse=True)
    return entries


def prune_snapshots(keep_newer_than_days: float = 14.0) -> int:
    cutoff = time.time() - keep_newer_than_days * 86400
    removed = 0
    for meta in list_snapshots():
        if meta.get("saved_at", 0) >= cutoff:
            continue
        for path in (meta.get("snapshot"),):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                    removed += 1
            except Exception:
                pass
        try:
            os.remove(meta["snapshot"][:-4] + ".json")
        except Exception:
            pass
    return removed
