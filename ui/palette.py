"""Ctrl+K command palette."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QLineEdit, QListWidget,
                               QListWidgetItem, QVBoxLayout)

from ui.theme import icon


class CommandPalette(QDialog):
    """Searchable launcher for every action in the app."""

    def __init__(self, parent, commands):
        super().__init__(parent, Qt.Popup)
        self.setWindowTitle("Command Palette")
        self.setModal(True)
        self.resize(560, 420)
        self._commands = commands
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Ketik perintah…  (mis. simpan, watermark, zoom)")
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        lay.addWidget(self.list, 1)
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._run)
        self.list.itemActivated.connect(lambda _i: self._run())
        self._filter("")
        self.edit.setFocus()

    def _filter(self, text):
        needle = text.strip().lower()
        self.list.clear()
        for cmd in self._commands:
            hay = f"{cmd['title']} {cmd.get('shortcut', '')} {cmd.get('hint', '')}".lower()
            if needle and needle not in hay:
                continue
            label = cmd["title"]
            if cmd.get("shortcut"):
                label += f"    {cmd['shortcut']}"
            item = QListWidgetItem(icon(cmd.get("icon", "search")), label)
            item.setData(Qt.UserRole, cmd["run"])
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run(self):
        item = self.list.currentItem()
        if item is None:
            return
        run = item.data(Qt.UserRole)
        self.accept()
        if run:
            run()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow()
            row += 1 if ev.key() == Qt.Key_Down else -1
            row = max(0, min(row, self.list.count() - 1))
            self.list.setCurrentRow(row)
            return
        if ev.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(ev)
