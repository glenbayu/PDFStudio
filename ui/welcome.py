"""Welcome / empty-state screen with Recent Files and quick actions."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("welcomePanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 24, 20, 24)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("welcomeCard")
        card.setMaximumWidth(640)
        card.setMinimumWidth(420)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 30, 36, 28)
        lay.setSpacing(12)

        logo = QLabel()
        logo.setFixedSize(68, 68)
        logo.setPixmap(theme.app_pixmap(68))
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background:transparent;")
        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)

        title = QLabel("PDF Studio")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        sub = QLabel("Edit, anotasi, isi formulir, dan tanda tangan PDF — tanpa langganan.")
        sub.setObjectName("welcomeSub")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)

        lay.addSpacing(6)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        btn_open = QPushButton("Buka PDF…")
        btn_open.setObjectName("primary")
        btn_open.setMinimumHeight(40)
        btn_open.clicked.connect(self.openRequested.emit)

        btn_img = QPushButton("PDF dari Gambar…")
        btn_img.setMinimumHeight(40)
        btn_img.clicked.connect(self.imagesRequested.emit)

        btn_merge = QPushButton("Gabung PDF…")
        btn_merge.setMinimumHeight(40)
        btn_merge.clicked.connect(self.mergeRequested.emit)

        btn_demo = QPushButton("Buka Dokumen Contoh")
        btn_demo.setMinimumHeight(40)
        btn_demo.clicked.connect(self.demoRequested.emit)

        grid.addWidget(btn_open, 0, 0)
        grid.addWidget(btn_img, 0, 1)
        grid.addWidget(btn_merge, 1, 0)
        grid.addWidget(btn_demo, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        # Recent files box
        self._recent_box = QWidget()
        self._recent_box.setStyleSheet("background:transparent;")
        rlay = QVBoxLayout(self._recent_box)
        rlay.setContentsMargins(0, 8, 0, 0)
        rlay.setSpacing(6)
        rhead = QLabel("Dokumen Terbaru")
        rhead.setObjectName("welcomeSub")
        rhead.setStyleSheet("font-weight:600; background:transparent;")
        rlay.addWidget(rhead)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("welcomeRecent")
        self.recent_list.setMaximumHeight(168)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.itemActivated.connect(self._open_recent_item)
        self.recent_list.itemClicked.connect(self._open_recent_item)
        rlay.addWidget(self.recent_list)
        self._recent_box.hide()
        lay.addWidget(self._recent_box)

        lay.addSpacing(6)
        tips = QLabel("Tarik & lepas file PDF (atau gambar) ke jendela ini  ·  Ctrl+O untuk membuka  ·  Ctrl+K Command Palette")
        tips.setObjectName("welcomeHint")
        tips.setAlignment(Qt.AlignCenter)
        tips.setWordWrap(True)
        lay.addWidget(tips)

        feat = QLabel(
            "Multi-Tab  ·  Sorot  ·  Catatan  ·  Tinta  ·  Edit teks  ·  OCR  ·  "
            "Tanda tangan  ·  TTD digital & verifikasi  ·  Form  ·  Gabung/pisah  ·  Password"
        )
        feat.setObjectName("welcomeFeat")
        feat.setAlignment(Qt.AlignCenter)
        feat.setWordWrap(True)
        lay.addWidget(feat)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(card)
        wrap.addStretch(1)
        outer.addLayout(wrap)
        outer.addStretch(2)

    def set_recent(self, paths: list[str]) -> None:
        self.recent_list.clear()
        existing = [p for p in (paths or []) if isinstance(p, str) and os.path.exists(p)]
        for p in existing[:6]:
            name = os.path.basename(p)
            folder = os.path.dirname(p)
            if len(folder) > 52:
                folder = "…" + folder[-51:]
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
