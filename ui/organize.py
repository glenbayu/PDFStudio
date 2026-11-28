"""Full-canvas 'Organize Pages' grid view (PdfCraft / Acrobat style)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel,
                               QListView, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QScrollArea, QSlider,
                               QVBoxLayout, QWidget)


class OrganizePagesView(QWidget):
    """Full-canvas page grid with multi-select, drag-reorder, and batch toolbar."""

    batchAction = Signal(str, list)   # action_name, sorted 0-based page indices
    moveRequested = Signal(int, int)  # src, dst
    pageActivated = Signal(int)       # double-click page -> jump & exit
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("organizePagesView")
        self.doc = None
        self._thumb_w = 160
        self._pending = 0
        self._loading = False
        self._drag_from = -1
        self._drag_item = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- top page toolbar (scrollable horizontally on narrow windows so it never widens MainWindow)
        bar = QWidget()
        bar.setObjectName("organizeBar")
        blay = QHBoxLayout(bar)
        blay.setContentsMargins(10, 6, 10, 6)
        blay.setSpacing(6)
        bar_scroll = QScrollArea()
        bar_scroll.setObjectName("organizeBarScroll")
        bar_scroll.setWidgetResizable(True)
        bar_scroll.setFrameShape(QFrame.NoFrame)
        bar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        bar_scroll.setFixedHeight(48)
        bar_scroll.setMinimumWidth(0)

        self.sel_label = QLabel("0 halaman dipilih")
        self.sel_label.setObjectName("hint")
        self.sel_label.setMinimumWidth(140)
        blay.addWidget(self.sel_label)

        self.btn_sel_all = QPushButton("Pilih Semua")
        self.btn_sel_all.clicked.connect(self.select_all)
        blay.addWidget(self.btn_sel_all)

        self.btn_rot_l = QPushButton("Putar Kiri")
        self.btn_rot_l.clicked.connect(lambda: self._emit_batch("rotate_l"))
        blay.addWidget(self.btn_rot_l)

        self.btn_rot_r = QPushButton("Putar Kanan")
        self.btn_rot_r.clicked.connect(lambda: self._emit_batch("rotate_r"))
        blay.addWidget(self.btn_rot_r)

        self.btn_insert = QPushButton("Sisip Kosong")
        self.btn_insert.clicked.connect(lambda: self._emit_batch("insert_blank"))
        blay.addWidget(self.btn_insert)

        self.btn_insert_pdf = QPushButton("Sisip dari PDF…")
        self.btn_insert_pdf.clicked.connect(lambda: self._emit_batch("insert_pdf"))
        blay.addWidget(self.btn_insert_pdf)

        self.btn_dup = QPushButton("Duplikat")
        self.btn_dup.clicked.connect(lambda: self._emit_batch("duplicate"))
        blay.addWidget(self.btn_dup)

        self.btn_extract = QPushButton("Ekstrak…")
        self.btn_extract.clicked.connect(lambda: self._emit_batch("extract"))
        blay.addWidget(self.btn_extract)

        self.btn_delete = QPushButton("Hapus")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.clicked.connect(lambda: self._emit_batch("delete"))
        blay.addWidget(self.btn_delete)

        blay.addStretch(1)

        size_lbl = QLabel("Ukuran:")
        size_lbl.setObjectName("hint")
        blay.addWidget(size_lbl)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(110, 260)
        self.size_slider.setValue(self._thumb_w)
        self.size_slider.setFixedWidth(96)
        self.size_slider.valueChanged.connect(self._on_size_changed)
        blay.addWidget(self.size_slider)

        self.btn_done = QPushButton("Selesai")
        self.btn_done.setObjectName("primary")
        self.btn_done.clicked.connect(self.closeRequested.emit)
        blay.addWidget(self.btn_done)

        bar_scroll.setWidget(bar)
        root.addWidget(bar_scroll)

        # ---- page card grid
        self.grid = QListWidget()
        self.grid.setObjectName("organizeGrid")
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setFlow(QListView.LeftToRight)
        self.grid.setWrapping(True)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setMovement(QListView.Snap)
        self.grid.setDragDropMode(QAbstractItemView.InternalMove)
        self.grid.setDefaultDropAction(Qt.MoveAction)
        self.grid.setSpacing(14)
        self.grid.setUniformItemSizes(True)
        self.grid.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        self.grid.itemSelectionChanged.connect(self._update_selection_ui)
        self.grid.itemDoubleClicked.connect(
            lambda item: self.pageActivated.emit(self.grid.row(item)))
        self.grid.pressed.connect(self._pressed)
        self.grid.model().rowsMoved.connect(self._rows_moved)
        self._apply_grid_metrics()
        root.addWidget(self.grid, 1)

        self._update_selection_ui()

    def _apply_grid_metrics(self):
        h = int(self._thumb_w * 1.35)
        self.grid.setIconSize(QSize(self._thumb_w, h))
        self.grid.setGridSize(QSize(self._thumb_w + 30, h + 38))
        for i in range(self.grid.count()):
            self.grid.item(i).setSizeHint(QSize(self._thumb_w + 26, h + 34))

    def _on_size_changed(self, val: int):
        self._thumb_w = val
        self._apply_grid_metrics()
        self.rebuild()

    def set_document(self, doc):
        self.doc = doc
        self.rebuild()

    def rebuild(self):
        self.grid.clear()
        self._loading = False
        if not self.doc or not self.doc.is_open or self.doc.page_count == 0:
            self._pending = 0
            self._update_selection_ui()
            return
        h = int(self._thumb_w * 1.35)
        for i in range(self.doc.page_count):
            item = QListWidgetItem(f"Halaman {i + 1}")
            item.setSizeHint(QSize(self._thumb_w + 26, h + 34))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
            self.grid.addItem(item)
        self._pending = self.doc.page_count
        self._loading = True
        QTimer.singleShot(0, self._load_batch)
        self._update_selection_ui()

    def _load_batch(self):
        if not self._loading or not self.doc or not self.doc.is_open:
            return
        done = 0
        while self._pending > 0 and done < 6:
            idx = self.grid.count() - self._pending
            self._pending -= 1
            done += 1
            if 0 <= idx < self.grid.count():
                self._render_into(idx)
        if self._pending > 0:
            QTimer.singleShot(10, self._load_batch)
        else:
            self._loading = False

    def _render_into(self, idx: int):
        try:
            w, _h = self.doc.page_size(idx)
            if not w:
                return
            zoom = self._thumb_w / w
            pix = self.doc.render(idx, zoom, 1.0)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGB888).copy()
            item = self.grid.item(idx)
            if item is not None:
                item.setIcon(QPixmap.fromImage(img))
        except Exception:
            pass

    def selected_pages(self) -> list[int]:
        return sorted({self.grid.row(it) for it in self.grid.selectedItems()
                       if self.grid.row(it) >= 0})

    def select_all(self):
        if self.grid.count() == len(self.selected_pages()):
            self.grid.clearSelection()
        else:
            self.grid.selectAll()

    def _update_selection_ui(self):
        pages = self.selected_pages()
        total = self.grid.count()
        n = len(pages)
        self.sel_label.setText(f"{n} dari {total} halaman dipilih" if total else "0 halaman")
        has_sel = n > 0
        for b in (self.btn_rot_l, self.btn_rot_r, self.btn_dup, self.btn_extract):
            b.setEnabled(has_sel)
        self.btn_delete.setEnabled(has_sel and total - n >= 1)
        self.btn_insert.setEnabled(total > 0)
        self.btn_insert_pdf.setEnabled(total > 0)
        self.btn_sel_all.setText("Batal Pilih" if total and n == total else "Pilih Semua")

    def _emit_batch(self, action: str):
        self.batchAction.emit(action, self.selected_pages())

    def _pressed(self, index):
        self._drag_from = index.row()
        self._drag_item = self.grid.item(index.row())

    def _rows_moved(self, *_args):
        if self._drag_from < 0 or self._drag_item is None:
            return
        src = self._drag_from
        dst = self.grid.row(self._drag_item)
        try:
            if src != dst and dst >= 0:
                for i in range(self.grid.count()):
                    self.grid.item(i).setText(f"Halaman {i + 1}")
                self.moveRequested.emit(src, dst)
        finally:
            self._drag_from = -1
            self._drag_item = None

    def _context_menu(self, pos):
        item = self.grid.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.grid.clearSelection()
            item.setSelected(True)
        menu = QMenu(self)
        menu.addAction("Buka halaman ini", lambda: self.pageActivated.emit(self.grid.row(item)))
        menu.addSeparator()
        menu.addAction("Putar Kiri", lambda: self._emit_batch("rotate_l"))
        menu.addAction("Putar Kanan", lambda: self._emit_batch("rotate_r"))
        menu.addAction("Duplikat", lambda: self._emit_batch("duplicate"))
        menu.addAction("Sisip halaman kosong setelahnya", lambda: self._emit_batch("insert_blank"))
        menu.addAction("Ekstrak ke PDF baru…", lambda: self._emit_batch("extract"))
        menu.addSeparator()
        act_del = menu.addAction("Hapus halaman terpilih", lambda: self._emit_batch("delete"))
        pages = self.selected_pages()
        act_del.setEnabled(bool(pages) and (self.grid.count() - len(pages) >= 1))
        menu.exec(self.grid.mapToGlobal(pos))
