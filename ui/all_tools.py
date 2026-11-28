"""PdfCraft-style collapsible 'All Tools' catalogue panel with colour-coded icons."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

from ui.theme import icon


class AllToolsPanel(QWidget):
    """Searchable, grouped catalogue of PDF tools with colour-coded icons."""

    closeRequested = Signal()

    def __init__(self, groups: list[tuple[str, list[tuple[str, object, str, str]]]], parent=None):
        super().__init__(parent)
        self.setObjectName("allToolsPanel")
        self._items: list[tuple[str, QToolButton, QWidget]] = []
        self._sections: list[tuple[QLabel, list[tuple[str, QToolButton]]]] = []
        self._colored_btns: list[tuple[QToolButton, str, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setContentsMargins(4, 0, 2, 0)
        title = QLabel("Semua Alat")
        title.setObjectName("allToolsTopTitle")
        top.addWidget(title, 1)
        btn_close = QToolButton()
        btn_close.setText("×")
        btn_close.setToolTip("Tutup panel Semua Alat")
        btn_close.setFixedSize(24, 24)
        btn_close.clicked.connect(self.closeRequested.emit)
        top.addWidget(btn_close)
        root.addLayout(top)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Cari alat…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("allToolsBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 2, 2, 8)
        lay.setSpacing(2)

        for sec_title, entries in groups:
            hdr = QLabel(sec_title)
            hdr.setObjectName("allToolsHeader")
            lay.addWidget(hdr)
            sec_btns: list[tuple[str, QToolButton]] = []
            for label, action, icon_name, color_hex in entries:
                btn = QToolButton()
                btn.setObjectName("allToolsBtn")
                btn.setDefaultAction(action)
                btn.setText(label.replace("&", "&&"))
                if icon_name:
                    btn.setIcon(icon(icon_name, color=color_hex))
                    self._colored_btns.append((btn, icon_name, color_hex))
                btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                btn.setIconSize(QSize(18, 18))
                btn.setMinimumWidth(185)
                btn.setMinimumHeight(34)
                btn.setAutoRaise(True)
                lay.addWidget(btn)
                sec_btns.append((label.lower(), btn))
                self._items.append((label.lower(), btn, hdr))
            self._sections.append((hdr, sec_btns))

        lay.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def refresh_icons(self):
        for btn, icon_name, color_hex in self._colored_btns:
            btn.setIcon(icon(icon_name, color=color_hex))

    def _apply_filter(self, text: str):
        q = (text or "").strip().lower()
        for hdr, sec_btns in self._sections:
            any_visible = False
            for label, btn in sec_btns:
                vis = (not q) or (q in label)
                btn.setVisible(vis)
                if vis:
                    any_visible = True
            hdr.setVisible(any_visible)
