"""Modal dialogs: text input, signature pad, security, metadata, signing."""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QIcon, QFont)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget, QGroupBox, QDoubleSpinBox,
                               QSlider, QListWidget, QListWidgetItem)

from ui.theme import icon, INK, ACCENT, MUTED

FONTS = ["Helvetica", "Times", "Courier"]


def _buttons(dialog, ok_text="Simpan", cancel_text="Batal"):
    box = QDialogButtonBox()
    ok = box.addButton(ok_text, QDialogButtonBox.AcceptRole)
    ok.setObjectName("primary")
    cancel = box.addButton(cancel_text, QDialogButtonBox.RejectRole)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box, ok


class BaseDialog(QDialog):
    def __init__(self, parent=None, title="", width=440):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setModal(True)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(18, 16, 18, 16)
        self.root.setSpacing(12)

    def header(self, text, sub=""):
        lab = QLabel(text)
        lab.setObjectName("title")
        self.root.addWidget(lab)
        if sub:
            s = QLabel(sub)
            s.setObjectName("hint")
            s.setWordWrap(True)
            self.root.addWidget(s)


# --------------------------------------------------------------------- text
class TextDialog(BaseDialog):
    """Text box / edit-text dialog with font, size and colour."""

    def __init__(self, parent=None, title="Tambah Teks", text="",
                 fontsize=12.0, font="Helvetica", color="#000000",
                 bold=False, italic=False, hint="", multi=True):
        super().__init__(parent, title, 520)
        self.header(title, hint)

        self.editor = QPlainTextEdit(text)
        self.editor.setMinimumHeight(110)
        if not multi:
            self.editor.setMaximumHeight(64)
        self.root.addWidget(self.editor)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.font_box = QComboBox()
        self.font_box.addItems(FONTS)
        self.font_box.setCurrentText(font if font in FONTS else "Helvetica")
        self.size_box = QDoubleSpinBox()
        self.size_box.setRange(4, 200)
        self.size_box.setDecimals(1)
        self.size_box.setValue(float(fontsize))
        self.size_box.setSuffix(" pt")
        self.size_box.setFixedWidth(90)
        self.bold_btn = QPushButton("B")
        self.bold_btn.setCheckable(True)
        self.bold_btn.setChecked(bold)
        self.bold_btn.setFixedWidth(34)
        self.bold_btn.setStyleSheet("font-weight:700;")
        self.italic_btn = QPushButton("I")
        self.italic_btn.setCheckable(True)
        self.italic_btn.setChecked(italic)
        self.italic_btn.setFixedWidth(34)
        self.italic_btn.setStyleSheet("font-style:italic; font-family:Georgia;")
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(42, 30)
        self.color_btn.setToolTip("Warna teks")
        self._color = QColor(color)
        self._paint_color_btn()
        self.color_btn.clicked.connect(self._pick_color)

        row.addWidget(QLabel("Font"))
        row.addWidget(self.font_box, 1)
        row.addWidget(self.size_box)
        row.addWidget(self.bold_btn)
        row.addWidget(self.italic_btn)
        row.addWidget(self.color_btn)
        self.root.addLayout(row)

        box, _ = _buttons(self)
        self.root.addWidget(box)
        self.editor.setFocus()
        self.editor.selectAll()

    def _paint_color_btn(self):
        self.color_btn.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid #4a4f59; border-radius:6px;")

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Warna Teks")
        if c.isValid():
            self._color = c
            self._paint_color_btn()

    def values(self):
        return {
            "text": self.editor.toPlainText(),
            "font": self.font_box.currentText(),
            "fontsize": self.size_box.value(),
            "color": (self._color.redF(), self._color.greenF(), self._color.blueF()),
            "bold": self.bold_btn.isChecked(),
            "italic": self.italic_btn.isChecked(),
        }


class NoteDialog(TextDialog):
    def __init__(self, parent=None, text=""):
        super().__init__(parent, "Catatan Tempel", text, 11, "Helvetica",
                         "#B8860B", hint="Catatan akan tampil sebagai ikon kuning di halaman.",
                         multi=False)
        self.setWindowTitle("Catatan Tempel")


# ---------------------------------------------------------------- signature
class SignaturePad(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(460, 190)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background:#fbfbfd; border:1px solid #3a3e46; border-radius:8px;")
        self.strokes: list[list[QPointF]] = []
        self.pen_color = QColor("#111827")
        self.pen_width = 3.0
        self._drawing = False

    def clear(self):
        self.strokes = []
        self.update()

    def undo(self):
        if self.strokes:
            self.strokes.pop()
            self.update()

    def is_empty(self):
        return not self.strokes

    def mousePressEvent(self, ev):
        self._drawing = True
        self.strokes.append([ev.position()])
        self.update()

    def mouseMoveEvent(self, ev):
        if self._drawing and self.strokes:
            self.strokes[-1].append(ev.position())
            self.update()

    def mouseReleaseEvent(self, ev):
        self._drawing = False

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self.pen_color, self.pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        for s in self.strokes:
            if len(s) < 2:
                if s:
                    p.drawPoint(s[0])
                continue
            path = QPainterPath(s[0])
            for pt in s[1:]:
                path.lineTo(pt)
            p.drawPath(path)
        if self.is_empty():
            p.setPen(QColor("#b9bec7"))
            f = QFont("Segoe UI", 12)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "Tanda tangan di sini  ✍")
        p.end()

    def image(self, margin=10) -> QImage:
        if self.is_empty():
            return QImage()
        xs = [pt.x() for s in self.strokes for pt in s]
        ys = [pt.y() for s in self.strokes for pt in s]
        x0, y0 = min(xs) - margin, min(ys) - margin
        x1, y1 = max(xs) + margin, max(ys) + margin
        w = int(max(40, x1 - x0))
        h = int(max(24, y1 - y0))
        img = QImage(w * 3, h * 3, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(3, 3)
        p.translate(-x0, -y0)
        pen = QPen(self.pen_color, self.pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        for s in self.strokes:
            if len(s) < 2:
                if s:
                    p.drawPoint(s[0])
                continue
            path = QPainterPath(s[0])
            for pt in s[1:]:
                path.lineTo(pt)
            p.drawPath(path)
        p.end()
        return img


class SignatureDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Tanda Tangan", 540)
        self.header("Tanda tangan",
                    "Pilih tanda tangan tersimpan, gambar baru pakai mouse/trackpad, "
                    "atau impor PNG berlatar transparan.")
        from core import signatures as sigstore
        self._sigstore = sigstore
        self._saved_path: str | None = None
        self._imported: QImage | None = None

        saved_row = QHBoxLayout()
        self.saved_box = QComboBox()
        self.saved_box.setMinimumWidth(260)
        self.saved_box.currentIndexChanged.connect(self._pick_saved)
        self.btn_del_saved = QPushButton("Hapus Tersimpan")
        self.btn_del_saved.clicked.connect(self._delete_saved)
        saved_row.addWidget(QLabel("Tersimpan"))
        saved_row.addWidget(self.saved_box, 1)
        saved_row.addWidget(self.btn_del_saved)
        self.root.addLayout(saved_row)

        self.pad = SignaturePad()
        self.root.addWidget(self.pad)

        row = QHBoxLayout()
        clear = QPushButton("Hapus")
        clear.clicked.connect(self._clear_all)
        undo = QPushButton("Undo")
        undo.clicked.connect(self.pad.undo)
        imp = QPushButton("Impor Gambar…")
        imp.clicked.connect(self._import)
        self.width_slider = QSlider(Qt.Horizontal)
        self.width_slider.setRange(2, 10)
        self.width_slider.setValue(3)
        self.width_slider.setFixedWidth(110)
        self.width_slider.valueChanged.connect(lambda v: setattr(self.pad, "pen_width", float(v)))
        row.addWidget(clear)
        row.addWidget(undo)
        row.addWidget(imp)
        row.addStretch(1)
        row.addWidget(QLabel("Tebal"))
        row.addWidget(self.width_slider)
        self.root.addLayout(row)

        save_row = QHBoxLayout()
        self.save_check = QCheckBox("Simpan ke pustaka:")
        self.save_check.setChecked(True)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nama tanda tangan (opsional, mis. Paraf / Resmi)")
        save_row.addWidget(self.save_check)
        save_row.addWidget(self.name_edit, 1)
        self.root.addLayout(save_row)

        self._reload_saved()

        box, _ = _buttons(self, "Pakai Tanda Tangan")
        self.root.addWidget(box)

    def _reload_saved(self):
        self.saved_box.blockSignals(True)
        self.saved_box.clear()
        self.saved_box.addItem("— Gambar / impor baru —", None)
        entries = self._sigstore.list_signatures()
        for e in entries:
            self.saved_box.addItem(e["name"], e["path"])
        self.saved_box.blockSignals(False)
        self.btn_del_saved.setEnabled(bool(entries))

    def _pick_saved(self, idx: int):
        path = self.saved_box.itemData(idx)
        self._saved_path = path
        if path:
            img = QImage(path)
            if not img.isNull():
                self.pad.clear()
                self._imported = img
                self.save_check.setChecked(False)
                return
        self._saved_path = None

    def _delete_saved(self):
        path = self.saved_box.currentData()
        if not path:
            return
        self._sigstore.delete_signature(path)
        self._saved_path = None
        self._imported = None
        self._reload_saved()

    def _clear_all(self):
        self.pad.clear()
        self._imported = None
        self._saved_path = None
        self.saved_box.setCurrentIndex(0)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih gambar tanda tangan", "",
                                              "Gambar (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Gagal", "Gambar tidak bisa dibaca.")
            return
        self.pad.clear()
        self.pad.strokes = []
        self._imported = img
        self._saved_path = None
        self.saved_box.setCurrentIndex(0)
        self.pad.update()

    def accept(self):
        if self._imported is not None and self.pad.is_empty():
            if self.save_check.isChecked() and not self._saved_path:
                try:
                    self._saved_path = self._sigstore.save_signature_image(
                        self._imported, self.name_edit.text())
                except Exception:
                    pass
            super().accept()
            return
        if self.pad.is_empty():
            QMessageBox.information(self, "Kosong", "Gambar tanda tangan dulu, pilih yang tersimpan, atau impor gambar.")
            return
        if self.save_check.isChecked():
            try:
                self._saved_path = self._sigstore.save_signature_image(
                    self.pad.image(), self.name_edit.text())
            except Exception:
                pass
        super().accept()

    def result_image(self) -> QImage:
        if self._imported is not None and self.pad.is_empty():
            return self._imported
        return self.pad.image()

    def result_path(self) -> str | None:
        return self._saved_path


# ----------------------------------------------------------------- security
class ProtectDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Proteksi Password", 460)
        self.header("Kunci dokumen dengan password",
                    "Password user diminta saat file dibuka. Password owner mengunci izin "
                    "(kosongkan untuk memakai password user).")
        form = QFormLayout()
        form.setSpacing(10)
        self.user_pw = QLineEdit()
        self.user_pw.setEchoMode(QLineEdit.Password)
        self.user_pw2 = QLineEdit()
        self.user_pw2.setEchoMode(QLineEdit.Password)
        self.owner_pw = QLineEdit()
        self.owner_pw.setEchoMode(QLineEdit.Password)
        form.addRow("Password buka", self.user_pw)
        form.addRow("Ulangi password", self.user_pw2)
        form.addRow("Password owner", self.owner_pw)
        self.root.addLayout(form)

        self.p_print = QCheckBox("Izinkan mencetak")
        self.p_copy = QCheckBox("Izinkan menyalin teks")
        self.p_mod = QCheckBox("Izinkan mengubah / anotasi")
        self.p_print.setChecked(True)
        self.p_copy.setChecked(True)
        for w in (self.p_print, self.p_copy, self.p_mod):
            self.root.addWidget(w)

        box, _ = _buttons(self, "Terapkan")
        self.root.addWidget(box)

    def accept(self):
        if len(self.user_pw.text()) < 4:
            QMessageBox.warning(self, "Password lemah", "Minimal 4 karakter.")
            return
        if self.user_pw.text() != self.user_pw2.text():
            QMessageBox.warning(self, "Beda", "Konfirmasi password tidak sama.")
            return
        super().accept()

    def values(self):
        return {
            "user_pw": self.user_pw.text(),
            "owner_pw": self.owner_pw.text() or self.user_pw.text(),
            "allow_print": self.p_print.isChecked(),
            "allow_copy": self.p_copy.isChecked(),
            "allow_modify": self.p_mod.isChecked(),
        }


class PasswordPrompt(BaseDialog):
    def __init__(self, parent=None, filename=""):
        super().__init__(parent, "Dokumen Terkunci", 420)
        self.header("PDF terkunci password", f"Masukkan password untuk membuka:\n{filename}")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Password…")
        self.root.addWidget(self.pw)
        box, _ = _buttons(self, "Buka")
        self.root.addWidget(box)
        self.pw.setFocus()


# ----------------------------------------------------------------- metadata
class MetadataDialog(BaseDialog):
    def __init__(self, parent=None, meta=None):
        super().__init__(parent, "Properti Dokumen", 480)
        self.header("Properti dokumen")
        meta = meta or {}
        form = QFormLayout()
        form.setSpacing(10)
        self.fields = {}
        for key, label in (("title", "Judul"), ("author", "Penulis"),
                           ("subject", "Subjek"), ("keywords", "Kata kunci")):
            e = QLineEdit(meta.get(key) or "")
            self.fields[key] = e
            form.addRow(label, e)
        self.root.addLayout(form)
        box, _ = _buttons(self)
        self.root.addWidget(box)

    def values(self):
        return {k: v.text() for k, v in self.fields.items()}


class PageRangeDialog(BaseDialog):
    def __init__(self, parent=None, max_page=1, title="Ekspor Halaman",
                 label="Halaman yang diekspor", default=""):
        super().__init__(parent, title, 420)
        self.header(title, f"Dokumen ini punya {max_page} halaman. "
                            "Contoh: 1-3,5,8-10")
        self.edit = QLineEdit(default or f"1-{max_page}")
        self.edit.setPlaceholderText("1-3,5")
        self.root.addWidget(QLabel(label))
        self.root.addWidget(self.edit)
        box, _ = _buttons(self, "Lanjut")
        self.root.addWidget(box)

    def pages(self, max_page: int) -> list[int]:
        out = []
        for part in self.edit.text().split(","):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
            if m:
                a, b = sorted((int(m.group(1)), int(m.group(2))))
                out.extend(range(a - 1, b))
            elif part.isdigit():
                out.append(int(part) - 1)
        return sorted(set(p for p in out if 0 <= p < max_page))

    def accept(self):
        if not self.pages(1_000_000):
            QMessageBox.warning(self, "Kosong", "Masukkan nomor halaman yang valid.")
            return
        super().accept()


# ------------------------------------------------------------------ signing
class DigitalSignDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent, "Tanda Tangan Digital (PAdES)", 520)
        self.header("Tanda tangan digital PAdES",
                    "Butuh file sertifikat .pfx / .p12 beserta password. "
                    "Tanda tangan ini bisa diverifikasi di Adobe Reader.")
        form = QFormLayout()
        form.setSpacing(10)
        self.pfx = QLineEdit()
        self.pfx.setPlaceholderText("Pilih file .pfx / .p12")
        browse = QPushButton("Pilih…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.pfx, 1)
        row.addWidget(browse)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.reason = QLineEdit("Disetujui dan ditandatangani")
        self.location = QLineEdit("")
        form.addRow("Sertifikat", row)
        form.addRow("Password", self.pw)
        form.addRow("Alasan", self.reason)
        form.addRow("Lokasi", self.location)
        self.root.addLayout(form)

        gen = QPushButton("Belum punya sertifikat? Buat self-signed…")
        gen.clicked.connect(self._generate)
        self.root.addWidget(gen)

        box, _ = _buttons(self, "Tanda Tangani")
        self.root.addWidget(box)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih sertifikat", "",
                                              "Sertifikat (*.pfx *.p12);;Semua file (*)")
        if path:
            self.pfx.setText(path)

    def _generate(self):
        name, ok = TextPrompt.get(self, "Nama sertifikat", "Nama (untuk sertifikat)")
        if not ok:
            return
        pw, ok = TextPrompt.get(self, "Password sertifikat", "Password .pfx baru", password=True)
        if not ok:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Simpan sertifikat", f"{name}.pfx",
                                              "PKCS#12 (*.pfx)")
        if not path:
            return
        try:
            from core.pdfdoc import make_self_signed_pfx
            make_self_signed_pfx(path, name, pw)
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "Gagal", f"Tidak bisa membuat sertifikat:\n{exc}")
            return
        self.pfx.setText(path)
        self.pw.setText(pw)
        QMessageBox.information(
            self, "Sertifikat dibuat",
            "Sertifikat self-signed dibuat.\n\nCatatan: ini untuk keperluan pribadi/uji coba — "
            "bukan tanda tangan tersertifikasi yang diakui secara hukum.")

    def accept(self):
        if not self.pfx.text() or not os.path.exists(self.pfx.text()):
            QMessageBox.warning(self, "Sertifikat", "Pilih file sertifikat .pfx / .p12 dulu.")
            return
        super().accept()

    def values(self):
        return {"pfx": self.pfx.text(), "password": self.pw.text(),
                "reason": self.reason.text(), "location": self.location.text()}


class TextPrompt(BaseDialog):
    def __init__(self, parent=None, title="", label="", text="", password=False):
        super().__init__(parent, title, 400)
        self.header(title)
        self.edit = QLineEdit(text)
        if password:
            self.edit.setEchoMode(QLineEdit.Password)
        self.root.addWidget(QLabel(label))
        self.root.addWidget(self.edit)
        box, _ = _buttons(self, "OK")
        self.root.addWidget(box)
        self.edit.setFocus()
        self.edit.selectAll()

    @staticmethod
    def get(parent, title, label, text="", password=False):
        d = TextPrompt(parent, title, label, text, password)
        if d.exec() == QDialog.Accepted:
            return d.edit.text(), True
        return "", False


class FormFieldDialog(BaseDialog):
    def __init__(self, parent=None, widget_info=None):
        info = widget_info or {}
        super().__init__(parent, "Isi Formulir", 440)
        self.info = info
        typ = info.get("type", "Text")
        self.header(info.get("label") or info.get("name") or "Field",
                    f"Tipe field: {typ}")
        self.editor = None
        self.combo = None
        self.check = None
        value = info.get("value")
        if typ in ("CheckBox", "RadioButton"):
            self.check = QCheckBox("Centang")
            self.check.setChecked(bool(value))
            self.root.addWidget(self.check)
        elif info.get("choices"):
            self.combo = QComboBox()
            self.combo.addItems(info["choices"])
            if value in info["choices"]:
                self.combo.setCurrentText(str(value))
            self.root.addWidget(self.combo)
        else:
            self.editor = QPlainTextEdit("" if value is None else str(value))
            self.editor.setMaximumHeight(90)
            self.root.addWidget(self.editor)
        box, _ = _buttons(self, "Simpan")
        self.root.addWidget(box)

    def value(self):
        if self.check is not None:
            return self.check.isChecked()
        if self.combo is not None:
            return self.combo.currentText()
        return self.editor.toPlainText() if self.editor else ""


class AboutDialog(BaseDialog):
    def __init__(self, parent=None, version="1.2"):
        super().__init__(parent, "Tentang PDF Studio", 560)
        self.header("PDF Studio", f"Versi {version} · PDF editor desktop")
        text = QLabel(
            "Dibuat dengan PySide6 (Qt) + PyMuPDF + pyHanko.\n\n"
            "<b>Alat</b><br>"
            "• <b>Pilih</b> — seleksi teks, klik anotasi untuk pindah/ubah ukuran<br>"
            "• <b>Sorot / garis bawah / coret / squiggly</b> — tarik di atas teks<br>"
            "• <b>Teks</b> — klik-tarik untuk menulis teks baru<br>"
            "• <b>Edit teks</b> — klik langsung di teks, ketik, Enter simpan<br>"
            "• <b>Tinta</b> — gambar bebas<br>"
            "• <b>Kotak / elips / garis / panah</b> — bentuk vektor<br>"
            "• <b>Callout</b> — kotak komentar dengan garis penunjuk<br>"
            "• <b>Stempel</b> — cap teks berwarna (DRAFT, LULUS, dll.)<br>"
            "• <b>Gambar</b> — sisipkan foto/logo<br>"
            "• <b>Tanda tangan</b> — gambar tanda tangan lalu tempel<br>"
            "• <b>Form</b> — isi field AcroForm (teks, checkbox, pilihan)<br>"
            "• <b>TTD digital</b> — tanda tangan PAdES dengan sertifikat .pfx<br><br>"
            "<b>Dokumen</b><br>"
            "Watermark, nomor halaman, header/footer, outline/bookmark, lampiran,<br>"
            "bandingkan dua PDF, sisip/gandakan halaman, tautan, sanitasi metadata,<br>"
            "kompres, proteksi AES-256, ekspor PNG, dan flatten anotasi.<br><br>"
            "<b>Tampilan</b><br>"
            "Panel Properti / Komentar / Outline, tool rail kiri, command palette<br>"
            "(Ctrl+K), mode baca (F11), tema gelap & terang.<br>"
            "Gulir kontinu antar halaman, render bertahap, posisi baca diingat<br>"
            "per file, autosave + pemulihan setelah aplikasi mati mendadak.<br>"
            "OCR halaman scan (butuh Tesseract terpasang).<br><br>"
            "<b>Shortcut</b><br>"
            "Ctrl+O buka · Ctrl+S simpan · Ctrl+Shift+S simpan sebagai<br>"
            "Ctrl+Z undo · Ctrl+Y redo · Ctrl+F cari · Ctrl+H cari &amp; ganti<br>"
            "Ctrl+K command palette · F11 mode baca<br>"
            "Ctrl++ / Ctrl+- zoom · Ctrl+0 pas halaman · Ctrl+1 ukuran asli<br>"
            "PgUp/PgDn halaman · Space+drag untuk menggeser"
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        text.setObjectName("hint")
        self.root.addWidget(text)
        box, _ = _buttons(self, "Tutup", "Tutup")
        self.root.addWidget(box)



class RecoveryDialog(BaseDialog):
    """Offer autosaved snapshots after an unexpected shutdown."""

    def __init__(self, parent=None, entries=None):
        super().__init__(parent, "Pulihkan dokumen", 560)
        self._entries = list(entries or [])
        self.header("Ada dokumen yang belum tersimpan",
                    "PDF Studio menemukan snapshot otomatis. Pilih yang mau "
                    "dipulihkan, atau abaikan untuk memulai dari kosong.")
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        import datetime
        for meta in self._entries:
            when = datetime.datetime.fromtimestamp(meta.get("saved_at", 0))
            label = (f"{meta.get('name') or 'Tanpa Nama'}  �  "
                     f"halaman {int(meta.get('page', 0)) + 1}  �  "
                     f"{when.strftime('%d/%m %H:%M')}")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, meta)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.setMinimumHeight(140)
        self.root.addWidget(self.list)
        box = QDialogButtonBox()
        self.btn_restore = box.addButton("Pulihkan", QDialogButtonBox.AcceptRole)
        self.btn_restore.setObjectName("primary")
        self.btn_skip = box.addButton("Abaikan", QDialogButtonBox.RejectRole)
        self.btn_delete = box.addButton("Hapus snapshot",
                                        QDialogButtonBox.DestructiveRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self._delete = False
        self.btn_delete.clicked.connect(self._mark_delete)
        self.root.addWidget(box)

    def _mark_delete(self):
        self._delete = True
        self.reject()

    def selected_entries(self):
        picked = self.list.selectedItems()
        if not picked:
            picked = [self.list.item(i) for i in range(self.list.count())]
        return [item.data(Qt.UserRole) for item in picked]

    def delete_requested(self):
        return self._delete


class SignatureVerifyDialog(BaseDialog):
    """Display verification details for all digital signatures in a PDF."""

    def __init__(self, parent, entries: list[dict]):
        super().__init__(parent, "Verifikasi Tanda Tangan Digital", 560)
        self.header(
            f"Tanda tangan digital ({len(entries)})",
            "Hasil pemeriksaan integritas kriptografis dan detail sertifikat pada dokumen ini.")
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setMinimumHeight(240)
        blocks = []
        for idx, e in enumerate(entries, 1):
            status = ("VALID & TERPERCAYA" if (e.get("intact") and e.get("valid") and e.get("trusted"))
                      else "INTEGRITAS VALID (SELF-SIGNED / PENERBIT TIDAK DIKENAL)"
                      if (e.get("intact") and e.get("valid"))
                      else "PERINGATAN / TIDAK VALID")
            lines = [
                f"#{idx}  Field: {e.get('field_name') or 'Signature'}",
                f"Status      : {status}",
                f"Ringkasan   : {e.get('summary') or '-'}",
                f"Penandatangan: {e.get('signer') or '-'}",
                f"Penerbit    : {e.get('issuer') or '-'}",
                f"Waktu       : {e.get('signing_time') or '-'}",
                f"Alasan      : {e.get('reason') or '-'}",
                f"Lokasi      : {e.get('location') or '-'}",
            ]
            blocks.append("\n".join(lines))
        view.setPlainText("\n\n" + ("\n" + "-" * 56 + "\n\n").join(blocks) if blocks else "Tidak ada tanda tangan digital.")
        self.root.addWidget(view)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        self.root.addWidget(box)

