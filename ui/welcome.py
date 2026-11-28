"""PdfCraft-style Home / Welcome workspace with Recommended Tools & Recent Files."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from ui import theme


class WelcomePanel(QWidget):
    openRequested = Signal()
    demoRequested = Signal()
    imagesRequested = Signal()
    mergeRequested = Signal()
    fileRequested = Signal(str)
    toolRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("welcomePanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 24)
        outer.setSpacing(18)

        # ---- Header
        hdr = QHBoxLayout()
        hdr.setSpacing(14)
        logo = QLabel()
        logo.setFixedSize(48, 48)
        logo.setPixmap(theme.app_pixmap(48))
        logo.setStyleSheet("background:transparent;")
        hdr.addWidget(logo)

        htxt = QVBoxLayout()
        htxt.setSpacing(2)
        title = QLabel("Welcome to PDF Studio")
        title.setObjectName("welcomeTitle")
        htxt.addWidget(title)
        sub = QLabel("Workbench PDF lokal & privat — baca, edit teks, anotasi, formulir, OCR, dan tanda tangan digital.")
        sub.setObjectName("welcomeSub")
        sub.setWordWrap(True)
        htxt.addWidget(sub)
        hdr.addLayout(htxt, 1)
        outer.addLayout(hdr)

        # ---- Recommended tools section (PdfCraft style)
        sec_rec = QFrame()
        sec_rec.setObjectName("welcomeSection")
        srl = QVBoxLayout(sec_rec)
        srl.setContentsMargins(18, 16, 18, 16)
        srl.setSpacing(12)

        rec_lbl = QLabel("Alat yang Direkomendasikan")
        rec_lbl.setObjectName("title")
        rec_lbl.setStyleSheet("background:transparent;")
        srl.addWidget(rec_lbl)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        cards = [
            ("Kelola halaman", "Grid · Putar · Hapus", "fit_page", "#4ade80", "organize"),
            ("Tambah komentar", "Sorot · Catatan · Tinta", "note", "#fbbf24", "highlight"),
            ("Siapkan formulir", "Isi & buat field baru", "form", "#c084fc", "add_form"),
            ("Edit PDF", "Edit & tambah teks", "edit_text", "#f472b6", "edit_text"),
            ("Lindungi PDF", "Password AES-256 · Redaksi", "lock", "#60a5fa", "protect"),
        ]
        for idx, (cname, desc, iname, col, action_key) in enumerate(cards):
            btn = QPushButton()
            btn.setObjectName("recToolCard")
            btn.setMinimumHeight(88)
            btn.setCursor(Qt.PointingHandCursor)
            bl = QVBoxLayout(btn)
            bl.setContentsMargins(10, 8, 10, 8)
            bl.setSpacing(4)
            top_r = QHBoxLayout()
            ic_lbl = QLabel()
            ic_lbl.setPixmap(theme.icon(iname, color=col, size=20).pixmap(20, 20))
            ic_lbl.setStyleSheet("background:transparent;")
            name_lbl = QLabel(cname)
            name_lbl.setStyleSheet("font-weight:600; background:transparent;")
            top_r.addWidget(ic_lbl)
            top_r.addWidget(name_lbl, 1)
            bl.addLayout(top_r)
            desc_lbl = QLabel(desc)
            desc_lbl.setObjectName("welcomeHint")
            desc_lbl.setWordWrap(True)
            bl.addWidget(desc_lbl)
            use_lbl = QLabel("Gunakan →")
            use_lbl.setStyleSheet("color:#60a5fa; font-size:12px; font-weight:600; background:transparent;")
            bl.addWidget(use_lbl)
            btn.clicked.connect(lambda _c=False, k=action_key: self.toolRequested.emit(k))
            grid.addWidget(btn, idx // 3, idx % 3)

        btn_open = QPushButton("  Buka File PDF…")
        btn_open.setObjectName("openTile")
        btn_open.setIcon(theme.icon("open", color="#60a5fa", size=22))
        btn_open.setIconSize(QSize(22, 22))
        btn_open.setMinimumHeight(88)
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(self.openRequested.emit)
        grid.addWidget(btn_open, 1, 2)

        for c in range(3):
            grid.setColumnStretch(c, 1)
        srl.addLayout(grid)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        btn_img = QPushButton("PDF dari Gambar…")
        btn_img.clicked.connect(self.imagesRequested.emit)
        btn_merge = QPushButton("Gabung PDF…")
        btn_merge.clicked.connect(self.mergeRequested.emit)
        btn_demo = QPushButton("Buka Dokumen Contoh")
        btn_demo.clicked.connect(self.demoRequested.emit)
        quick_row.addWidget(btn_img)
        quick_row.addWidget(btn_merge)
        quick_row.addWidget(btn_demo)
        quick_row.addStretch(1)
        srl.addLayout(quick_row)

        outer.addWidget(sec_rec)

        # ---- Recent files
        self._recent_box = QFrame()
        self._recent_box.setObjectName("welcomeSection")
        rlay = QVBoxLayout(self._recent_box)
        rlay.setContentsMargins(18, 14, 18, 14)
        rlay.setSpacing(8)
        rhead = QLabel("Dokumen Terbaru")
        rhead.setObjectName("title")
        rhead.setStyleSheet("background:transparent;")
        rlay.addWidget(rhead)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("welcomeRecent")
        self.recent_list.setMaximumHeight(168)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.itemActivated.connect(self._open_recent_item)
        self.recent_list.itemClicked.connect(self._open_recent_item)
        rlay.addWidget(self.recent_list)
        self._recent_box.hide()
        outer.addWidget(self._recent_box)

        priv = QLabel(
            "PRIVASI · PDF Studio berjalan 100% offline di perangkatmu. "
            "Tanpa akun, tanpa telemetri, dan tanpa pemrosesan cloud.  ·  Ctrl+K Command Palette"
        )
        priv.setObjectName("welcomeHint")
        priv.setWordWrap(True)
        outer.addWidget(priv)
        outer.addStretch(1)

    def set_recent(self, paths: list[str]) -> None:
        self.recent_list.clear()
        existing = [p for p in (paths or []) if isinstance(p, str) and os.path.exists(p)]
        for p in existing[:6]:
            name = os.path.basename(p)
            folder = os.path.dirname(p)
            if len(folder) > 56:
                folder = "…" + folder[-55:]
            item = QListWidgetItem(f"{name}   —   {folder}")
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            self.recent_list.addItem(item)
        self._recent_box.setVisible(self.recent_list.count() > 0)

    def _open_recent_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if path:
            self.fileRequested.emit(path)

    def dragEnterEvent(self, ev):
        ev.ignore()
