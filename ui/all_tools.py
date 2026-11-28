"""Acrobat/PdfCraft-style collapsible 'All Tools' catalogue panel."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)


class AllToolsPanel(QWidget):
    """Searchable, grouped catalogue of PDF tools with icons and labels."""

    def __init__(self, groups: list[tuple[str, list[tuple[str, object]]]], parent=None):
        super().__init__(parent)
        self.setObjectName("allToolsPanel")
        self._items: list[tuple[str, QToolButton, QWidget]] = []
        self._sections: list[tuple[QLabel, list[tuple[str, QToolButton]]]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

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
        lay.setContentsMargins(2, 2, 2, 8)
        lay.setSpacing(4)

        for title, actions in groups:
            hdr = QLabel(title)
            hdr.setObjectName("allToolsHeader")
            lay.addWidget(hdr)
            sec_btns: list[tuple[str, QToolButton]] = []
            for label, action in actions:
                btn = QToolButton()
                btn.setObjectName("allToolsBtn")
                btn.setDefaultAction(action)
                btn.setText(label)
                btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                btn.setIconSize(QSize(18, 18))
                btn.setSizePolicy(btn.sizePolicy().horizontalPolicy(),
                                  btn.sizePolicy().verticalPolicy())
                btn.setMinimumWidth(180)
                btn.setAutoRaise(True)
                lay.addWidget(btn)
                sec_btns.append((label.lower(), btn))
                self._items.append((label.lower(), btn, hdr))
            self._sections.append((hdr, sec_btns))

        lay.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

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
