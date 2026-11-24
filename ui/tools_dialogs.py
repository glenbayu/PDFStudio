"""Dialogs for search & replace, watermark, batch tools, stamps and friends."""
from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog,
                               QComboBox, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QRadioButton, QSpinBox, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ui.dialogs import BaseDialog, _buttons
from ui.theme import ACCENT, MUTED


def parse_pages(text: str, count: int) -> list[int]:
    out: list[int] = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if m:
            a, b = sorted((int(m.group(1)), int(m.group(2))))
            out.extend(range(a - 1, b))
        elif part.isdigit():
            out.append(int(part) - 1)
    return sorted(set(p for p in out if 0 <= p < count))


class _PagesDialog(BaseDialog):
    def __init__(self, parent, title, count, width=520):
        super().__init__(parent, title, width)
        self.count = count
        self.header(title, f"Dokumen punya {count} halaman.")

    def _add_pages_row(self, layout, label="Halaman"):
        self.pages_edit = QLineEdit(f"1-{self.count}")
        self.pages_edit.setPlaceholderText("1-3,5 (kosong = semua)")
        layout.addRow(label, self.pages_edit)

    def pages(self):
        text = self.pages_edit.text().strip()
        return parse_pages(text, self.count) if text else list(range(self.count))


# ------------------------------------------------------------ search & replace
class SearchReplaceDialog(BaseDialog):
    def __init__(self, parent=None, doc=None, pno=0, query=""):
        super().__init__(parent, "Cari & Ganti", 620)
        self.doc = doc
        self.pno = pno
        self.header("Cari & ganti teks",
                    "Penggantian memakai font asli tiap baris yang cocok.")
        form = QFormLayout()
        form.setSpacing(9)
        self.find_edit = QLineEdit(query)
        self.find_edit.setPlaceholderText("Teks yang dicari")
        self.repl_edit = QLineEdit()
        self.repl_edit.setPlaceholderText("Teks pengganti")
        form.addRow("Cari", self.find_edit)
        form.addRow("Ganti dengan", self.repl_edit)
        self.root.addLayout(form)

        opts = QHBoxLayout()
        self.case_cb = QCheckBox("Bedakan huruf besar/kecil")
        self.word_cb = QCheckBox("Kata utuh")
        self.regex_cb = QCheckBox("Regex")
        opts.addWidget(self.case_cb)
        opts.addWidget(self.word_cb)
        opts.addWidget(self.regex_cb)
        opts.addStretch(1)
        self.root.addLayout(opts)

        scope = QHBoxLayout()
        scope.addWidget(QLabel("Cakupan"))
        self.scope_box = QComboBox()
        self.scope_box.addItems(["Seluruh dokumen", "Halaman ini"])
        scope.addWidget(self.scope_box, 1)
        self.root.addLayout(scope)

        self.results = QListWidget()
        self.results.setMinimumHeight(150)
        self.root.addWidget(self.results)
        self.count_label = QLabel("Belum ada pencarian.")
        self.count_label.setObjectName("hint")
        self.root.addWidget(self.count_label)

        row = QHBoxLayout()
        find_btn = QPushButton("Cari Semua")
        find_btn.clicked.connect(self.run_search)
        row.addWidget(find_btn)
        row.addStretch(1)
        box, _ = _buttons(self, "Ganti Semua")
        row.addWidget(box)
        self.root.addLayout(row)
        self.find_edit.setFocus()
        if query:
            self.run_search()

    def run_search(self):
        if self.doc is None:
            return
        query = self.find_edit.text()
        self.results.clear()
        if not query.strip():
            self.count_label.setText("Isi teks yang mau dicari.")
            return
        pages = [self.pno] if self.scope_box.currentIndex() == 1 else None
        hits = 0
        for pno in (pages if pages is not None else range(self.doc.page_count)):
            try:
                found = self.doc.page(pno).search_for(query)
            except Exception:
                found = []
            for r in found:
                try:
                    snippet = self.doc.page(pno).get_textbox(r).strip()
                except Exception:
                    snippet = query
                item = QListWidgetItem(f"Hal {pno + 1}  ·  {snippet[:90]}")
                item.setToolTip(snippet)
                self.results.addItem(item)
                hits += 1
                if hits >= 400:
                    break
        self.count_label.setText(f"{hits} kecocokan ditemukan."
                                 if hits else "Tidak ada kecocokan.")

    def values(self):
        return {
            "query": self.find_edit.text(),
            "replacement": self.repl_edit.text(),
            "match_case": self.case_cb.isChecked(),
            "whole_word": self.word_cb.isChecked(),
            "regex": self.regex_cb.isChecked(),
            "pages": [self.pno] if self.scope_box.currentIndex() == 1 else None,
        }


# ---------------------------------------------------------------- watermark
class WatermarkDialog(_PagesDialog):
    def __init__(self, parent=None, count=1, text="RAHASIA"):
        super().__init__(parent, "Watermark", count, 540)
        self.header("Watermark",
                    "Teks dicetak miring di tengah halaman. Bisa juga diulang (tile).")
        form = QFormLayout()
        form.setSpacing(9)
        self.text_edit = QLineEdit(text)
        form.addRow("Teks", self.text_edit)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(8, 180)
        self.size_spin.setValue(46)
        self.size_spin.setSuffix(" pt")
        form.addRow("Ukuran", self.size_spin)
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.03, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(0.18)
        form.addRow("Transparansi", self.opacity_spin)
        row = QHBoxLayout()
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(46, 28)
        self._color = QColor("#d81a1a")
        self._paint_color()
        self.color_btn.clicked.connect(self._pick_color)
        row.addWidget(self.color_btn)
        row.addStretch(1)
        form.addRow("Warna", row)
        self.diag_cb = QCheckBox("Miring 30°")
        self.diag_cb.setChecked(True)
        self.tile_cb = QCheckBox("Ulangi penuh halaman (tile)")
        opt = QHBoxLayout()
        opt.addWidget(self.diag_cb)
        opt.addWidget(self.tile_cb)
        opt.addStretch(1)
        self.root.addLayout(form)
        self.root.addLayout(opt)
        self._add_pages_row(form)
        box, _ = _buttons(self, "Terapkan")
        self.root.addWidget(box)

    def _paint_color(self):
        self.color_btn.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #4a4f59; border-radius:6px;")

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Warna Watermark")
        if c.isValid():
            self._color = c
            self._paint_color()

    def values(self):
        c = self._color
        return {
            "text": self.text_edit.text(),
            "size": self.size_spin.value(),
            "opacity": self.opacity_spin.value(),
            "color": (c.redF(), c.greenF(), c.blueF()),
            "diagonal": self.diag_cb.isChecked(),
            "tiled": self.tile_cb.isChecked(),
            "pages": self.pages(),
        }


# --------------------------------------------------------------- page numbers
class PageNumberDialog(_PagesDialog):
    def __init__(self, parent=None, count=1):
        super().__init__(parent, "Nomor Halaman", count, 520)
        self.header("Nomor halaman",
                    "Tambahkan nomor ke setiap halaman terpilih.")
        form = QFormLayout()
        form.setSpacing(9)
        self.pos_box = QComboBox()
        self.pos_box.addItems(["Bawah tengah", "Bawah kanan", "Bawah kiri",
                               "Atas tengah", "Atas kanan", "Atas kiri"])
        self.fmt_edit = QLineEdit("Halaman {page} dari {total}")
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, 9999)
        self.start_spin.setValue(1)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(6, 48)
        self.size_spin.setValue(9)
        self.size_spin.setSuffix(" pt")
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(6, 120)
        self.margin_spin.setValue(26)
        self.margin_spin.setSuffix(" pt")
        form.addRow("Posisi", self.pos_box)
        form.addRow("Format", self.fmt_edit)
        form.addRow("Mulai dari", self.start_spin)
        form.addRow("Ukuran", self.size_spin)
        form.addRow("Margin", self.margin_spin)
        self._add_pages_row(form)
        self.root.addLayout(form)
        box, _ = _buttons(self, "Terapkan")
        self.root.addWidget(box)

    def values(self):
        pos = ["bottom-center", "bottom-right", "bottom-left",
               "top-center", "top-right", "top-left"][self.pos_box.currentIndex()]
        return {
            "position": pos, "start": self.start_spin.value(),
            "fmt": self.fmt_edit.text(), "size": self.size_spin.value(),
            "margin": self.margin_spin.value(), "pages": self.pages(),
        }


# --------------------------------------------------------------- header/footer
class HeaderFooterDialog(_PagesDialog):
    def __init__(self, parent=None, count=1):
        super().__init__(parent, "Header & Footer", count, 540)
        self.header("Header & footer",
                    "Placeholder: {page}, {total}, {date}, {title}")
        form = QFormLayout()
        form.setSpacing(9)
        self.head_edit = QLineEdit()
        self.head_edit.setPlaceholderText("Contoh: {title}")
        self.foot_edit = QLineEdit("{page} / {total}")
        self.align_box = QComboBox()
        self.align_box.addItems(["Tengah", "Kiri", "Kanan"])
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(6, 40)
        self.size_spin.setValue(9)
        self.size_spin.setSuffix(" pt")
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(6, 120)
        self.margin_spin.setValue(26)
        self.margin_spin.setSuffix(" pt")
        form.addRow("Header", self.head_edit)
        form.addRow("Footer", self.foot_edit)
        form.addRow("Perataan", self.align_box)
        form.addRow("Ukuran", self.size_spin)
        form.addRow("Margin", self.margin_spin)
        self._add_pages_row(form)
        self.root.addLayout(form)
        box, _ = _buttons(self, "Terapkan")
        self.root.addWidget(box)

    def values(self):
        return {
            "header": self.head_edit.text(), "footer": self.foot_edit.text(),
            "align": ["center", "left", "right"][self.align_box.currentIndex()],
            "size": self.size_spin.value(), "margin": self.margin_spin.value(),
            "pages": self.pages(),
        }


# --------------------------------------------------------------------- stamps
STAMPS = [
    ("DRAFT", "#b4541a"), ("DISETUJUI", "#1a7a3c"), ("RAHASIA", "#b32020"),
    ("TERBATAS", "#b32020"), ("REVISI", "#1a5fa8"), ("BATAL", "#6b6b6b"),
    ("LUNAS", "#1a7a3c"), ("SALINAN", "#1a5fa8"),
]


class StampDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Stempel", 470)
        self.header("Stempel", "Klik stempel lalu tempel di halaman.")
        self.text_edit = QLineEdit("DISETUJUI")
        form = QFormLayout()
        form.addRow("Teks", self.text_edit)
        self.root.addLayout(form)
        grid = QHBoxLayout()
        for name, col in STAMPS:
            b = QPushButton(name)
            b.setFixedHeight(30)
            b.setStyleSheet(f"border:1px solid {col}; color:{col}; font-weight:700;"
                            "border-radius:5px;")
            b.clicked.connect(lambda _c=False, t=name: self.text_edit.setText(t))
            grid.addWidget(b)
            if grid.count() % 4 == 0:
                self.root.addLayout(grid)
                grid = QHBoxLayout()
        if grid.count():
            grid.addStretch(1)
            self.root.addLayout(grid)

        row = QHBoxLayout()
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(42, 28)
        self._color = QColor("#b32020")
        self._paint()
        self.color_btn.clicked.connect(self._pick)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(8, 72)
        self.size_spin.setValue(22)
        self.size_spin.setSuffix(" pt")
        row.addWidget(QLabel("Warna"))
        row.addWidget(self.color_btn)
        row.addWidget(QLabel("Ukuran"))
        row.addWidget(self.size_spin)
        row.addStretch(1)
        self.root.addLayout(row)

        box, _ = _buttons(self, "Tempel")
        self.root.addWidget(box)

    def _paint(self):
        self.color_btn.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #4a4f59; border-radius:6px;")

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, "Warna Stempel")
        if c.isValid():
            self._color = c
            self._paint()

    def values(self):
        c = self._color
        return {"text": self.text_edit.text(), "fontsize": self.size_spin.value(),
                "color": (c.redF(), c.greenF(), c.blueF())}


# -------------------------------------------------------------- annotation props
class AnnotPropsDialog(BaseDialog):
    def __init__(self, parent=None, annot=None):
        annot = annot or {}
        super().__init__(parent, "Properti Anotasi", 480)
        self.annot = annot
        self.header(f"Anotasi · {annot.get('kind', '')}",
                    "Ubah warna, tebal, transparansi, isi, atau posisi.")
        self.color_btn = QPushButton()
        self.color_btn.setFixedHeight(30)
        stroke = annot.get("stroke") or (0.9, 0.3, 0.3)
        self._color = QColor.fromRgbF(*stroke)
        self._paint_color()
        self.color_btn.clicked.connect(self._pick_color)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.4, 20)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setValue(float(annot.get("width") or 1.0))
        self.width_spin.setSuffix(" pt")
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.05, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(float(annot.get("opacity") or 1.0))
        self.content_edit = QPlainTextEdit(annot.get("content") or "")
        self.content_edit.setMaximumHeight(84)

        r = annot.get("rect") or (0, 0, 100, 100)
        self.x_spin = self._num(r[0])
        self.y_spin = self._num(r[1])
        self.w_spin = self._num(max(1.0, r[2] - r[0]))
        self.h_spin = self._num(max(1.0, r[3] - r[1]))

        form = QFormLayout()
        form.setSpacing(8)
        form.addRow("Warna", self.color_btn)
        form.addRow("Tebal", self.width_spin)
        form.addRow("Transparansi", self.opacity_spin)
        form.addRow("Isi", self.content_edit)
        pos = QHBoxLayout()
        for lab, w in (("X", self.x_spin), ("Y", self.y_spin),
                       ("L", self.w_spin), ("T", self.h_spin)):
            pos.addWidget(QLabel(lab))
            pos.addWidget(w)
        form.addRow("Posisi", pos)
        self.root.addLayout(form)
        box, _ = _buttons(self, "Simpan")
        self.root.addWidget(box)

    @staticmethod
    def _num(v):
        s = QDoubleSpinBox()
        s.setRange(-5000, 5000)
        s.setDecimals(1)
        s.setValue(float(v))
        return s

    def _paint_color(self):
        self.color_btn.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #4a4f59; border-radius:6px;")

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Warna Anotasi")
        if c.isValid():
            self._color = c
            self._paint_color()

    def values(self):
        c = self._color
        return {
            "color": (c.redF(), c.greenF(), c.blueF()),
            "width": self.width_spin.value(),
            "opacity": self.opacity_spin.value(),
            "content": self.content_edit.toPlainText(),
            "rect": (self.x_spin.value(), self.y_spin.value(),
                     self.x_spin.value() + self.w_spin.value(),
                     self.y_spin.value() + self.h_spin.value()),
        }


# --------------------------------------------------------------------- compare
class CompareDialog(BaseDialog):
    def __init__(self, parent=None, result=None, name_a="", name_b=""):
        super().__init__(parent, "Bandingkan PDF", 760)
        result = result or {}
        self.header("Hasil perbandingan",
                    f"{os.path.basename(name_a)} ↔ {os.path.basename(name_b)}")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Halaman / baris", "Isi"])
        self.tree.setColumnWidth(0, 150)
        self.tree.setMinimumHeight(380)
        self.root.addWidget(self.tree)
        for page in result.get("pages", []):
            root = QTreeWidgetItem(
                [f"Halaman {page['page'] + 1}",
                 f"+{page['added']}  −{page['removed']}"])
            for row in page["rows"]:
                sign = "+" if row["op"] == "add" else "−"
                item = QTreeWidgetItem([sign, row["text"][:180]])
                item.setForeground(0, QColor("#2eb872" if row["op"] == "add"
                                             else "#e5484d"))
                root.addChild(item)
            self.tree.addTopLevelItem(root)
            root.setExpanded(True)
        if not result.get("pages"):
            self.tree.addTopLevelItem(QTreeWidgetItem(["Tidak ada perbedaan teks", ""]))
        self.summary = QLabel(f"{result.get('added', 0)} baris ditambah · "
                              f"{result.get('removed', 0)} baris dihapus · "
                              f"{len(result.get('pages', []))} halaman berbeda")
        self.summary.setObjectName("hint")
        self.root.addWidget(self.summary)
        box, _ = _buttons(self, "Tutup", "")
        self.root.addWidget(box)


# ---------------------------------------------------------------- batch tools
class BatchDialog(BaseDialog):
    def __init__(self, parent=None, folder=""):
        super().__init__(parent, "Proses Banyak File", 620)
        self.folder = folder
        self.header("Batch processing",
                    "Tambahkan beberapa PDF, pilih operasi, lalu jalankan sekali.")
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setMinimumHeight(130)
        self.root.addWidget(self.list)
        row = QHBoxLayout()
        for text, slot in (("Tambah file…", self.add_files),
                           ("Hapus", self.remove_selected),
                           ("Kosongkan", self.list.clear)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        self.root.addLayout(row)

        self.chk_compress = QCheckBox("Kompres")
        self.chk_compress.setChecked(True)
        self.chk_numbers = QCheckBox("Nomor halaman")
        self.chk_watermark = QCheckBox("Watermark")
        self.chk_protect = QCheckBox("Password")
        self.chk_flatten = QCheckBox("Flatten anotasi")
        self.chk_png = QCheckBox("Ekspor PNG")
        grid = QHBoxLayout()
        for w in (self.chk_compress, self.chk_numbers, self.chk_watermark,
                  self.chk_protect, self.chk_flatten, self.chk_png):
            grid.addWidget(w)
        grid.addStretch(1)
        self.root.addLayout(grid)

        form = QFormLayout()
        self.wm_edit = QLineEdit("RAHASIA")
        self.pw_edit = QLineEdit()
        self.pw_edit.setEchoMode(QLineEdit.Password)
        self.pw_edit.setPlaceholderText("Password untuk PDF hasil (opsional)")
        self.out_edit = QLineEdit(os.path.join(folder, "PDFStudio-Batch"))
        browse = QPushButton("Pilih…")
        browse.clicked.connect(self._browse_out)
        out_row = QHBoxLayout()
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(browse)
        form.addRow("Teks watermark", self.wm_edit)
        form.addRow("Password", self.pw_edit)
        form.addRow("Folder hasil", out_row)
        self.root.addLayout(form)

        box, _ = _buttons(self, "Jalankan")
        self.root.addWidget(box)

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Pilih PDF", self.folder, "PDF (*.pdf)")
        for p in paths:
            self.list.addItem(p)

    def remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, "Folder hasil", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def files(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def values(self):
        return {
            "files": self.files(),
            "compress": self.chk_compress.isChecked(),
            "numbers": self.chk_numbers.isChecked(),
            "watermark": self.chk_watermark.isChecked(),
            "protect": self.chk_protect.isChecked(),
            "flatten": self.chk_flatten.isChecked(),
            "png": self.chk_png.isChecked(),
            "wm_text": self.wm_edit.text(),
            "password": self.pw_edit.text(),
            "out": self.out_edit.text().strip(),
        }


# ---------------------------------------------------------------- attachments
class AttachmentsDialog(BaseDialog):
    def __init__(self, parent=None, doc=None):
        super().__init__(parent, "Lampiran", 560)
        self.doc = doc
        self.header("Lampiran dokumen",
                    "File yang ditanam di dalam PDF (bukan halaman).")
        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        self.root.addWidget(self.list)
        row = QHBoxLayout()
        for text, slot in (("Tambah…", self.add_file),
                           ("Ekstrak…", self.extract),
                           ("Hapus", self.delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        self.root.addLayout(row)
        self.changed = False
        self.reload()
        box, _ = _buttons(self, "Selesai", "")
        self.root.addWidget(box)

    def reload(self):
        self.list.clear()
        if self.doc is None:
            return
        for a in self.doc.attachments():
            item = QListWidgetItem(f"{a['name']}  ·  {a['size'] / 1024:.1f} KB")
            item.setData(Qt.UserRole, a["name"])
            self.list.addItem(item)

    def add_file(self):
        if self.doc is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Pilih file lampiran")
        if not path:
            return
        try:
            self.doc.add_attachment(path)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal", str(exc))
            return
        self.changed = True
        self.reload()

    def _current(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    @staticmethod
    def _safe_filename(name: str) -> str:
        base = os.path.basename((name or "").replace("\\", "/"))
        base = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", base).strip(" .")
        return base or "lampiran"

    def extract(self):
        name = self._current()
        if not name:
            return
        safe = self._safe_filename(name)
        out, _ = QFileDialog.getSaveFileName(self, "Simpan lampiran",
                                            os.path.join(self.parent()._last_folder, safe))
        if not out:
            return
        try:
            self.doc.extract_attachment(name, out)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal", str(exc))
            return
        QMessageBox.information(self, "Selesai", f"Lampiran disimpan:\n{out}")

    def delete(self):
        name = self._current()
        if not name:
            return
        r = QMessageBox.question(self, "Hapus lampiran", f"Hapus “{name}”?",
                                 QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        if self.doc.delete_attachment(name):
            self.changed = True
            self.reload()


# ---------------------------------------------------------------- insert pages
class InsertPagesDialog(BaseDialog):
    def __init__(self, parent=None, folder="", count=1):
        super().__init__(parent, "Sisip Halaman dari PDF", 540)
        self.header("Sisip halaman", "Ambil halaman dari PDF lain ke dokumen ini.")
        form = QFormLayout()
        form.setSpacing(9)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Pilih file PDF sumber")
        browse = QPushButton("Pilih…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        self.pages_edit = QLineEdit("1")
        self.pages_edit.setPlaceholderText("Contoh: 1-3,7")
        self.pos_spin = QSpinBox()
        self.pos_spin.setRange(1, count + 1)
        self.pos_spin.setValue(count + 1)
        form.addRow("File sumber", row)
        form.addRow("Halaman sumber", self.pages_edit)
        form.addRow("Sisip sebelum halaman", self.pos_spin)
        self.root.addLayout(form)
        self.folder = folder
        box, _ = _buttons(self, "Sisipkan")
        self.root.addWidget(box)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih PDF", self.folder, "PDF (*.pdf)")
        if path:
            self.path_edit.setText(path)

    def values(self):
        return {"path": self.path_edit.text().strip(),
                "pages_text": self.pages_edit.text().strip(),
                "at": self.pos_spin.value() - 1}


# ------------------------------------------------------------------- shortcuts
class ShortcutsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Shortcut Keyboard", 560)
        self.header("Shortcut", "Semua pintasan yang tersedia.")
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setMinimumHeight(420)
        text.setPlainText(
            "FILE\n"
            "  Ctrl+O            Buka PDF\n"
            "  Ctrl+S            Simpan\n"
            "  Ctrl+Shift+S      Simpan sebagai\n"
            "  Ctrl+P            Cetak\n"
            "  Ctrl+Q            Keluar\n\n"
            "NAVIGASI\n"
            "  PgUp / PgDown     Halaman sebelumnya / berikutnya\n"
            "  Ctrl+Home/End     Halaman pertama / terakhir\n"
            "  Ctrl+0            Pas halaman\n"
            "  Ctrl+1            Ukuran asli\n"
            "  Ctrl+2            Lebar halaman\n"
            "  Ctrl+ +/-         Zoom in / out\n"
            "  Ctrl+scroll       Zoom\n"
            "  Scroll            Gulir dokumen (kontinu)\n"
            "  Ctrl+drag         Geser halaman\n"
            "  Ctrl+[ / Ctrl+]   Putar halaman kiri / kanan\n"
            "  Alt+Up / Alt+Down Pindah urutan halaman\n"
            "  F11               Mode baca (sembunyikan panel)\n\n"
            "EDIT\n"
            "  Ctrl+Z / Ctrl+Y    Undo / Redo\n"
            "  Ctrl+A            Pilih semua teks\n"
            "  Ctrl+C            Salin teks\n"
            "  Ctrl+F            Cari\n"
            "  Ctrl+H            Cari & ganti\n"
            "  Ctrl+K            Command palette\n"
            "  Delete            Hapus anotasi terpilih\n"
            "  Esc               Batal / kembali ke Pilih\n"
            "  F1                Daftar shortcut ini\n\n"
            "TEKS DI HALAMAN\n"
            "  Klik teks         Editor langsung terbuka\n"
            "  Ctrl+B / Ctrl+I   Tebal / Miring saat edit\n"
            "  Enter             Simpan\n"
            "  Shift+Enter       Baris baru\n"
            "  Esc               Batal\n\n"
            "TAB DOKUMEN\n"
            "  Ctrl+W            Tutup tab aktif\n"
            "  Ctrl+Tab          Pindah ke tab berikutnya\n\n"
            "ANOTASI\n"
            "  Klik              Pilih anotasi (alat Pilih)\n"
            "  Tarik             Pindahkan anotasi\n"
            "  Tarik handle      Ubah ukuran (8 titik)\n"
            "  Delete            Hapus anotasi terpilih\n")
        self.root.addWidget(text)
        box, _ = _buttons(self, "Tutup", "")
        self.root.addWidget(box)


# ------------------------------------------------------------------------ crop
class CropDialog(_PagesDialog):
    def __init__(self, parent, count: int, current_page: int = 0):
        super().__init__(parent, "Potong Margin (Crop)", count, 480)
        self.current_page = current_page
        form = QFormLayout()
        form.setSpacing(9)

        self.mode_box = QComboBox()
        self.mode_box.addItems([
            "Auto-crop margin putih",
            "Potong manual (mm)",
            "Reset ke ukuran asli",
        ])
        self.mode_box.currentIndexChanged.connect(self._sync_mode)
        form.addRow("Mode", self.mode_box)

        self.pad_spin = QDoubleSpinBox()
        self.pad_spin.setRange(0.0, 60.0)
        self.pad_spin.setValue(5.0)
        self.pad_spin.setSuffix(" mm")
        form.addRow("Sisa tepi (auto)", self.pad_spin)

        def _mm():
            s = QDoubleSpinBox()
            s.setRange(0.0, 150.0)
            s.setValue(10.0)
            s.setSuffix(" mm")
            return s

        self.top_spin = _mm()
        self.bottom_spin = _mm()
        self.left_spin = _mm()
        self.right_spin = _mm()
        form.addRow("Potong atas", self.top_spin)
        form.addRow("Potong bawah", self.bottom_spin)
        form.addRow("Potong kiri", self.left_spin)
        form.addRow("Potong kanan", self.right_spin)

        self.scope_box = QComboBox()
        self.scope_box.addItems([
            f"Halaman ini saja ({current_page + 1})",
            f"Semua halaman (1-{count})",
            "Rentang kustom",
        ])
        self.scope_box.currentIndexChanged.connect(
            lambda i: self.pages_edit.setEnabled(i == 2))
        form.addRow("Terapkan ke", self.scope_box)
        self._add_pages_row(form, "Rentang")
        self.pages_edit.setEnabled(False)
        self.root.addLayout(form)
        self._sync_mode(0)

        box, _ = _buttons(self, "Terapkan")
        self.root.addWidget(box)

    def _sync_mode(self, idx: int):
        self.pad_spin.setEnabled(idx == 0)
        for s in (self.top_spin, self.bottom_spin, self.left_spin, self.right_spin):
            s.setEnabled(idx == 1)

    def values(self) -> dict:
        mm_to_pt = 72.0 / 25.4
        mode = ("auto", "manual", "reset")[self.mode_box.currentIndex()]
        scope = self.scope_box.currentIndex()
        if scope == 0:
            pages = [self.current_page]
        elif scope == 1:
            pages = list(range(self.count))
        else:
            pages = self._pages()
        return {
            "mode": mode,
            "pages": pages,
            "margin": self.pad_spin.value() * mm_to_pt,
            "top": self.top_spin.value() * mm_to_pt,
            "bottom": self.bottom_spin.value() * mm_to_pt,
            "left": self.left_spin.value() * mm_to_pt,
            "right": self.right_spin.value() * mm_to_pt,
        }


# ------------------------------------------------------------ embedded images
class PageImagesDialog(BaseDialog):
    def __init__(self, parent, doc, pno: int, folder: str = ""):
        super().__init__(parent, f"Gambar di Halaman {pno + 1}", 540)
        self.doc = doc
        self.pno = pno
        self._folder = folder
        self.changed = False
        self.header(f"Kelola gambar halaman {pno + 1}",
                    "Pilih gambar yang tertanam di halaman ini untuk diganti, diekstrak, atau dihapus.")
        self.list = QListWidget()
        self.list.setMinimumHeight(210)
        self.root.addWidget(self.list)

        row = QHBoxLayout()
        btn_replace = QPushButton("Ganti Gambar…")
        btn_replace.clicked.connect(self._replace)
        btn_extract = QPushButton("Ekstrak…")
        btn_extract.clicked.connect(self._extract)
        btn_delete = QPushButton("Hapus")
        btn_delete.setObjectName("danger")
        btn_delete.clicked.connect(self._delete)
        row.addWidget(btn_replace)
        row.addWidget(btn_extract)
        row.addWidget(btn_delete)
        row.addStretch(1)
        self.root.addLayout(row)

        box, _ = _buttons(self, "Tutup", "")
        self.root.addWidget(box)
        self._reload()

    def _reload(self):
        self.list.clear()
        imgs = self.doc.page_images(self.pno)
        for idx, info in enumerate(imgs, 1):
            kb = info["size"] / 1024.0
            label = (f"#{idx}  {info['width']}×{info['height']} px · "
                     f"{info['ext'].upper()} · {kb:.1f} KB (xref {info['xref']})")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, info)
            self.list.addItem(item)
        if not imgs:
            empty = QListWidgetItem("(Tidak ada gambar tertanam di halaman ini)")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)

    def _selected(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _replace(self):
        info = self._selected()
        if not info:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih gambar pengganti", self._folder,
            "Gambar (*.png *.jpg *.jpeg *.webp *.bmp);;Semua file (*)")
        if not path:
            return
        self.doc.snapshot("Ganti gambar", self.pno)
        if self.doc.replace_page_image(self.pno, info["xref"], path):
            self.changed = True
            self._reload()
        else:
            QMessageBox.warning(self, "Gagal", "Gambar tidak bisa diganti.")

    def _extract(self):
        info = self._selected()
        if not info:
            return
        ext = info.get("ext") or "png"
        out, _ = QFileDialog.getSaveFileName(
            self, "Simpan gambar",
            os.path.join(self._folder, f"hal{self.pno + 1}_img{info['xref']}.{ext}"),
            f"Gambar (*.{ext} *.png *.jpg)")
        if not out:
            return
        try:
            self.doc.extract_page_image(info["xref"], out)
            QMessageBox.information(self, "Selesai", f"Gambar diekstrak ke:\n{out}")
        except Exception as exc:
            QMessageBox.critical(self, "Gagal", str(exc))

    def _delete(self):
        info = self._selected()
        if not info:
            return
        r = QMessageBox.question(
            self, "Hapus gambar",
            f"Hapus gambar {info['width']}×{info['height']} px dari halaman {self.pno + 1}?",
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.doc.snapshot("Hapus gambar", self.pno)
        if self.doc.delete_page_image(self.pno, info["xref"]):
            self.changed = True
            self._reload()
        else:
            QMessageBox.warning(self, "Gagal", "Gambar tidak bisa dihapus.")


# ----------------------------------------------------------- form field builder
class AddFormFieldDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Tambah Field Formulir", 440)
        self.header("Buat field formulir baru",
                    "Pilih jenis field, lalu tarik kotak di halaman untuk menempatkannya.")
        form = QFormLayout()
        form.setSpacing(9)
        self.kind_box = QComboBox()
        self.kind_box.addItem("Kotak Teks (Text)", "text")
        self.kind_box.addItem("Centang (Checkbox)", "checkbox")
        self.kind_box.addItem("Pilihan (Dropdown)", "combobox")
        self.kind_box.currentIndexChanged.connect(self._sync_kind)
        form.addRow("Jenis field", self.kind_box)

        self.name_edit = QLineEdit("field_baru")
        form.addRow("Nama field", self.name_edit)

        self.default_edit = QLineEdit()
        self.default_edit.setPlaceholderText("Nilai awal (opsional)")
        form.addRow("Nilai awal", self.default_edit)

        self.options_edit = QLineEdit("Pilihan 1, Pilihan 2, Pilihan 3")
        self.options_edit.setPlaceholderText("Pisahkan dengan koma")
        form.addRow("Opsi dropdown", self.options_edit)

        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(6.0, 28.0)
        self.size_spin.setValue(11.0)
        self.size_spin.setSuffix(" pt")
        form.addRow("Ukuran font", self.size_spin)
        self.root.addLayout(form)
        self._sync_kind(0)

        box, _ = _buttons(self, "Tempatkan di Halaman")
        self.root.addWidget(box)

    def _sync_kind(self, _idx: int):
        k = self.kind_box.currentData()
        self.options_edit.setEnabled(k == "combobox")
        self.default_edit.setEnabled(k != "checkbox")

    def values(self) -> dict:
        opts = [o.strip() for o in self.options_edit.text().split(",") if o.strip()]
        return {
            "kind": self.kind_box.currentData(),
            "name": self.name_edit.text().strip() or "field",
            "default": self.default_edit.text(),
            "options": opts,
            "fontsize": self.size_spin.value(),
        }

