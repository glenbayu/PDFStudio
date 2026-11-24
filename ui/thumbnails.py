"""Thumbnail sidebar with drag reordering and page actions."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QListWidget, QListWidgetItem, QListView,
                               QMenu, QVBoxLayout, QWidget, QAbstractItemView)


class ThumbnailPanel(QWidget):
    pageSelected = Signal(int)
    moveRequested = Signal(int, int)     # src, dst
    actionRequested = Signal(str, int)   # rotate_l/rotate_r/duplicate/delete/insert

    THUMB_W = 104

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setFlow(QListView.TopToBottom)
        self.list.setWrapping(False)
        self.list.setMovement(QListView.Snap)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setIconSize(QSize(self.THUMB_W, 138))
        self.list.setGridSize(QSize(self.THUMB_W + 26, 168))
        self.list.setSpacing(6)
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list)
        self.doc = None
        self._pending = 0
        self._loading = False
        self._guard = False
        self._drag_from = -1
        self._drag_item = None
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.pressed.connect(self._pressed)
        self.list.model().rowsMoved.connect(self._rows_moved)

    def _new_item(self, i: int) -> QListWidgetItem:
        item = QListWidgetItem(str(i + 1))
        item.setSizeHint(QSize(self.THUMB_W + 26, 168))
        item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        item.setToolTip(f"Halaman {i + 1}")
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
        return item

    def set_document(self, doc):
        self.doc = doc
        self.list.clear()
        self._pending = doc.page_count if doc else 0
        self._loading = False
        if not doc or doc.page_count == 0:
            return
        for i in range(doc.page_count):
            self.list.addItem(self._new_item(i))
        self._loading = True
        QTimer.singleShot(0, self._load_batch)

    def _load_batch(self):
        if not self._loading or self.doc is None:
            return
        done = 0
        while self._pending > 0 and done < 6:
            idx = self.list.count() - self._pending
            self._pending -= 1
            done += 1
            if idx < 0 or idx >= self.list.count():
                continue
            self._render_into(idx)
        if self._pending > 0:
            QTimer.singleShot(10, self._load_batch)
        else:
            self._loading = False

    def _render_into(self, idx: int):
        try:
            w, h = self.doc.page_size(idx)
            if not w:
                return
            zoom = self.THUMB_W / w
            pix = self.doc.render(idx, zoom, 1.0)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGB888).copy()
            item = self.list.item(idx)
            if item is not None:
                item.setIcon(QPixmap.fromImage(img))
        except Exception:
            pass

    def update_page(self, pno: int):
        if not self.doc or pno < 0 or pno >= self.list.count():
            return
        self._render_into(pno)

    def rebuild(self):
        """Recreate items after pages are added/removed."""
        doc = self.doc
        self.list.clear()
        if not doc:
            return
        self._pending = doc.page_count
        for i in range(doc.page_count):
            self.list.addItem(self._new_item(i))
        self._loading = True
        QTimer.singleShot(0, self._load_batch)

    def _row_changed(self, row):
        if not self._guard and row >= 0:
            self.pageSelected.emit(row)

    def set_current(self, pno: int):
        self._guard = True
        self.list.setCurrentRow(pno)
        self._guard = False

    def _pressed(self, index):
        self._drag_from = index.row()
        self._drag_item = self.list.item(index.row())

    def _rows_moved(self, *_args):
        """Emit the page move requested by an internal drag."""
        if self._drag_from < 0 or self._drag_item is None:
            return
        src = self._drag_from
        dst = self.list.row(self._drag_item)
        self._guard = True
        try:
            if src != dst and dst >= 0:
                for i in range(self.list.count()):
                    self.list.item(i).setText(str(i + 1))
                self.moveRequested.emit(src, dst)
        finally:
            self._drag_from = -1
            self._drag_item = None
            self._guard = False

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        row = self.list.row(item)
        menu = QMenu(self)
        menu.addAction("Putar kiri", lambda: self.actionRequested.emit("rotate_l", row))
        menu.addAction("Putar kanan", lambda: self.actionRequested.emit("rotate_r", row))
        menu.addSeparator()
        menu.addAction("Duplikat halaman", lambda: self.actionRequested.emit("duplicate", row))
        menu.addAction("Sisip halaman kosong", lambda: self.actionRequested.emit("insert", row))
        menu.addSeparator()
        menu.addAction("Hapus halaman", lambda: self.actionRequested.emit("delete", row))
        menu.exec(self.list.mapToGlobal(pos))
