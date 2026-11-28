"""Main window wiring the canvas, tools, menus and document operations."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

import pymupdf as fitz

from PySide6.QtCore import QFileSystemWatcher, QRectF, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices,
                           QGuiApplication, QIcon, QImage, QKeySequence,
                           QPainter, QPixmap, QShortcut)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDockWidget, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QProgressDialog,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QStackedWidget, QStatusBar, QTabBar, QTabWidget,
                               QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ui import theme
from ui.dialogs import (AboutDialog, DigitalSignDialog, FormFieldDialog,
                      MetadataDialog, NoteDialog, PageRangeDialog,
                      PasswordPrompt, ProtectDialog, RecoveryDialog,
                      SignatureDialog, SignatureVerifyDialog, TextDialog,
                      TextPrompt)
from ui.palette import CommandPalette
from ui.all_tools import AllToolsPanel
from ui.organize import OrganizePagesView
from ui.theme import icon
from ui.thumbnails import ThumbnailPanel
from ui.tools_dialogs import (AddFormFieldDialog, AnnotPropsDialog,
                             AttachmentsDialog, BatchDialog, CompareDialog,
                             CropDialog, HeaderFooterDialog, InsertPagesDialog,
                             PageImagesDialog, PageNumberDialog,
                             SearchReplaceDialog, ShortcutsDialog, StampDialog,
                             WatermarkDialog, parse_pages)
from ui.viewer import PageView
from ui.welcome import WelcomePanel
from ui.workers import run_in_background
from core.exporter import export_docx as _export_docx, export_text as _export_text
from core.pdfdoc import PdfDoc, create_pdf_from_images, strip_password
from core import recovery
from core import signatures as sigstore

APP_NAME = "PDF Studio"
VERSION = "1.2"

TOOL_HINTS = {
    "select": "Tarik untuk memilih teks · Ctrl+C menyalin · klik anotasi untuk memilih · Ctrl+drag menggeser halaman",
    "highlight": "Tarik di atas teks untuk menyorot",
    "underline": "Tarik di atas teks untuk memberi garis bawah",
    "strikeout": "Tarik di atas teks untuk mencoret",
    "note": "Klik di halaman untuk menempel catatan",
    "text": "Klik-tarik untuk membuat kotak teks baru",
    "edit_text": "Klik langsung di teks untuk mengubahnya di halaman",
    "ink": "Gambar bebas dengan mouse",
    "rect": "Tarik untuk menggambar kotak",
    "ellipse": "Tarik untuk menggambar elips",
    "line": "Tarik untuk menggambar garis lurus",
    "arrow": "Tarik untuk menggambar panah",
    "callout": "Tarik kotak komentar, lalu isi teksnya",
    "stamp": "Klik atau tarik kotak untuk menempel stempel",
    "image": "Tarik kotak untuk menempatkan gambar",
    "signature": "Tarik kotak untuk menempatkan tanda tangan",
    "form": "Klik field formulir untuk mengisinya",
    "add_form": "Tarik kotak di halaman untuk menempatkan field formulir baru",
    "cert": "Tarik kotak untuk menempatkan tanda tangan digital",
    "redact": "Tarik kotak untuk menghapus isi secara permanen (redaksi)",
    "hand": "Tarik untuk menggeser halaman",
}

KIND_LABELS = {
    "freetext": "Teks bebas", "rect": "Kotak", "ellipse": "Elips",
    "line": "Garis", "arrow": "Panah", "ink": "Tinta", "note": "Catatan",
    "highlight": "Sorot", "underline": "Garis bawah", "strikeout": "Coret",
    "squiggly": "Garis bergelombang", "polygon": "Poligon",
    "polyline": "Garis lipat", "stamp": "Stempel",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get((kind or "").lower(), (kind or "Anotasi").title())


@dataclass
class TabState:
    doc: PdfDoc
    pno: int = 0
    dirty: bool = False
    zoom: float = 1.0
    zoom_mode: str = "fitp"
    scroll_x: int | None = None
    scroll_y: int | None = None
    search_query: str = ""
    search_hits: list = field(default_factory=list)
    search_idx: int = -1
    sig_entries: list = field(default_factory=list)
    sig_dismissed: bool = False
    externally_modified: bool = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = PdfDoc()
        self._tabs: list[TabState] = []
        self._closed_tabs: list[str] = []
        self._active_tab: int = -1
        self._docks_initialized = False
        self._icon_actions: list[tuple[QAction, str]] = []
        self._watcher = QFileSystemWatcher(self)
        self._suppress_watch = False
        self.pno = 0
        self.dirty = False
        self._zoom_mode = "fitp"
        self._pending_sign = None
        self._pending_image = None
        self._pending_form_field = None
        self._has_rendered = False
        self._sig_image_path = None
        self._search_hits: list[tuple[int, tuple]] = []
        self._search_idx = -1
        self._read_mode = False
        self._organize_mode = False
        self._restoring_view = False
        self._settings = QSettings("PDFStudio", "PDFStudio")
        self.colors = {
            "markup": QColor("#ffd400"),
            "stroke": QColor("#e5484d"),
            "text": QColor("#111111"),
            "note": QColor("#ffd400"),
        }
        self.recent = [p for p in (self._settings.value("recent", []) or []) if isinstance(p, str)]

        saved_theme = self._settings.value("theme", "dark")
        theme.set_current_theme(saved_theme if isinstance(saved_theme, str) else "dark")

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1440, 900)
        self.setWindowIcon(QIcon(theme.app_pixmap(128)))

        self._build_center()
        self._build_actions()
        self._build_docks()
        self._build_menus()
        self._build_toolbars()
        self._build_status()
        self._wire()

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(45_000)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        self._autosave_timer.start()
        QTimer.singleShot(500, self._check_recovery)

        geo = self._settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        self._apply_theme()
        self.welcome.set_recent(self.recent)
        self._set_tool("select")
        self._set_zoom(1.0, "fitp")
        self._update_title()
        self._update_actions()
        self.tool_rail.hide()
        self.dock_tools.show()
        self.dock_thumbs.hide()
        self.dock_props.hide()
        self.dock_comments.hide()
        self.dock_outline.hide()
        self.dock_search.hide()
        self.dock_layers.hide()
        self.dock_fields.hide()

        last = self._settings.value("last_folder", "")
        self._last_folder = last if isinstance(last, str) and os.path.isdir(last) else ""

    # ------------------------------------------------------------------- ui
    def _build_center(self):
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setFrameShape(QFrame.NoFrame)

        # ---- document tab strip
        self.doc_tabs_bar = QWidget()
        self.doc_tabs_bar.setObjectName("docTabBar")
        tlay = QHBoxLayout(self.doc_tabs_bar)
        tlay.setContentsMargins(6, 4, 6, 0)
        tlay.setSpacing(4)
        self.doc_tabs = QTabBar()
        self.doc_tabs.setTabsClosable(True)
        self.doc_tabs.setMovable(True)
        self.doc_tabs.setExpanding(False)
        self.doc_tabs.setElideMode(Qt.ElideMiddle)
        self.doc_tabs.setDocumentMode(True)
        self.doc_tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.doc_tabs.customContextMenuRequested.connect(self._on_tab_context_menu)
        self.doc_tabs.currentChanged.connect(self._on_tab_selected)
        self.doc_tabs.tabCloseRequested.connect(self.close_tab)
        self.doc_tabs.tabMoved.connect(self._on_tab_moved)
        tlay.addWidget(self.doc_tabs, 1)
        self.btn_new_tab = QPushButton("+")
        self.btn_new_tab.setFixedSize(28, 26)
        self.btn_new_tab.setStyleSheet("padding: 0px; font-size: 16px; font-weight: 600;")
        self.btn_new_tab.setToolTip("Buka PDF di tab baru (Ctrl+O)")
        self.btn_new_tab.clicked.connect(lambda: self.open_file())
        tlay.addWidget(self.btn_new_tab)
        self.doc_tabs_bar.hide()

        # ---- digital signature verification banner
        self.sig_banner = QWidget()
        self.sig_banner.setObjectName("sigBannerOk")
        slay = QHBoxLayout(self.sig_banner)
        slay.setContentsMargins(14, 6, 14, 6)
        slay.setSpacing(10)
        self.sig_banner_label = QLabel("")
        self.sig_banner_label.setStyleSheet("background:transparent; font-weight:600;")
        slay.addWidget(self.sig_banner_label, 1)
        self.sig_banner_btn = QPushButton("Detail Tanda Tangan…")
        self.sig_banner_btn.clicked.connect(self.verify_signatures)
        slay.addWidget(self.sig_banner_btn)
        sig_close = QPushButton("×")
        sig_close.setFixedSize(26, 24)
        sig_close.clicked.connect(self._dismiss_sig_banner)
        slay.addWidget(sig_close)
        self.sig_banner.hide()

        # ---- external file change reload banner
        self.reload_banner = QWidget()
        self.reload_banner.setObjectName("reloadBanner")
        rlay = QHBoxLayout(self.reload_banner)
        rlay.setContentsMargins(14, 6, 14, 6)
        rlay.setSpacing(10)
        self.reload_label = QLabel("File ini telah diubah di luar PDF Studio.")
        self.reload_label.setStyleSheet("background:transparent; font-weight:600;")
        rlay.addWidget(self.reload_label, 1)
        btn_reload = QPushButton("Muat Ulang")
        btn_reload.setObjectName("primary")
        btn_reload.clicked.connect(self.reload_current_file)
        rlay.addWidget(btn_reload)
        btn_ignore = QPushButton("Abaikan")
        btn_ignore.clicked.connect(self._dismiss_reload_banner)
        rlay.addWidget(btn_ignore)
        self.reload_banner.hide()

        self.context_bar = QWidget()
        self.context_bar.setObjectName("contextBar")
        ctx = QHBoxLayout(self.context_bar)
        ctx.setContentsMargins(14, 7, 14, 7)
        ctx.setSpacing(10)
        self.ctx_title = QLabel("Pilih")
        self.ctx_title.setStyleSheet("font-weight:700;")
        self.ctx_hint = QLabel("")
        self.ctx_hint.setObjectName("hint")
        ctx.addWidget(self.ctx_title)
        ctx.addWidget(self.ctx_hint, 1)

        self.ctx_color = QPushButton()
        self.ctx_color.setFixedSize(30, 24)
        self.ctx_color.setToolTip("Warna alat aktif")
        self.ctx_color.clicked.connect(self._pick_color)
        ctx.addWidget(QLabel("Warna"))
        ctx.addWidget(self.ctx_color)

        self.ctx_width = QDoubleSpinBox()
        self.ctx_width.setRange(0.5, 16)
        self.ctx_width.setSingleStep(0.5)
        self.ctx_width.setValue(2.0)
        self.ctx_width.setSuffix(" pt")
        self.ctx_width.setFixedWidth(84)
        self.ctx_width.valueChanged.connect(self.width_spin_changed)
        ctx.addWidget(QLabel("Tebal"))
        ctx.addWidget(self.ctx_width)

        self.ctx_size = QDoubleSpinBox()
        self.ctx_size.setRange(4, 144)
        self.ctx_size.setValue(12)
        self.ctx_size.setSuffix(" pt")
        self.ctx_size.setFixedWidth(84)
        self.ctx_size.valueChanged.connect(self.size_spin_changed)
        ctx.addWidget(QLabel("Ukuran"))
        ctx.addWidget(self.ctx_size)

        self.ctx_font = QComboBox()
        self.ctx_font.addItems(["Helvetica", "Times", "Courier"])
        self.ctx_font.setFixedWidth(110)
        self.ctx_font.currentTextChanged.connect(
            lambda t: self.view.set_style(font=t))
        ctx.addWidget(QLabel("Font"))
        ctx.addWidget(self.ctx_font)

        self.ctx_done = QPushButton("Selesai (Esc)")
        self.ctx_done.clicked.connect(lambda: self._set_tool("select"))
        ctx.addWidget(self.ctx_done)
        self.context_bar.hide()

        # ---- floating-style Find Bar (Ctrl+F)
        self.find_bar = QWidget()
        self.find_bar.setObjectName("findBar")
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(10, 5, 10, 5)
        fb.setSpacing(6)
        self.find_bar_edit = QLineEdit()
        self.find_bar_edit.setPlaceholderText("Cari teks dalam dokumen…")
        self.find_bar_edit.setFixedWidth(230)
        self.find_bar_edit.setClearButtonEnabled(True)
        fb.addWidget(self.find_bar_edit)
        self.find_bar_count = QLabel("0 / 0")
        self.find_bar_count.setObjectName("hint")
        self.find_bar_count.setMinimumWidth(52)
        self.find_bar_count.setAlignment(Qt.AlignCenter)
        fb.addWidget(self.find_bar_count)
        self.find_bar_case = QToolButton()
        self.find_bar_case.setText("Aa")
        self.find_bar_case.setCheckable(True)
        self.find_bar_case.setToolTip("Case-sensitive")
        fb.addWidget(self.find_bar_case)
        self.find_bar_word = QToolButton()
        self.find_bar_word.setText("Kata")
        self.find_bar_word.setCheckable(True)
        self.find_bar_word.setToolTip("Whole word")
        fb.addWidget(self.find_bar_word)
        fb_prev = QToolButton()
        fb_prev.setText("▲")
        fb_prev.setToolTip("Hasil sebelumnya")
        fb_prev.clicked.connect(lambda: self._search_step(-1))
        fb.addWidget(fb_prev)
        fb_next = QToolButton()
        fb_next.setText("▼")
        fb_next.setToolTip("Hasil berikutnya")
        fb_next.clicked.connect(lambda: self._search_step(1))
        fb.addWidget(fb_next)
        fb_close = QToolButton()
        fb_close.setText("×")
        fb_close.setToolTip("Tutup (Esc)")
        fb_close.clicked.connect(self.find_bar.hide)
        fb.addWidget(fb_close)
        QShortcut(QKeySequence(Qt.Key_Escape), self.find_bar, self.find_bar.hide,
                  context=Qt.WidgetWithChildrenShortcut)
        self.find_bar.hide()

        self.organize_view = OrganizePagesView(self)
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.scroll)
        self.center_stack.addWidget(self.organize_view)

        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.doc_tabs_bar)
        lay.addWidget(self.sig_banner)
        lay.addWidget(self.reload_banner)
        lay.addWidget(self.context_bar)
        lay.addWidget(self.find_bar)
        lay.addWidget(self.center_stack, 1)
        self.setCentralWidget(holder)

        self.view = PageView()
        self.view.set_document(self.doc)
        self.welcome = WelcomePanel()
        self.welcome.openRequested.connect(lambda: self.open_file())
        self.welcome.demoRequested.connect(self.open_demo)
        self.welcome.imagesRequested.connect(self.create_from_images)
        self.welcome.mergeRequested.connect(self.merge_pdf_standalone)
        self.welcome.fileRequested.connect(self.open_file)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.welcome)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(140)
        self._resize_timer.timeout.connect(self._on_resize_idle)

    def width_spin_changed(self, value):
        self.width_spin.blockSignals(True)
        self.width_spin.setValue(value)
        self.width_spin.blockSignals(False)
        self.ctx_width.blockSignals(True)
        self.ctx_width.setValue(value)
        self.ctx_width.blockSignals(False)
        self.view.set_style(width=value)

    def size_spin_changed(self, value):
        self.size_spin.blockSignals(True)
        self.size_spin.setValue(value)
        self.size_spin.blockSignals(False)
        self.ctx_size.blockSignals(True)
        self.ctx_size.setValue(value)
        self.ctx_size.blockSignals(False)
        self.view.set_style(fontsize=value)

    def _act(self, text, slot=None, shortcut=None, icon_name=None, checkable=False,
             tip="", name=None):
        a = QAction(text, self)
        if icon_name:
            a.setIcon(icon(icon_name))
            self._icon_actions.append((a, icon_name))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
            a.setToolTip(tip if not text else f"{text} — {tip}")
        a.setCheckable(checkable)
        if slot:
            a.triggered.connect(slot)
        if name:
            setattr(self, name, a)
        return a

    def _refresh_icons(self):
        for a, name in self._icon_actions:
            a.setIcon(icon(name))

    def _build_actions(self):
        self.act_open = self._act("Buka…", lambda: self.open_file(), "Ctrl+O", "open", tip="Buka file PDF")
        self.act_new_from_images = self._act("Buat PDF dari Gambar…", self.create_from_images, None, "image",
                                             tip="Gabungkan beberapa file gambar menjadi PDF baru")
        self.act_close_tab = self._act("Tutup Tab", lambda: self.close_tab(), "Ctrl+W", tip="Tutup dokumen di tab aktif")
        self.act_save = self._act("Simpan", self.save, "Ctrl+S", "save", tip="Simpan perubahan")
        self.act_save_as = self._act("Simpan Sebagai…", self.save_as, "Ctrl+Shift+S", "save")
        self.act_undo = self._act("Undo", self.undo, "Ctrl+Z", "undo")
        self.act_redo = self._act("Redo", self.redo, "Ctrl+Y", "redo")
        self.act_print = self._act("Cetak…", self.print_doc, "Ctrl+P", "print")
        self.act_zoom_in = self._act("Perbesar", lambda: self._zoom_by(1.15), "Ctrl++", "zoom_in")
        self.act_zoom_out = self._act("Perkecil", lambda: self._zoom_by(1 / 1.15), "Ctrl+-", "zoom_out")
        self.act_fit_w = self._act("Lebar Halaman", self.fit_width, "Ctrl+2", "fit_width")
        self.act_fit_p = self._act("Pas Halaman", self.fit_page, "Ctrl+0", "fit_page")
        self.act_actual = self._act("Ukuran Asli", self.actual_size, "Ctrl+1", "zoom_in")
        self.act_prev = self._act("Halaman Sebelumnya", lambda: self.go_page(self.pno - 1), "PgUp", "prev")
        self.act_next = self._act("Halaman Berikutnya", lambda: self.go_page(self.pno + 1), "PgDown", "next")
        self.act_first = self._act("Halaman Pertama", lambda: self.go_page(0), "Ctrl+Home", "first")
        self.act_last = self._act("Halaman Terakhir", lambda: self.go_page(10 ** 9), "Ctrl+End", "last")
        self.act_copy = self._act("Salin Teks", self.copy_selection, "Ctrl+C")
        self.act_select_all = self._act("Pilih Semua Teks", self.view.select_all, "Ctrl+A")
        self.act_find = self._act("Cari…", self.focus_search, "Ctrl+F", "search")
        self.act_rotate_l = self._act("Putar Kiri", lambda: self.rotate_page(-90), "Ctrl+[", "rotate_l")
        self.act_rotate_r = self._act("Putar Kanan", lambda: self.rotate_page(90), "Ctrl+]", "rotate_r")
        self.act_delete_page = self._act("Hapus Halaman", self.delete_page, None, "trash")
        self.act_insert_page = self._act("Sisip Halaman Kosong", self.insert_page, None, "insert")
        self.act_move_up = self._act("Pindah Halaman ke Atas", lambda: self.move_page(-1), "Alt+Up", "arrow_up")
        self.act_move_down = self._act("Pindah Halaman ke Bawah", lambda: self.move_page(1), "Alt+Down", "arrow_down")
        self.act_extract = self._act("Ambil / Pisah Halaman…", self.extract_pages, None, "split")
        self.act_merge = self._act("Gabung PDF…", self.merge_pdf, None, "merge")
        self.act_compress = self._act("Kompres PDF…", self.compress, None, "compress")
        self.act_metadata = self._act("Properti Dokumen…", self.edit_metadata, None, "info")
        self.act_protect = self._act("Proteksi Password…", self.protect, None, "lock")
        self.act_unlock = self._act("Hapus Password…", self.remove_password, None, "lock")
        self.act_sign_digital = self._act("Tanda Tangan Digital…", self.start_digital_sign, None, "cert")
        self.act_verify_sig = self._act("Verifikasi Tanda Tangan…", self.verify_signatures, None, "cert",
                                        tip="Periksa validitas & integritas tanda tangan digital")
        self.act_new_sig = self._act("Buat Tanda Tangan Baru…", self.new_signature, None, "sign")
        self.act_new_image = self._act("Pilih Gambar Baru…", self.new_image, None, "image")
        self.act_finalize = self._act("Finalisasi (Flatten)…", self.finalize, None, "save")
        self.act_export_png = self._act("Ekspor Halaman ke PNG…", self.export_png, None, "image")
        self.act_export_docx = self._act("Ekspor ke Word (.docx)…", self.export_docx, None, "save",
                                         tip="Konversi PDF ke dokumen Microsoft Word (.docx)")
        self.act_export_txt = self._act("Ekspor ke Teks (.txt)…", self.export_txt, None, "text",
                                        tip="Ekstrak seluruh teks PDF ke file .txt")
        self.act_crop = self._act("Potong Margin (Crop)…", self.crop_document, None, "fit_page",
                                  tip="Auto-crop atau potong margin halaman")
        self.act_manage_images = self._act("Kelola Gambar Halaman…", self.manage_page_images, None, "image",
                                           tip="Ganti, ekstrak, atau hapus gambar yang tertanam di halaman ini")
        self.act_add_form = self._act("Tambah Field Formulir…", self.start_add_form_field, None, "form",
                                      tip="Buat field formulir baru (teks, checkbox, dropdown) di halaman")
        self.act_about = self._act("Tentang PDF Studio", self.show_about, None, "info")
        self.act_shortcuts = self._act("Shortcut Keyboard", self.show_shortcuts, "F1")
        self.act_quit = self._act("Keluar", self.close, "Ctrl+Q")
        self.act_demo = self._act("Buka Dokumen Contoh", self.open_demo, None, "open",
                                  tip="Buka PDF contoh bawaan aplikasi")
        self.act_find_replace = self._act("Cari & Ganti…", self.search_replace, "Ctrl+H",
                                          "search", tip="Ganti teks massal")
        self.act_watermark = self._act("Watermark…", self.watermark, None, "text",
                                       tip="Teks miring di latar halaman")
        self.act_pagenum = self._act("Nomor Halaman…", self.page_numbers, None, "first")
        self.act_header = self._act("Header & Footer…", self.header_footer, None, "text")
        self.act_sanitize = self._act("Bersihkan Dokumen…", self.sanitize, None, "trash")
        self.act_ocr = self._act("OCR Halaman Scan…", self.ocr_document, None, "search",
                                 tip="Tambah layer teks ke PDF hasil scan (OCR Windows/Tesseract)")
        self.act_unhighlight = self._act(
            "Hapus Latar Stabilo (Flatten)…", self.remove_flattened_highlight, None,
            "highlight",
            tip="Bersihkan blok kuning yang sudah menyatu dengan halaman (bukan anotasi)")
        self.act_batch = self._act("Proses Banyak File…", self.batch, None, "merge")
        self.act_compare = self._act("Bandingkan PDF…", self.compare, None, "split")
        self.act_attach = self._act("Lampiran…", self.attachments, None, "image")
        self.act_insert_pages = self._act("Sisip Halaman dari PDF…", self.insert_pages_pdf,
                                          None, "insert")
        self.act_duplicate_page = self._act("Duplikat Halaman", self.duplicate_page, None, "insert")
        self.act_command = self._act("Command Palette", self.command_palette, "Ctrl+K",
                                     "search", tip="Cari dan jalankan perintah")
        self.act_read = self._act("Mode Baca", self.toggle_read_mode, "F11", "fill_page",
                                  checkable=True, tip="Sembunyikan panel edit")
        self.act_organize = self._act(
            "Kelola Halaman (Grid)", self.toggle_organize_mode, "Ctrl+Shift+O",
            "fit_page", checkable=True,
            tip="Tampilan grid untuk putar, hapus, sisip, pindah, ekstrak banyak halaman")
        self.act_zoom_sel = self._act("Zoom ke Seleksi", self.zoom_to_selection, None, "zoom_in")
        self.act_dark = self._act("Tema Gelap", lambda: self.set_theme("dark"), None, "fill_page",
                                  checkable=True)
        self.act_light = self._act("Tema Terang", lambda: self.set_theme("light"), None, "fill_page",
                                   checkable=True)
        theme_group = QActionGroup(self)
        theme_group.addAction(self.act_dark)
        theme_group.addAction(self.act_light)
        self.act_dark.setChecked(True)

        self.act_layout_cont = self._act("Gulir Kontinu", lambda: self.set_layout_mode("continuous"),
                                         None, None, checkable=True)
        self.act_layout_single = self._act("Satu Halaman", lambda: self.set_layout_mode("single"),
                                           None, None, checkable=True)
        self.act_layout_two = self._act("Dua Halaman Berdampingan", lambda: self.set_layout_mode("two_page"),
                                        None, None, checkable=True)
        layout_group = QActionGroup(self)
        for a in (self.act_layout_cont, self.act_layout_single, self.act_layout_two):
            layout_group.addAction(a)
        self.act_layout_cont.setChecked(True)

        self.act_color_normal = self._act("Normal", lambda: self.set_color_mode("normal"),
                                          None, None, checkable=True)
        self.act_color_night = self._act("Mode Malam (Gelap)", lambda: self.set_color_mode("night"),
                                         None, None, checkable=True)
        self.act_color_sepia = self._act("Sepia (Hangat)", lambda: self.set_color_mode("sepia"),
                                         None, None, checkable=True)
        color_group = QActionGroup(self)
        for a in (self.act_color_normal, self.act_color_night, self.act_color_sepia):
            color_group.addAction(a)
        self.act_color_normal.setChecked(True)

        # tools
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_actions = {}
        tools = [
            ("select", "Pilih Teks", "select"),
            ("highlight", "Sorot", "highlight"),
            ("underline", "Garis Bawah", "underline"),
            ("strikeout", "Coret", "strikeout"),
            ("note", "Catatan", "note"),
            ("text", "Tambah Teks", "text"),
            ("edit_text", "Edit Teks", "edit_text"),
            ("ink", "Tinta", "ink"),
            ("rect", "Kotak", "rect"),
            ("ellipse", "Elips", "ellipse"),
            ("line", "Garis", "line"),
            ("arrow", "Panah", "arrow"),
            ("callout", "Callout", "callout"),
            ("stamp", "Stempel", "stamp"),
            ("image", "Gambar", "image"),
            ("signature", "Tanda Tangan", "sign"),
            ("form", "Isi Form", "form"),
            ("cert", "TTD Digital", "cert"),
            ("redact", "Redaksi", "redact"),
            ("hand", "Geser", "fit_width"),
        ]
        for key, text, ic in tools:
            a = QAction(icon(ic), text, self)
            self._icon_actions.append((a, ic))
            a.setCheckable(True)
            a.setStatusTip(TOOL_HINTS.get(key, text))
            a.setToolTip(text)
            a.triggered.connect(lambda _c=False, k=key: self._set_tool(k))
            self.tool_group.addAction(a)
            self.tool_actions[key] = a
        self.tool_actions["select"].setChecked(True)

    def _build_menus(self):
        mb = self.menuBar()
        m_file = mb.addMenu("&File")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_new_from_images)
        m_file.addAction(self.act_demo)
        self.recent_menu = m_file.addMenu("Terbaru")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m_file.addSeparator()
        m_file.addAction(self.act_save)
        m_file.addAction(self.act_save_as)
        m_file.addAction(self.act_close_tab)
        m_file.addSeparator()
        m_file.addAction(self.act_export_png)
        m_file.addAction(self.act_export_docx)
        m_file.addAction(self.act_export_txt)
        m_file.addAction(self.act_compress)
        m_file.addSeparator()
        m_file.addAction(self.act_print)
        m_file.addSeparator()
        m_file.addAction(self.act_metadata)
        m_file.addAction(self.act_quit)

        m_edit = mb.addMenu("&Edit")
        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)
        m_edit.addSeparator()
        m_edit.addAction(self.act_copy)
        m_edit.addAction(self.act_select_all)
        m_edit.addAction(self.act_find)
        m_edit.addAction(self.act_find_replace)
        m_edit.addSeparator()
        m_edit.addAction(self.act_command)

        m_view = mb.addMenu("&Tampilan")
        m_view.addAction(self.act_zoom_in)
        m_view.addAction(self.act_zoom_out)
        m_view.addAction(self.act_fit_w)
        m_view.addAction(self.act_fit_p)
        m_view.addAction(self.act_actual)
        m_view.addSeparator()
        m_view.addAction(self.act_first)
        m_view.addAction(self.act_prev)
        m_view.addAction(self.act_next)
        m_view.addAction(self.act_last)
        m_view.addSeparator()
        m_view.addAction(self.act_zoom_sel)
        m_view.addAction(self.act_read)
        m_view.addSeparator()
        m_layout = m_view.addMenu("Tata Letak Halaman")
        m_layout.addAction(self.act_layout_cont)
        m_layout.addAction(self.act_layout_single)
        m_layout.addAction(self.act_layout_two)
        m_color = m_view.addMenu("Filter Warna Halaman")
        m_color.addAction(self.act_color_normal)
        m_color.addAction(self.act_color_night)
        m_color.addAction(self.act_color_sepia)
        m_theme = m_view.addMenu("Tema")
        m_theme.addAction(self.act_dark)
        m_theme.addAction(self.act_light)
        m_panels = m_view.addMenu("Panel")
        m_panels.addAction(self.dock_tools.toggleViewAction())
        m_panels.addAction(self.dock_thumbs.toggleViewAction())
        m_panels.addAction(self.dock_props.toggleViewAction())
        m_panels.addAction(self.dock_comments.toggleViewAction())
        m_panels.addAction(self.dock_outline.toggleViewAction())
        m_panels.addAction(self.dock_search.toggleViewAction())
        m_panels.addAction(self.dock_layers.toggleViewAction())
        m_panels.addAction(self.dock_fields.toggleViewAction())

        m_doc = mb.addMenu("&Dokumen")
        m_doc.addAction(self.act_organize)
        m_doc.addSeparator()
        m_doc.addAction(self.act_rotate_l)
        m_doc.addAction(self.act_rotate_r)
        m_doc.addAction(self.act_crop)
        m_doc.addSeparator()
        m_doc.addAction(self.act_insert_page)
        m_doc.addAction(self.act_duplicate_page)
        m_doc.addAction(self.act_delete_page)
        m_doc.addAction(self.act_move_up)
        m_doc.addAction(self.act_move_down)
        m_doc.addSeparator()
        m_doc.addAction(self.act_insert_pages)
        m_doc.addAction(self.act_extract)
        m_doc.addAction(self.act_merge)
        m_doc.addSeparator()
        m_doc.addAction(self.act_watermark)
        m_doc.addAction(self.act_pagenum)
        m_doc.addAction(self.act_header)
        m_doc.addSeparator()
        m_doc.addAction(self.act_compare)
        m_doc.addAction(self.act_attach)
        m_doc.addAction(self.act_manage_images)
        m_doc.addAction(self.act_add_form)
        m_doc.addAction(self.act_batch)
        m_doc.addAction(self.act_sanitize)
        m_doc.addAction(self.act_unhighlight)
        m_doc.addAction(self.act_ocr)
        m_doc.addSeparator()
        m_doc.addAction(self.act_protect)
        m_doc.addAction(self.act_unlock)
        m_doc.addAction(self.act_sign_digital)
        m_doc.addAction(self.act_verify_sig)
        m_doc.addSeparator()
        m_doc.addAction(self.act_finalize)

        m_tools = mb.addMenu("&Alat")
        for key in ("select", "highlight", "underline", "strikeout", "note", "text",
                    "edit_text", "ink", "rect", "ellipse", "line", "arrow",
                    "callout", "stamp", "image", "signature", "form", "cert",
                    "redact", "hand"):
            m_tools.addAction(self.tool_actions[key])
        m_tools.addSeparator()
        m_tools.addAction(self.act_new_sig)
        m_tools.addAction(self.act_new_image)

        m_help = mb.addMenu("&Bantuan")
        m_help.addAction(self.act_shortcuts)
        m_help.addAction(self.act_about)

    def _toolbar_btn(self, action):
        b = QToolButton()
        b.setDefaultAction(action)
        b.setAutoRaise(True)
        b.setIconSize(QSize(22, 22))
        b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        return b

    def _build_toolbars(self):
        tb = QToolBar("Utama")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(22, 22))
        self.addToolBar(tb)
        for a in (self.act_open, self.act_save, self.act_undo, self.act_redo):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_first)
        tb.addAction(self.act_prev)
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(58)
        self.page_spin.setAlignment(Qt.AlignCenter)
        # NoButtons + QSS padding leaves a 1px line edit (Qt quirk), so hide the
        # buttons through the stylesheet instead.
        self.page_spin.setStyleSheet(
            "QSpinBox { padding: 6px 4px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 0px; border: 0px; }")
        self.page_spin.setToolTip("Nomor halaman")
        tb.addWidget(self.page_spin)
        self.page_total = QLabel("/ 0")
        self.page_total.setObjectName("hint")
        self.page_total.setFixedWidth(46)
        tb.addWidget(self.page_total)
        tb.addAction(self.act_next)
        tb.addAction(self.act_last)
        tb.addSeparator()
        tb.addAction(self.act_zoom_out)
        self.zoom_box = QComboBox()
        self.zoom_box.setEditable(True)
        self.zoom_box.setFixedWidth(84)
        self.zoom_box.addItems(["50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"])
        self.zoom_box.setCurrentText("100%")
        self.zoom_box.setToolTip("Zoom")
        tb.addWidget(self.zoom_box)
        tb.addAction(self.act_zoom_in)
        tb.addAction(self.act_fit_w)
        tb.addAction(self.act_fit_p)
        tb.addSeparator()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cari di dokumen…")
        self.search_edit.setFixedWidth(190)
        self.search_edit.setClearButtonEnabled(True)
        tb.addWidget(self.search_edit)
        self.search_case_btn = QToolButton()
        self.search_case_btn.setText("Aa")
        self.search_case_btn.setCheckable(True)
        self.search_case_btn.setToolTip("Cocokkan huruf besar/kecil (Case-sensitive)")
        self.search_case_btn.toggled.connect(lambda _c: self.run_search())
        tb.addWidget(self.search_case_btn)
        self.search_word_btn = QToolButton()
        self.search_word_btn.setText("Kata")
        self.search_word_btn.setCheckable(True)
        self.search_word_btn.setToolTip("Cocokkan kata utuh saja (Whole word)")
        self.search_word_btn.toggled.connect(lambda _c: self.run_search())
        tb.addWidget(self.search_word_btn)
        tb.addAction(self.act_find)
        self.search_prev = self._toolbar_btn(self._act("Hasil sebelumnya", lambda: self._search_step(-1), None, "prev"))
        self.search_next = self._toolbar_btn(self._act("Hasil berikutnya", lambda: self._search_step(1), None, "next"))
        tb.addWidget(self.search_prev)
        tb.addWidget(self.search_next)
        tb.addSeparator()
        tb.addAction(self.act_print)
        tb.addAction(self.act_organize)
        tb.addAction(self.act_command)
        tb.addAction(self.act_read)

        rail = QToolBar("Alat")
        rail.setObjectName("toolRail")
        rail.setMovable(False)
        rail.setOrientation(Qt.Vertical)
        rail.setIconSize(QSize(22, 22))
        rail.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addToolBar(Qt.LeftToolBarArea, rail)
        self.tool_rail = rail
        groups = (
            ("select", "highlight", "underline", "strikeout", "note"),
            ("text", "edit_text", "ink"),
            ("rect", "ellipse", "line", "arrow", "callout", "stamp"),
            ("image", "signature", "form", "cert", "redact", "hand"),
        )
        for gi, group in enumerate(groups):
            if gi:
                rail.addSeparator()
            for key in group:
                rail.addAction(self.tool_actions[key])
        rail.addSeparator()
        rail.addAction(self.act_rotate_l)
        rail.addAction(self.act_rotate_r)
        rail.addAction(self.act_insert_page)
        rail.addAction(self.act_delete_page)
        rail.addSeparator()
        rail.addAction(self.act_watermark)
        rail.addAction(self.act_pagenum)

        # ---- right side-panel rail (PdfCraft/Acrobat style)
        rrail = QToolBar("Panel Samping")
        rrail.setObjectName("rightRail")
        rrail.setMovable(False)
        rrail.setOrientation(Qt.Vertical)
        rrail.setIconSize(QSize(20, 20))
        rrail.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addToolBar(Qt.RightToolBarArea, rrail)
        self.right_rail = rrail
        self._rail_buttons: list[tuple[QToolButton, QDockWidget]] = []
        for tip, icon_name, dock in (
            ("Halaman (Thumbnail)", "fit_page", self.dock_thumbs),
            ("Outline / Bookmark", "note", self.dock_outline),
            ("Komentar", "callout", self.dock_comments),
            ("Field Formulir", "form", self.dock_fields),
            ("Layer (OCG)", "rect", self.dock_layers),
            ("Properti & Gaya Alat", "edit_text", self.dock_props),
            ("Hasil Pencarian", "zoom_in", self.dock_search),
        ):
            btn = QToolButton()
            btn.setCheckable(True)
            btn.setIcon(icon(icon_name))
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _c=False, d=dock: self._toggle_side_dock(d))
            rrail.addWidget(btn)
            self._rail_buttons.append((btn, dock))

    def _build_docks(self):
        self.dock_tools = QDockWidget("Semua Alat", self)
        self.dock_tools.setObjectName("dock_tools")
        self.dock_tools.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.dock_tools.setMinimumWidth(215)
        self.dock_tools.setMaximumWidth(320)
        tool_groups = [
            ("Edit & Teks", [
                ("Pilih / Kursor", self.tool_actions["select"]),
                ("Edit Teks di Halaman", self.tool_actions["edit_text"]),
                ("Kotak Teks", self.tool_actions["text"]),
                ("Cari & Ganti", self.act_find_replace),
            ]),
            ("Komentar & Anotasi", [
                ("Sorot Teks", self.tool_actions["highlight"]),
                ("Garis Bawah", self.tool_actions["underline"]),
                ("Coret Teks", self.tool_actions["strikeout"]),
                ("Catatan Tempel", self.tool_actions["note"]),
                ("Tinta Bebas", self.tool_actions["ink"]),
                ("Kotak", self.tool_actions["rect"]),
                ("Elips", self.tool_actions["ellipse"]),
                ("Panah", self.tool_actions["arrow"]),
                ("Callout", self.tool_actions["callout"]),
                ("Stempel", self.tool_actions["stamp"]),
                ("Sisip Gambar", self.tool_actions["image"]),
            ]),
            ("Kelola Halaman", [
                ("Kelola Halaman (Grid)", self.act_organize),
                ("Putar Kiri", self.act_rotate_l),
                ("Putar Kanan", self.act_rotate_r),
                ("Potong Margin", self.act_crop),
                ("Sisip Halaman Kosong", self.act_insert_page),
                ("Duplikat Halaman", self.act_duplicate_page),
                ("Hapus Halaman", self.act_delete_page),
                ("Ekstrak / Pisah PDF", self.act_extract),
                ("Gabung PDF", self.act_merge),
            ]),
            ("Formulir & Tanda Tangan", [
                ("Isi Formulir", self.tool_actions["form"]),
                ("Buat Field Formulir", self.act_add_form),
                ("Tanda Tangan", self.tool_actions["signature"]),
                ("TTD Digital (PAdES)", self.act_sign_digital),
                ("Verifikasi TTD", self.act_verify_sig),
            ]),
            ("Lindungi, Scan & Tata Letak", [
                ("OCR Halaman Scan", self.act_ocr),
                ("Redaksi Permanen", self.tool_actions["redact"]),
                ("Kunci Password AES-256", self.act_protect),
                ("Watermark", self.act_watermark),
                ("Nomor Halaman", self.act_pagenum),
                ("Header & Footer", self.act_header),
                ("Bandingkan PDF", self.act_compare),
            ]),
        ]
        self.all_tools_panel = AllToolsPanel(tool_groups, self)
        self.dock_tools.setWidget(self.all_tools_panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_tools)

        self.dock_thumbs = QDockWidget("Halaman", self)
        self.dock_thumbs.setObjectName("dock_thumbs")
        self.dock_thumbs.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.thumbs = ThumbnailPanel()
        self.dock_thumbs.setWidget(self.thumbs)
        self.dock_thumbs.setMinimumWidth(200)
        self.dock_thumbs.setMaximumWidth(320)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_thumbs)

        self.dock_props = QDockWidget("Properti", self)
        self.dock_props.setObjectName("dock_props")
        self.dock_props.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.dock_props.setMinimumWidth(246)
        self.dock_props.setMaximumWidth(320)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(12)

        self.grp_style = QGroupBox("Gaya Alat")
        f = QFormLayout(self.grp_style)
        f.setSpacing(9)
        f.setLabelAlignment(Qt.AlignLeft)
        self.color_btn = QPushButton("  Warna")
        self.color_btn.setFixedHeight(30)
        self.color_btn.clicked.connect(self._pick_color)
        f.addRow("Warna", self.color_btn)

        swatches = QHBoxLayout()
        swatches.setSpacing(4)
        for name, col in (("Kuning", "#ffd400"), ("Merah", "#e5484d"), ("Hijau", "#2eb872"),
                          ("Biru", "#3b82f6"), ("Hitam", "#111111"),
                          ("Putih", "#ffffff")):
            b = QPushButton()
            b.setFixedSize(24, 22)
            b.setToolTip(name)
            b.setStyleSheet(f"background:{col}; border:1px solid #4a4f59; border-radius:4px;")
            b.clicked.connect(lambda _c=False, c=col: self._use_color(QColor(c)))
            swatches.addWidget(b)
        swatches.addStretch(1)
        f.addRow("", swatches)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 16.0)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setValue(2.0)
        self.width_spin.setSuffix(" pt")
        self.width_spin.valueChanged.connect(self.width_spin_changed)
        f.addRow("Tebal", self.width_spin)

        self.font_box = QComboBox()
        self.font_box.addItems(["Helvetica", "Times", "Courier"])
        self.font_box.currentTextChanged.connect(
            lambda t: self.view.set_style(font=t))
        f.addRow("Font", self.font_box)

        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(4, 144)
        self.size_spin.setValue(12)
        self.size_spin.setSuffix(" pt")
        self.size_spin.valueChanged.connect(self.size_spin_changed)
        f.addRow("Ukuran teks", self.size_spin)
        lay.addWidget(self.grp_style)

        self.grp_annot = QGroupBox("Anotasi Terpilih")
        ga = QVBoxLayout(self.grp_annot)
        ga.setSpacing(6)
        self.annot_label = QLabel("Tidak ada anotasi terpilih.\nKlik anotasi di halaman.")
        self.annot_label.setObjectName("hint")
        self.annot_label.setWordWrap(True)
        ga.addWidget(self.annot_label)
        arow = QHBoxLayout()
        self.annot_props_btn = QPushButton("Properti…")
        self.annot_props_btn.clicked.connect(self._edit_selected_annot)
        self.annot_del_btn = QPushButton("Hapus")
        self.annot_del_btn.setObjectName("danger")
        self.annot_del_btn.clicked.connect(self._delete_selected_annot)
        arow.addWidget(self.annot_props_btn)
        arow.addWidget(self.annot_del_btn)
        ga.addLayout(arow)
        lay.addWidget(self.grp_annot)

        self.grp_page = QGroupBox("Halaman")
        pg = QVBoxLayout(self.grp_page)
        pg.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(self._toolbar_btn(self.act_rotate_l))
        row.addWidget(self._toolbar_btn(self.act_rotate_r))
        row.addWidget(self._toolbar_btn(self.act_insert_page))
        row.addWidget(self._toolbar_btn(self.act_delete_page))
        row.addStretch(1)
        pg.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(self._toolbar_btn(self.act_move_up))
        row2.addWidget(self._toolbar_btn(self.act_move_down))
        row2.addWidget(self._toolbar_btn(self.act_extract))
        row2.addWidget(self._toolbar_btn(self.act_duplicate_page))
        row2.addStretch(1)
        pg.addLayout(row2)
        lay.addWidget(self.grp_page)

        self.grp_info = QGroupBox("Dokumen")
        gi = QVBoxLayout(self.grp_info)
        gi.setSpacing(4)
        self.info_label = QLabel("Belum ada dokumen")
        self.info_label.setWordWrap(True)
        self.info_label.setObjectName("hint")
        gi.addWidget(self.info_label)
        b = QPushButton("Properti Dokumen…")
        b.clicked.connect(self.edit_metadata)
        gi.addWidget(b)
        b2 = QPushButton("Lampiran…")
        b2.clicked.connect(self.attachments)
        gi.addWidget(b2)
        lay.addWidget(self.grp_info)
        lay.addStretch(1)

        tip = QLabel("Tips: Ctrl+K untuk command palette,\nCtrl+scroll untuk zoom, F11 mode baca.")
        tip.setObjectName("hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.dock_props.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_props)

        # ---- comments
        self.dock_comments = QDockWidget("Komentar", self)
        self.dock_comments.setObjectName("dock_comments")
        self.dock_comments.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.dock_comments.setMinimumWidth(246)
        self.dock_comments.setMaximumWidth(340)
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(10, 10, 10, 10)
        cl.setSpacing(8)
        self.comment_list = QListWidget()
        self.comment_list.setWordWrap(True)
        self.comment_list.itemDoubleClicked.connect(self._goto_comment)
        cl.addWidget(self.comment_list, 1)
        crow = QHBoxLayout()
        jump = QPushButton("Loncat")
        jump.clicked.connect(lambda: self._goto_comment(self.comment_list.currentItem()))
        reply = QPushButton("Balas…")
        reply.clicked.connect(self._reply_comment)
        remove = QPushButton("Hapus")
        remove.clicked.connect(self._delete_comment)
        refresh = QPushButton("↻")
        refresh.setFixedWidth(32)
        refresh.setToolTip("Muat ulang komentar")
        refresh.clicked.connect(self._refresh_comments)
        crow.addWidget(jump)
        crow.addWidget(reply)
        crow.addWidget(remove)
        crow.addWidget(refresh)
        cl.addLayout(crow)
        self.dock_comments.setWidget(cw)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_comments)

        # ---- outline
        self.dock_outline = QDockWidget("Outline", self)
        self.dock_outline.setObjectName("dock_outline")
        self.dock_outline.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.dock_outline.setMinimumWidth(246)
        self.dock_outline.setMaximumWidth(340)
        ow = QWidget()
        ol = QVBoxLayout(ow)
        ol.setContentsMargins(10, 10, 10, 10)
        ol.setSpacing(8)
        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderHidden(True)
        self.outline_tree.itemDoubleClicked.connect(self._goto_outline)
        ol.addWidget(self.outline_tree, 1)
        orow = QHBoxLayout()
        add_bm = QPushButton("Tambah…")
        add_bm.clicked.connect(self._add_bookmark)
        del_bm = QPushButton("Hapus")
        del_bm.clicked.connect(self._remove_bookmark)
        reload_bm = QPushButton("Muat ulang")
        reload_bm.clicked.connect(self._refresh_outline)
        orow.addWidget(add_bm)
        orow.addWidget(del_bm)
        orow.addWidget(reload_bm)
        ol.addLayout(orow)
        self.dock_outline.setWidget(ow)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_outline)

        # ---- search results sidebar
        self.dock_search = QDockWidget("Pencarian", self)
        self.dock_search.setObjectName("dock_search")
        self.dock_search.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.dock_search.setMinimumWidth(246)
        self.dock_search.setMaximumWidth(360)
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(10, 10, 10, 10)
        sl.setSpacing(8)
        self.search_summary = QLabel("Ketik kata kunci di kotak Cari.")
        self.search_summary.setObjectName("hint")
        self.search_summary.setWordWrap(True)
        sl.addWidget(self.search_summary)
        self.search_list = QListWidget()
        self.search_list.setWordWrap(True)
        self.search_list.itemClicked.connect(self._on_search_item_clicked)
        self.search_list.itemActivated.connect(self._on_search_item_clicked)
        sl.addWidget(self.search_list, 1)
        self.dock_search.setWidget(sw)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_search)

        # ---- layers (OCG)
        self.dock_layers = QDockWidget("Layer (OCG)", self)
        self.dock_layers.setObjectName("dock_layers")
        self.dock_layers.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.dock_layers.setMinimumWidth(246)
        self.dock_layers.setMaximumWidth(340)
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(10, 10, 10, 10)
        ll.setSpacing(8)
        self.layer_summary = QLabel("Tidak ada layer (OCG) pada dokumen ini.")
        self.layer_summary.setObjectName("hint")
        self.layer_summary.setWordWrap(True)
        ll.addWidget(self.layer_summary)
        self.layer_list = QListWidget()
        self.layer_list.itemChanged.connect(self._on_layer_item_changed)
        ll.addWidget(self.layer_list, 1)
        self.dock_layers.setWidget(lw)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_layers)

        # ---- form fields
        self.dock_fields = QDockWidget("Field Formulir", self)
        self.dock_fields.setObjectName("dock_fields")
        self.dock_fields.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.dock_fields.setMinimumWidth(246)
        self.dock_fields.setMaximumWidth(340)
        fw = QWidget()
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(10, 10, 10, 10)
        fl.setSpacing(8)
        self.field_summary = QLabel("Belum ada field formulir.")
        self.field_summary.setObjectName("hint")
        self.field_summary.setWordWrap(True)
        fl.addWidget(self.field_summary)
        self.field_list = QListWidget()
        self.field_list.setWordWrap(True)
        self.field_list.itemClicked.connect(self._goto_field)
        self.field_list.itemDoubleClicked.connect(self._edit_field_from_panel)
        fl.addWidget(self.field_list, 1)
        frow = QHBoxLayout()
        btn_fedit = QPushButton("Ubah Nilai…")
        btn_fedit.clicked.connect(lambda: self._edit_field_from_panel(self.field_list.currentItem()))
        btn_fref = QPushButton("Muat ulang")
        btn_fref.clicked.connect(self._refresh_fields)
        frow.addWidget(btn_fedit)
        frow.addWidget(btn_fref)
        fl.addLayout(frow)
        self.dock_fields.setWidget(fw)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_fields)

        self.tabifyDockWidget(self.dock_props, self.dock_thumbs)
        self.tabifyDockWidget(self.dock_props, self.dock_comments)
        self.tabifyDockWidget(self.dock_props, self.dock_outline)
        self.tabifyDockWidget(self.dock_props, self.dock_fields)
        self.tabifyDockWidget(self.dock_props, self.dock_layers)
        self.tabifyDockWidget(self.dock_props, self.dock_search)
        self.dock_props.raise_()

    def _build_status(self):
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        sb.setContentsMargins(8, 0, 8, 0)
        # Keep a little breathing room: at 125-150% Windows scaling the default
        # QStatusBar height clips the descenders of the status labels.
        sb.setMinimumHeight(sb.fontMetrics().height() + 12)
        self.setStatusBar(sb)
        self.hint_label = QLabel("Siap")
        self.pos_label = QLabel("")
        self.hint_label.setContentsMargins(2, 3, 2, 3)
        self.pos_label.setContentsMargins(2, 3, 2, 3)
        sb.addWidget(self.hint_label, 1)
        sb.addPermanentWidget(self.pos_label)

    def _wire(self):
        self.view.action.connect(self._on_view_action)
        self.view.inlineCommit.connect(self._on_inline_commit)
        self.view.status.connect(self.hint_label.setText)
        self.view.zoomRequested.connect(self._zoom_by)
        self.view.pageActivated.connect(self._on_page_activated)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_moved)
        self.view.annotSelected.connect(self._on_annot_selected)
        self.view.annotChanged.connect(self._on_annot_changed)
        self.view.annotDeleted.connect(self._on_annot_deleted)
        self.view.annotProps.connect(self._open_annot_props)
        self.view.scanNeedsOcr.connect(self._ocr_scanned_page)
        self.view.linkClicked.connect(self._on_link_clicked)
        self._watcher.fileChanged.connect(self._on_external_file_changed)
        self.thumbs.pageSelected.connect(self.go_page)
        self.thumbs.moveRequested.connect(self._thumb_move)
        self.thumbs.actionRequested.connect(self._thumb_action)
        self.organize_view.batchAction.connect(self._on_organize_batch)
        self.organize_view.moveRequested.connect(self._on_organize_move)
        self.organize_view.pageActivated.connect(self._on_organize_page_activated)
        self.organize_view.closeRequested.connect(lambda: self.toggle_organize_mode(False))
        self.page_spin.valueChanged.connect(lambda v: self.go_page(v - 1))
        self.zoom_box.lineEdit().returnPressed.connect(self._zoom_from_box)
        self.zoom_box.activated.connect(lambda _i: self._zoom_from_box())
        self.search_edit.textChanged.connect(self._on_toolbar_search_changed)
        self.search_edit.returnPressed.connect(lambda: self._search_step(1))
        self.find_bar_edit.textChanged.connect(self._on_find_bar_changed)
        self.find_bar_edit.returnPressed.connect(lambda: self._search_step(1))
        self.find_bar_case.toggled.connect(lambda c: self._sync_search_flags(case=c))
        self.find_bar_word.toggled.connect(lambda w: self._sync_search_flags(word=w))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(280)
        self._search_timer.timeout.connect(lambda: self.run_search())
        self.setAcceptDrops(True)
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.activated.connect(self._on_escape)
        next_tab = QShortcut(QKeySequence("Ctrl+Tab"), self)
        next_tab.activated.connect(lambda: self._cycle_tab(1))
        prev_tab = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        prev_tab.activated.connect(lambda: self._cycle_tab(-1))

    def _on_escape(self):
        if self.view.inline_active():
            self.view.cancel_inline()
            return
        if self._organize_mode:
            self.toggle_organize_mode(False)
            return
        if self._read_mode:
            self.toggle_read_mode(False)
            return
        if self.view.selected_annot() is not None:
            self.view.select_annot(None)
            return
        self._set_tool("select")

    def _apply_theme(self):
        name = self._settings.value("theme", "dark")
        name = "light" if name == "light" else "dark"
        theme.set_current_theme(name)
        self.act_dark.setChecked(name == "dark")
        self.act_light.setChecked(name == "light")
        self.setStyleSheet(theme.THEME if name != "light" else theme.LIGHT_THEME)
        self._refresh_icons()
        self.view.set_theme(name)
        self.zoom_box.lineEdit().setAlignment(Qt.AlignCenter)

    # ---------------------------------------------------------------- helpers
    def _cat(self, tool=None):
        tool = tool or self.view.tool
        if tool in ("highlight", "note", "underline", "strikeout"):
            return "markup"
        if tool in ("text", "edit_text"):
            return "text"
        return "stroke"

    def _color(self) -> QColor:
        return self.colors[self._cat()]

    def _color_tuple(self):
        c = self._color()
        return (c.redF(), c.greenF(), c.blueF())

    def _use_color(self, color: QColor):
        self.colors[self._cat()] = color
        self._sync_color_button()
        self.view.set_style(color=(color.redF(), color.greenF(), color.blueF()))

    def _pick_color(self):
        c = QColorDialog.getColor(self._color(), self, "Pilih Warna")
        if c.isValid():
            self._use_color(c)

    def _sync_color_button(self):
        c = self._color()
        css = (f"background:{c.name()}; border:1px solid #5a5f69; border-radius:6px; color:"
               f"{'#111' if c.lightness() > 140 else '#fff'};")
        self.color_btn.setStyleSheet(css)
        self.color_btn.setText(f"  {c.name().upper()}")
        if hasattr(self, "ctx_color"):
            self.ctx_color.setStyleSheet(css.replace("border-radius:6px", "border-radius:5px"))

    def _update_context_bar(self, key):
        if not hasattr(self, "ctx_title"):
            return
        cat = self._cat(key)
        markup = key in ("highlight", "underline", "strikeout", "note")
        texty = key in ("text", "edit_text")
        vector = key in ("rect", "ellipse", "line", "arrow", "ink")
        bar = key not in ("select", "hand")
        self.context_bar.setVisible(bar and not self._read_mode)
        self.ctx_title.setText(self.tool_actions[key].text() if key in self.tool_actions else key)
        self.ctx_hint.setText(TOOL_HINTS.get(key, ""))
        self.ctx_color.setVisible(cat != "none")
        self.ctx_width.setVisible(vector or key in ("signature", "cert"))
        self.ctx_size.setVisible(texty or key in ("callout", "stamp"))
        self.ctx_font.setVisible(texty)
        self.ctx_done.setVisible(bar)

        if hasattr(self, "grp_style"):
            self.grp_style.setVisible(key not in ("select", "hand", "form", "image",
                                                 "signature", "cert"))
            self.grp_annot.setVisible(True)

    def _set_tool(self, key):
        if self._read_mode and key != "hand":
            self.toggle_read_mode(False)
        self.view.set_tool(key)
        if key in self.tool_actions:
            self.tool_actions[key].setChecked(True)
        self._sync_color_button()
        self._update_context_bar(key)
        self.hint_label.setText(TOOL_HINTS.get(key, ""))
        if key == "signature" and not self._sig_image_path:
            self._make_signature()
        elif key == "image" and not self._pending_image:
            self._pick_image()
        elif key == "cert" and not self._pending_sign:
            self.start_digital_sign()
        elif key == "stamp":
            if not getattr(self, "_stamp_values", None):
                self._choose_stamp()
        elif key == "callout":
            self.hint_label.setText("Tarik kotak untuk callout, lalu ketik isinya.")

    def _update_actions(self):
        has_doc = self.doc.is_open
        for a in (self.act_save, self.act_save_as, self.act_close_tab, self.act_print, self.act_zoom_in,
                  self.act_zoom_out, self.act_fit_w, self.act_fit_p, self.act_actual,
                  self.act_prev, self.act_next, self.act_first, self.act_last,
                  self.act_rotate_l, self.act_rotate_r, self.act_crop, self.act_delete_page,
                  self.act_insert_page, self.act_move_up, self.act_move_down,
                  self.act_extract, self.act_merge, self.act_compress,
                  self.act_metadata, self.act_protect, self.act_unlock,
                  self.act_sign_digital, self.act_verify_sig, self.act_finalize,
                  self.act_export_png, self.act_export_docx, self.act_export_txt,
                  self.act_manage_images, self.act_add_form,
                  self.act_select_all, self.act_find_replace, self.act_watermark,
                  self.act_pagenum, self.act_header, self.act_sanitize,
                  self.act_ocr, self.act_unhighlight,
                  self.act_compare, self.act_attach, self.act_insert_pages,
                  self.act_duplicate_page, self.act_zoom_sel, self.act_organize):
            a.setEnabled(has_doc)
        self.act_undo.setEnabled(has_doc and self.doc.can_undo)
        self.act_redo.setEnabled(has_doc and self.doc.can_redo)
        self.act_copy.setEnabled(has_doc)
        self.act_find.setEnabled(has_doc)
        for w in (self.page_spin, self.zoom_box, self.search_edit,
                  self.search_case_btn, self.search_word_btn,
                  self.search_prev, self.search_next):
            w.setEnabled(has_doc)

    def _update_title(self):
        if not self.doc.is_open:
            self.setWindowTitle(APP_NAME)
            return
        name = os.path.basename(self.doc.path or "Tanpa Nama")
        star = "• " if self.dirty else ""
        self.setWindowTitle(f"{star}{name} — {APP_NAME}")
        if 0 <= self._active_tab < self.doc_tabs.count():
            self.doc_tabs.setTabText(self._active_tab, f"{star}{name}")
            self.doc_tabs.setTabToolTip(self._active_tab, self.doc.path or name)
            self._tabs[self._active_tab].dirty = self.dirty

    def _update_status(self):
        if not self.doc.is_open:
            self.info_label.setText("Belum ada dokumen.\nBuka PDF dengan Ctrl+O.")
            self.pos_label.setText("")
            self.hint_label.setText("Siap")
            self.page_total.setText("/ 0")
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(0, 0)
            self.page_spin.blockSignals(False)
            return
        info = self.doc.info()
        w, h = info["size"]
        mb = info["filesize"] / (1024 * 1024)
        enc = " · terkunci 🔒" if info["encrypted"] else ""
        save_state = " · belum disimpan" if self.dirty else " · tersimpan"
        self.info_label.setText(
            f"{info['pages']} halaman{enc}\n"
            f"Ukuran halaman {w:.0f} × {h:.0f} pt\n"
            f"{mb:.2f} MB{save_state}\n{self._short_path(os.path.dirname(info['path'] or ''))}")
        self.page_total.setText(f"/ {self.doc.page_count}")
        self.pos_label.setText(
            f"Halaman {self.pno + 1}/{self.doc.page_count}   ·   Zoom {self.view.zoom * 100:.0f}%"
            f"   ·   {w:.0f}×{h:.0f} pt")
        self._sync_page_spin()

    @staticmethod
    def _short_path(path, limit=40):
        if not path or len(path) <= limit:
            return path or ""
        parts = path.replace("/", "\\").split("\\")
        tail = parts[-1]
        for part in reversed(parts[:-1]):
            candidate = part + "\\" + tail
            if len(candidate) + 2 > limit:
                break
            tail = candidate
        return "…\\" + tail

    def _sync_page_spin(self):
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, max(1, self.doc.page_count))
        self.page_spin.setValue(self.pno + 1)
        self.page_spin.blockSignals(False)

    def _update_widgets(self):
        if not self.doc.is_open:
            self.view.set_widget_rects([])
            return
        try:
            rects = [w["rect"] for w in self.doc.widgets(self.pno)]
        except Exception:
            rects = []
        self.view.set_widget_rects(rects)

    # ------------------------------------------------------------------ files
    def _show_viewer(self):
        if self.scroll.widget() is not self.view:
            old = self.scroll.takeWidget()
            if old is not None:
                old.setParent(None)
            self.scroll.setWidgetResizable(False)
            self.scroll.setWidget(self.view)
            self.view.show()

    def _show_welcome(self):
        if self._organize_mode:
            self.toggle_organize_mode(False)
        if self.scroll.widget() is not self.welcome:
            old = self.scroll.takeWidget()
            if old is not None:
                old.setParent(None)
            self.scroll.setWidgetResizable(True)
            self.scroll.setWidget(self.welcome)
            self.welcome.show()
        self.welcome.set_recent(self.recent)
        self.doc_tabs_bar.hide()
        self.sig_banner.hide()
        self.reload_banner.hide()
        self.context_bar.hide()
        self.find_bar.hide()
        self.dock_tools.show()
        for dock in (self.dock_thumbs, self.dock_props,
                     self.dock_comments, self.dock_outline, self.dock_fields,
                     self.dock_layers, self.dock_search):
            dock.hide()

    def _ensure_docks_visible(self):
        if self._docks_initialized:
            return
        self._docks_initialized = True
        docks = (self.dock_tools, self.dock_thumbs, self.dock_props,
                 self.dock_comments, self.dock_outline, self.dock_fields,
                 self.dock_layers, self.dock_search)
        saved_state = self._settings.value("dockState_v2")
        if saved_state:
            self.restoreState(saved_state)
            if not any(d.isVisible() for d in docks):
                for dock in docks:
                    dock.show()
        else:
            for dock in docks:
                dock.show()
            self.dock_props.raise_()
        self._sync_rail_buttons()

    def _toggle_side_dock(self, target: QDockWidget):
        side_docks = (self.dock_thumbs, self.dock_props,
                      self.dock_comments, self.dock_outline,
                      self.dock_fields, self.dock_layers, self.dock_search)
        if target.isVisible() and target.visibleRegion().boundingRect().width() > 0:
            for d in side_docks:
                d.hide()
        else:
            for d in side_docks:
                d.show()
            target.raise_()
        self._sync_rail_buttons()

    def _sync_rail_buttons(self):
        for btn, dock in getattr(self, "_rail_buttons", []):
            active = dock.isVisible() and not dock.visibleRegion().isEmpty()
            btn.blockSignals(True)
            btn.setChecked(active)
            btn.blockSignals(False)

    def _sync_watcher(self):
        watched = self._watcher.files()
        if watched:
            self._watcher.removePaths(watched)
        paths = []
        for tab in self._tabs:
            p = tab.doc.path
            if p and os.path.exists(p) and p not in paths:
                paths.append(p)
        if paths:
            self._watcher.addPaths(paths)

    def _on_external_file_changed(self, path: str):
        if self._suppress_watch or not path:
            return
        norm = os.path.abspath(path).lower()
        for idx, tab in enumerate(self._tabs):
            if tab.doc.path and os.path.abspath(tab.doc.path).lower() == norm:
                tab.externally_modified = True
                if idx == self._active_tab:
                    self.reload_label.setText(
                        f"“{os.path.basename(path)}” diubah di luar PDF Studio.")
                    self.reload_banner.show()
        if os.path.exists(path) and path not in self._watcher.files():
            try:
                self._watcher.addPath(path)
            except Exception:
                pass

    def _dismiss_reload_banner(self):
        if 0 <= self._active_tab < len(self._tabs):
            self._tabs[self._active_tab].externally_modified = False
        self.reload_banner.hide()

    def reload_current_file(self):
        if not self.doc.is_open or not self.doc.path:
            return
        if not self._confirm_discard():
            return
        path = self.doc.path
        pw = self.doc.password
        page = self.pno
        try:
            self.doc.open(path, pw)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal memuat ulang", self._friendly(exc))
            return
        self.dirty = False
        if 0 <= self._active_tab < len(self._tabs):
            tab = self._tabs[self._active_tab]
            tab.dirty = False
            tab.externally_modified = False
            tab.sig_entries = self.doc.verify_signatures()
            tab.sig_dismissed = False
        self.reload_banner.hide()
        self.view.set_document(self.doc)
        self.thumbs.set_document(self.doc)
        self._sync_page(min(page, max(0, self.doc.page_count - 1)))
        self._update_title()
        self._update_actions()
        self._update_status()
        self._refresh_comments()
        self._refresh_outline()
        self._refresh_layers()
        self._refresh_fields()
        self._refresh_sig_banner()
        self._sync_watcher()
        self.hint_label.setText(f"Dimuat ulang: {os.path.basename(path)}")

    def _save_active_tab_state(self):
        if not (0 <= self._active_tab < len(self._tabs)):
            return
        tab = self._tabs[self._active_tab]
        tab.doc = self.doc
        tab.pno = self.pno
        tab.dirty = self.dirty
        tab.zoom = self.view.zoom
        tab.zoom_mode = self._zoom_mode
        tab.scroll_x = self.scroll.horizontalScrollBar().value()
        tab.scroll_y = self.scroll.verticalScrollBar().value()
        tab.search_query = self.search_edit.text()
        tab.search_hits = list(self._search_hits)
        tab.search_idx = self._search_idx

    def _activate_tab(self, idx: int, *, restore_view: bool = False):
        if not (0 <= idx < len(self._tabs)):
            return
        if self._active_tab != idx and 0 <= self._active_tab < len(self._tabs):
            self._save_active_tab_state()
            self._save_view_state()
        self._active_tab = idx
        tab = self._tabs[idx]
        self.doc = tab.doc
        self.pno = tab.pno
        self.dirty = tab.dirty
        self._zoom_mode = tab.zoom_mode
        self._search_hits = list(tab.search_hits)
        self._search_idx = tab.search_idx
        self._has_rendered = False

        self.doc_tabs.blockSignals(True)
        self.doc_tabs.setCurrentIndex(idx)
        self.doc_tabs.blockSignals(False)
        self.doc_tabs_bar.setVisible(not self._read_mode)

        self._show_viewer()
        if not self._read_mode:
            self._ensure_docks_visible()
        self.search_edit.blockSignals(True)
        self.search_edit.setText(tab.search_query)
        self.search_edit.blockSignals(False)
        self.view.set_document(self.doc)
        self.thumbs.set_document(self.doc)
        self._set_tool("select")
        if restore_view and self.doc.path:
            self._restore_view_state(self.doc.path)
        else:
            self._restoring_view = True
            try:
                if tab.zoom_mode in ("fitw", "fitp"):
                    self._zoom_mode = tab.zoom_mode
                    self._sync_page(tab.pno, force_zoom=True)
                else:
                    self._zoom_mode = "custom"
                    self.view.set_zoom(tab.zoom)
                    self._sync_page(tab.pno)
                if tab.scroll_x is not None:
                    self.scroll.horizontalScrollBar().setValue(tab.scroll_x)
                if tab.scroll_y is not None:
                    self.scroll.verticalScrollBar().setValue(tab.scroll_y)
            finally:
                self._restoring_view = False
        self._has_rendered = True
        self._refresh_search_view()
        self._update_title()
        self._update_actions()
        self._update_status()
        self._refresh_comments()
        self._refresh_outline()
        self._refresh_layers()
        self._refresh_fields()
        self._refresh_sig_banner()
        self.reload_banner.setVisible(bool(tab.externally_modified))

    def _on_tab_selected(self, idx: int):
        if idx >= 0 and idx != self._active_tab and idx < len(self._tabs):
            self._activate_tab(idx)

    def _on_tab_moved(self, from_idx: int, to_idx: int):
        if not (0 <= from_idx < len(self._tabs) and 0 <= to_idx < len(self._tabs)):
            return
        tab = self._tabs.pop(from_idx)
        self._tabs.insert(to_idx, tab)
        self._active_tab = self.doc_tabs.currentIndex()

    def _cycle_tab(self, delta: int):
        if len(self._tabs) < 2:
            return
        nxt = (self._active_tab + delta) % len(self._tabs)
        self._activate_tab(nxt)

    def _on_tab_context_menu(self, pos):
        idx = self.doc_tabs.tabAt(pos)
        if idx < 0:
            return
        menu = QMenu(self)
        act_close = menu.addAction("Tutup Tab")
        act_close_others = menu.addAction("Tutup Tab Lain")
        act_close_others.setEnabled(len(self._tabs) > 1)
        act_reopen = menu.addAction("Buka Kembali Tab Terakhir Ditutup")
        act_reopen.setEnabled(bool(self._closed_tabs))
        menu.addSeparator()
        tab_path = self._tabs[idx].doc.path if 0 <= idx < len(self._tabs) else ""
        act_reveal = menu.addAction("Tampilkan di Explorer")
        act_reveal.setEnabled(bool(tab_path and os.path.exists(tab_path)))
        chosen = menu.exec(self.doc_tabs.mapToGlobal(pos))
        if chosen == act_close:
            self.close_tab(idx)
        elif chosen == act_close_others:
            for i in range(len(self._tabs) - 1, -1, -1):
                if i != idx:
                    if not self.close_tab(i):
                        break
                    if i < idx:
                        idx -= 1
        elif chosen == act_reopen:
            self._reopen_last_closed_tab()
        elif chosen == act_reveal:
            self._reveal_in_explorer(tab_path)

    def _reopen_last_closed_tab(self):
        while self._closed_tabs:
            p = self._closed_tabs.pop()
            if os.path.exists(p):
                self.open_file(p)
                return

    def _reveal_in_explorer(self, path: str):
        if not path or not os.path.exists(path):
            return
        norm = os.path.normpath(path)
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", norm])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(norm)))

    def close_tab(self, idx: int | None = None) -> bool:
        if not self._tabs:
            return True
        if idx is None:
            idx = self._active_tab
        if not (0 <= idx < len(self._tabs)):
            return True
        if idx != self._active_tab:
            self._activate_tab(idx)
        if not self._confirm_discard():
            return False
        self._save_view_state()
        tab = self._tabs.pop(idx)
        if tab.doc.path and os.path.exists(tab.doc.path):
            self._closed_tabs.append(tab.doc.path)
            self._closed_tabs = self._closed_tabs[-15:]
        recovery.discard_snapshot(tab.doc.path)
        tab.doc.cleanup()
        self.doc_tabs.blockSignals(True)
        self.doc_tabs.removeTab(idx)
        self.doc_tabs.blockSignals(False)
        self._active_tab = -1
        if self._tabs:
            nxt = min(idx, len(self._tabs) - 1)
            self._activate_tab(nxt)
        else:
            self.doc = PdfDoc()
            self.pno = 0
            self.dirty = False
            self._search_hits = []
            self._search_idx = -1
            self.view.set_document(self.doc)
            self.thumbs.set_document(None)
            self._show_welcome()
            self._update_title()
            self._update_actions()
            self._update_status()
            self._refresh_comments()
            self._refresh_outline()
            self._refresh_layers()
            self._refresh_fields()
        self._sync_watcher()
        return True

    def open_demo(self):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        demo = os.path.join(base, "sample", "demo.pdf")
        if not os.path.exists(demo):
            QMessageBox.information(self, "Contoh tidak ditemukan",
                                    "File contoh tidak tersedia pada build ini.")
            return
        self.open_file(demo)

    def open_file(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Buka PDF", self._last_folder or "",
                "PDF (*.pdf);;Semua file (*)")
        if not path:
            return
        abs_path = os.path.abspath(path)
        for idx, tab in enumerate(self._tabs):
            if tab.doc.path and os.path.abspath(tab.doc.path).lower() == abs_path.lower():
                self._activate_tab(idx)
                return

        self._last_folder = os.path.dirname(abs_path)
        self._settings.setValue("last_folder", self._last_folder)
        password = None
        try:
            probe = fitz.open(abs_path)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal membuka", f"Tidak bisa membuka file:\n{exc}")
            return
        try:
            while probe.needs_pass:
                dlg = PasswordPrompt(self, os.path.basename(abs_path))
                if dlg.exec() != PasswordPrompt.Accepted:
                    probe.close()
                    return
                candidate = dlg.pw.text()
                if probe.authenticate(candidate):
                    password = candidate
                    break
                QMessageBox.warning(self, "Password salah",
                                    "Password tidak cocok. Coba lagi.")
        finally:
            probe.close()

        new_doc = PdfDoc()
        try:
            new_doc.open(abs_path, password)
        except Exception as exc:
            new_doc.cleanup()
            QMessageBox.critical(self, "Gagal membuka", f"Tidak bisa membuka file:\n{exc}")
            return

        if 0 <= self._active_tab < len(self._tabs):
            self._save_active_tab_state()
            self._save_view_state()

        sig_entries = new_doc.verify_signatures()
        tab = TabState(doc=new_doc, sig_entries=sig_entries)
        self._tabs.append(tab)
        idx = len(self._tabs) - 1
        self.doc_tabs.blockSignals(True)
        self.doc_tabs.addTab(os.path.basename(abs_path))
        self.doc_tabs.setTabToolTip(idx, abs_path)
        self.doc_tabs.blockSignals(False)

        self._add_recent(abs_path)
        recovery.discard_snapshot(abs_path)
        self._activate_tab(idx, restore_view=True)
        self._sync_watcher()
        self.hint_label.setText(
            f"Terbuka: {os.path.basename(abs_path)} — {self.doc.page_count} halaman")

    def create_from_images(self, image_paths: list[str] | None = None):
        if not image_paths:
            image_paths, _ = QFileDialog.getOpenFileNames(
                self, "Pilih gambar untuk dijadikan PDF", self._last_folder or "",
                "Gambar (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;Semua file (*)")
        if not image_paths:
            return
        self._last_folder = os.path.dirname(image_paths[0])
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Simpan PDF baru",
            os.path.join(self._last_folder, "gambar_gabungan.pdf"), "PDF (*.pdf)")
        if not out_path:
            return
        if not out_path.lower().endswith(".pdf"):
            out_path += ".pdf"
        try:
            n = create_pdf_from_images(image_paths, out_path)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal membuat PDF", self._friendly(exc))
            return
        self.open_file(out_path)
        self.hint_label.setText(f"PDF dibuat dari {n} gambar: {os.path.basename(out_path)}")

    def merge_pdf_standalone(self):
        if self.doc.is_open:
            return self.merge_pdf()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Pilih beberapa PDF untuk digabung", self._last_folder or "", "PDF (*.pdf)")
        if len(paths) < 2:
            if paths:
                self.open_file(paths[0])
            return
        self._last_folder = os.path.dirname(paths[0])
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Simpan PDF gabungan",
            os.path.join(self._last_folder, "gabungan.pdf"), "PDF (*.pdf)")
        if not out_path:
            return
        if not out_path.lower().endswith(".pdf"):
            out_path += ".pdf"
        tmp_doc = PdfDoc()
        try:
            tmp_doc.open(paths[0])
            for p in paths[1:]:
                tmp_doc.merge(p)
            tmp_doc.save_as(out_path)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal menggabung", self._friendly(exc))
            return
        finally:
            tmp_doc.cleanup()
        self.open_file(out_path)
        self.hint_label.setText(f"{len(paths)} PDF berhasil digabung.")

    def _on_link_clicked(self, link: dict):
        if not link:
            return
        if link.get("page") is not None:
            self.go_page(int(link["page"]))
            self.hint_label.setText(f"Loncat ke halaman {int(link['page']) + 1}.")
            return
        uri = (link.get("uri") or "").strip()
        if not uri:
            return
        low = uri.lower()
        if low.startswith(("http://", "https://", "mailto:")):
            r = QMessageBox.question(
                self, "Buka tautan eksternal?",
                f"Dokumen ini ingin membuka tautan eksternal:\n\n{uri}\n\n"
                "Pastikan kamu mempercayai tujuan tautan tersebut sebelum membuka.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(uri))
                self.hint_label.setText(f"Membuka tautan: {uri}")
            else:
                self.hint_label.setText("Pembukaan tautan eksternal dibatalkan.")
        else:
            self.hint_label.setText(f"Tautan diblokir demi keamanan: {uri}")

    def _refresh_sig_banner(self):
        if not (0 <= self._active_tab < len(self._tabs)):
            self.sig_banner.hide()
            return
        tab = self._tabs[self._active_tab]
        entries = tab.sig_entries
        if not entries or tab.sig_dismissed or self._read_mode:
            self.sig_banner.hide()
            return
        all_intact = all(e.get("intact") and e.get("valid") for e in entries)
        all_trusted = all_intact and all(e.get("trusted") for e in entries)
        first_signer = entries[0].get("signer") or "Penandatangan tidak dikenal"
        n = len(entries)
        if all_trusted:
            obj = "sigBannerOk"
            msg = f"Tertanda tangan digital ({n}) — Valid & terpercaya ({first_signer})"
        elif all_intact:
            obj = "sigBannerWarn"
            msg = f"Tertanda tangan digital ({n}) — Dokumen utuh, sertifikat self-signed / tidak dikenal ({first_signer})"
        else:
            obj = "sigBannerBad"
            msg = f"Peringatan tanda tangan digital ({n}) — Dokumen berubah atau tanda tangan tidak valid"
        self.sig_banner.setObjectName(obj)
        self.sig_banner.style().unpolish(self.sig_banner)
        self.sig_banner.style().polish(self.sig_banner)
        self.sig_banner_label.setText(msg)
        self.sig_banner.show()

    def _dismiss_sig_banner(self):
        if 0 <= self._active_tab < len(self._tabs):
            self._tabs[self._active_tab].sig_dismissed = True
        self.sig_banner.hide()

    def verify_signatures(self):
        if not self.doc.is_open:
            return
        entries = self.doc.verify_signatures()
        if 0 <= self._active_tab < len(self._tabs):
            self._tabs[self._active_tab].sig_entries = entries
            self._tabs[self._active_tab].sig_dismissed = False
        self._refresh_sig_banner()
        if not entries:
            QMessageBox.information(
                self, "Tidak ada tanda tangan digital",
                "Dokumen ini tidak memiliki tanda tangan digital kriptografis (PAdES).")
            return
        SignatureVerifyDialog(self, entries).exec()

    def set_layout_mode(self, mode: str):
        self.view.set_layout_mode(mode)
        self.act_layout_cont.setChecked(mode == "continuous")
        self.act_layout_single.setChecked(mode == "single")
        self.act_layout_two.setChecked(mode == "two_page")
        if self._zoom_mode in ("fitw", "fitp"):
            self._apply_zoom_mode()
        labels = {"continuous": "Gulir kontinu", "single": "Satu halaman",
                  "two_page": "Dua halaman berdampingan"}
        self.hint_label.setText(f"Tata letak: {labels.get(mode, mode)}")

    def set_color_mode(self, mode: str):
        self.view.set_color_mode(mode)
        self.act_color_normal.setChecked(mode == "normal")
        self.act_color_night.setChecked(mode == "night")
        self.act_color_sepia.setChecked(mode == "sepia")
        labels = {"normal": "Normal", "night": "Mode Malam", "sepia": "Sepia"}
        self.hint_label.setText(f"Filter halaman: {labels.get(mode, mode)}")

    # ------------------------------------------------------- per-file view mem
    def _view_key(self, path):
        import hashlib
        name = os.path.abspath(path or "").lower().encode("utf-8", "ignore")
        return "view/" + hashlib.md5(name).hexdigest()[:16]

    def _save_view_state(self):
        if not self.doc.is_open or not self.doc.path:
            return
        key = self._view_key(self.doc.path)
        self._settings.setValue(key + "/page", int(self.pno))
        self._settings.setValue(key + "/zoom", float(self.view.zoom))
        self._settings.setValue(key + "/mode", self._zoom_mode)

    def _restore_view_state(self, path):
        self._restoring_view = True
        try:
            key = self._view_key(path)
            page = self._settings.value(key + "/page", 0)
            zoom = self._settings.value(key + "/zoom", None)
            mode = self._settings.value(key + "/mode", "fitp")
            try:
                page = int(page)
            except Exception:
                page = 0
            if mode in ("fitw", "fitp"):
                self._zoom_mode = mode
                self._sync_page(page, force_zoom=True)
            else:
                self._zoom_mode = "custom"
                try:
                    z = float(zoom)
                except Exception:
                    z = 1.0
                if z > 0.05:
                    self.view.set_zoom(z)
                self._sync_page(page)
        finally:
            self._restoring_view = False

    def _add_recent(self, path):
        path = os.path.abspath(path)
        self.recent = [path] + [p for p in self.recent if os.path.abspath(p) != path]
        self.recent = self.recent[:8]
        self._settings.setValue("recent", self.recent)
        if hasattr(self, "welcome"):
            self.welcome.set_recent(self.recent)

    def _fill_recent(self):
        self.recent_menu.clear()
        if not self.recent:
            a = self.recent_menu.addAction("(belum ada)")
            a.setEnabled(False)
            return
        for p in self.recent:
            if not os.path.exists(p):
                continue
            a = self.recent_menu.addAction(os.path.basename(p))
            a.setToolTip(p)
            a.triggered.connect(lambda _c=False, f=p: self.open_file(f))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Bersihkan daftar")
        clear.triggered.connect(self._clear_recent)

    def _clear_recent(self):
        self.recent = []
        self._settings.setValue("recent", [])
        if hasattr(self, "welcome"):
            self.welcome.set_recent(self.recent)

    def save(self):
        if not self.doc.is_open:
            return
        if not self.doc.path:
            return self.save_as()
        self._suppress_watch = True
        try:
            self.doc.save_as(self.doc.path)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal menyimpan", str(exc))
            return
        finally:
            QTimer.singleShot(300, lambda: setattr(self, "_suppress_watch", False))
        self._after_save(self.doc.path)

    def save_as(self):
        if not self.doc.is_open:
            return
        base = self.doc.path or "dokumen.pdf"
        suggestion = base if self.doc.path else os.path.join(self._last_folder, "dokumen.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Simpan PDF", suggestion, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        old_path = self.doc.path
        self._suppress_watch = True
        try:
            self.doc.save_as(path)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal menyimpan", str(exc))
            return
        finally:
            QTimer.singleShot(300, lambda: setattr(self, "_suppress_watch", False))
        recovery.discard_snapshot(old_path)
        self._last_folder = os.path.dirname(path)
        self._after_save(path)

    def _after_save(self, path):
        self.dirty = False
        if 0 <= self._active_tab < len(self._tabs):
            tab = self._tabs[self._active_tab]
            tab.dirty = False
            tab.externally_modified = False
        self.reload_banner.hide()
        recovery.discard_snapshot(path)
        recovery.discard_snapshot(self.doc.path)
        self._add_recent(path)
        self._sync_watcher()
        self._update_title()
        self._update_status()
        self.hint_label.setText(f"Tersimpan: {path}")

    # ------------------------------------------------------ autosave/recovery
    def _autosave_tick(self):
        if not self.doc.is_open or not self.dirty:
            return
        recovery.write_snapshot(self.doc, page=self.pno, zoom=self.view.zoom)

    def _check_recovery(self):
        try:
            recovery.prune_snapshots()
        except Exception:
            pass
        entries = recovery.list_snapshots()
        if not entries:
            return
        dlg = RecoveryDialog(self, entries)
        if dlg.exec() != RecoveryDialog.Accepted:
            if dlg.delete_requested():
                for meta in entries:
                    recovery.discard_snapshot(meta.get("original"))
            return
        picked = dlg.selected_entries()
        if picked:
            self._restore_snapshot(picked[0])

    def _restore_snapshot(self, meta):
        snap = meta.get("snapshot")
        if not snap or not os.path.exists(snap):
            QMessageBox.warning(self, "Snapshot hilang",
                                "File snapshot sudah tidak ada.")
            recovery.discard_snapshot(meta.get("original"))
            return
        new_doc = PdfDoc()
        try:
            new_doc.open(snap)
        except Exception as exc:
            new_doc.cleanup()
            QMessageBox.critical(self, "Gagal memulihkan",
                                 f"Snapshot tidak bisa dibuka:\n{exc}")
            return
        original = meta.get("original") or ""
        if original and os.path.exists(original):
            new_doc.path = original
        page = max(0, min(int(meta.get("page", 0)), new_doc.page_count - 1))
        if 0 <= self._active_tab < len(self._tabs):
            self._save_active_tab_state()
        tab = TabState(doc=new_doc, pno=page, dirty=True, zoom_mode="fitp",
                       sig_entries=new_doc.verify_signatures())
        self._tabs.append(tab)
        idx = len(self._tabs) - 1
        title = os.path.basename(new_doc.path or meta.get("name") or "Dipulihkan.pdf")
        self.doc_tabs.blockSignals(True)
        self.doc_tabs.addTab(f"• {title}")
        self.doc_tabs.setTabToolTip(idx, new_doc.path or title)
        self.doc_tabs.blockSignals(False)
        self._activate_tab(idx, restore_view=False)
        self._sync_watcher()
        self.hint_label.setText(
            "Dokumen dipulihkan dari snapshot otomatis — simpan dengan Ctrl+S.")

    def _confirm_discard(self):
        if not self.doc.is_open or not self.dirty:
            return True
        r = QMessageBox.question(
            self, "Perubahan belum disimpan",
            "Dokumen sudah diubah. Simpan dulu sebelum keluar?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if r == QMessageBox.Save:
            self.save()
            return not self.dirty
        return r == QMessageBox.Discard

    # ------------------------------------------------------------------- view
    def _sync_page(self, pno, force_zoom=False):
        if not self.doc.is_open:
            return
        self.pno = max(0, min(pno, self.doc.page_count - 1))
        self.view.set_page(self.pno)
        self.thumbs.set_current(self.pno)
        self._update_widgets()
        if force_zoom:
            self._apply_zoom_mode()
        elif self._zoom_mode != "custom":
            self._apply_zoom_mode()
        self._sync_zoom_box()
        self._update_status()
        self._save_view_state()

    def go_page(self, pno):
        if not self.doc.is_open:
            return
        pno = max(0, min(pno, self.doc.page_count - 1))
        if pno == self.pno:
            return
        self._sync_page(pno)
        self._refresh_search_view()

    def _on_scroll_moved(self, _value=0):
        """Keep the page number/thumbnail in sync while the strip scrolls."""
        if not self.doc.is_open or self._restoring_view:
            return
        self.view.sync_active_from_viewport()

    def _on_page_activated(self, pno):
        """The pointer/scroll brought another page into focus."""
        if not self.doc.is_open:
            return
        pno = max(0, min(int(pno), self.doc.page_count - 1))
        if pno == self.pno:
            self._sync_page_spin()
            return
        self.pno = pno
        self.thumbs.set_current(pno)
        self._update_widgets()
        self._update_status()
        self._save_view_state()

    def _zoom_from_box(self):
        text = self.zoom_box.currentText().strip().lower().replace("%", "").strip()
        if text in ("fit", "pas", "fit width", "lebar"):
            self.fit_width()
            return
        try:
            val = float(text)
        except ValueError:
            self._sync_zoom_box()
            return
        if val < 10:
            val *= 100
        self._set_zoom(val / 100.0)

    def _sync_zoom_box(self):
        self.zoom_box.blockSignals(True)
        self.zoom_box.setCurrentText(f"{self.view.zoom * 100:.0f}%")
        self.zoom_box.blockSignals(False)

    def _zoom_by(self, factor):
        self._set_zoom(self.view.zoom * factor)

    def _set_zoom(self, z, mode="custom"):
        self._zoom_mode = mode
        self._restoring_view = True
        try:
            self.view.set_zoom(z)
            if self.doc.is_open:
                self.view.scroll_to_page(self.pno)
        finally:
            self._restoring_view = False
        self._sync_zoom_box()
        self._update_status()
        self._save_view_state()

    def _apply_zoom_mode(self):
        if self._zoom_mode == "custom":
            return
        vp = self.scroll.viewport().size()
        if not self.doc.is_open:
            return
        pw, ph = self.doc.page_size(self.pno)
        if pw <= 0 or ph <= 0:
            return
        avail_w = max(120, vp.width() - 34)
        avail_h = max(120, vp.height() - 34)
        if self._zoom_mode == "fitw":
            z = avail_w / pw
        else:
            z = min(avail_w / pw, avail_h / ph)
        self._restoring_view = True
        try:
            self.view.set_zoom(z)
            self.view.scroll_to_page(self.pno)
        finally:
            self._restoring_view = False
        self._sync_zoom_box()
        self._update_status()

    def fit_width(self):
        self._zoom_mode = "fitw"
        self._apply_zoom_mode()

    def fit_page(self):
        self._zoom_mode = "fitp"
        self._apply_zoom_mode()

    def actual_size(self):
        self._set_zoom(1.0)

    def _on_resize_idle(self):
        if self.view.inline_active():
            return
        if self._zoom_mode in ("fitw", "fitp"):
            self._apply_zoom_mode()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._resize_timer.start()

    def _restore_center(self, old_ratio):
        pass

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(30, lambda: None if self.view.inline_active() else self._apply_zoom_mode())

    def copy_selection(self):
        text = self.view.selection_text()
        if not text:
            self.hint_label.setText("Tidak ada teks terpilih. Tarik dulu di halaman dengan alat Pilih.")
            return
        QGuiApplication.clipboard().setText(text)
        self.hint_label.setText(f"{len(text)} karakter disalin ke clipboard.")

    def focus_search(self):
        if self.doc.is_open:
            self.find_bar.show()
            self.find_bar_edit.setFocus()
            self.find_bar_edit.selectAll()
        else:
            self.search_edit.setFocus()
            self.search_edit.selectAll()

    def _on_toolbar_search_changed(self, text: str):
        if self.find_bar_edit.text() != text:
            self.find_bar_edit.blockSignals(True)
            self.find_bar_edit.setText(text)
            self.find_bar_edit.blockSignals(False)
        self._search_debounce()

    def _on_find_bar_changed(self, text: str):
        if self.search_edit.text() != text:
            self.search_edit.blockSignals(True)
            self.search_edit.setText(text)
            self.search_edit.blockSignals(False)
        self._search_debounce()

    def _sync_search_flags(self, case=None, word=None):
        if case is not None:
            for b in (self.search_case_btn, self.find_bar_case):
                b.blockSignals(True)
                b.setChecked(case)
                b.blockSignals(False)
        if word is not None:
            for b in (self.search_word_btn, self.find_bar_word):
                b.blockSignals(True)
                b.setChecked(word)
                b.blockSignals(False)
        self.run_search()

    def _update_find_bar_count(self):
        total = len(self._search_hits)
        cur = (self._search_idx + 1) if (total and 0 <= self._search_idx < total) else 0
        self.find_bar_count.setText(f"{cur} / {total}")

    def _search_debounce(self):
        self._search_timer.start()

    def run_search(self):
        if not self.doc.is_open:
            return
        query = self.search_edit.text()
        mc = self.search_case_btn.isChecked()
        ww = self.search_word_btn.isChecked()
        self.search_list.clear()
        if not query.strip():
            self._search_hits = []
            self._search_idx = -1
            self.search_summary.setText("Ketik kata kunci di kotak Cari.")
            self.dock_search.setWindowTitle("Pencarian")
            self._update_find_bar_count()
            self._refresh_search_view()
            return
        entries = self.doc.search_with_context(query, match_case=mc, whole_word=ww)
        self._search_hits = [(e["page"], e["rect"]) for e in entries]
        self._search_idx = 0 if self._search_hits else -1
        for i, e in enumerate(entries):
            item = QListWidgetItem(f"Hal {e['page'] + 1} — {e['snippet']}")
            item.setData(Qt.UserRole, i)
            item.setToolTip(e["snippet"])
            self.search_list.addItem(item)
        if self._search_hits:
            pages_n = len({e["page"] for e in entries})
            self.search_summary.setText(
                f"{len(entries)} hasil di {pages_n} halaman untuk “{query}”.")
            self.dock_search.setWindowTitle(f"Pencarian ({len(entries)})")
            self.search_list.setCurrentRow(0)
            pno, _ = self._search_hits[0]
            if pno != self.pno:
                self._sync_page(pno)
            self.hint_label.setText(f"{len(self._search_hits)} hasil untuk “{query}”")
        else:
            self.search_summary.setText(f"Tidak ditemukan hasil untuk “{query}”.")
            self.dock_search.setWindowTitle("Pencarian (0)")
            self.hint_label.setText(f"Tidak ditemukan: “{query}”")
        self._refresh_search_view()
        self._update_find_bar_count()
        if self._search_hits:
            self._search_scroll_to_hit()

    def _on_search_item_clicked(self, item):
        if item is None:
            return
        idx = item.data(Qt.UserRole)
        if isinstance(idx, int) and 0 <= idx < len(self._search_hits):
            self._search_idx = idx
            pno, _ = self._search_hits[idx]
            if pno != self.pno:
                self._sync_page(pno)
            self._refresh_search_view()
            self._search_scroll_to_hit()
            self.hint_label.setText(
                f"Hasil {idx + 1} dari {len(self._search_hits)} (halaman {pno + 1})")

    def _search_step(self, delta):
        if not self._search_hits:
            if self.search_edit.text().strip():
                self.run_search()
            return
        self._search_idx = (self._search_idx + delta) % len(self._search_hits)
        if 0 <= self._search_idx < self.search_list.count():
            self.search_list.setCurrentRow(self._search_idx)
        pno, _ = self._search_hits[self._search_idx]
        if pno != self.pno:
            self._sync_page(pno)
        self._refresh_search_view()
        self._search_scroll_to_hit()
        self.hint_label.setText(
            f"Hasil {self._search_idx + 1} dari {len(self._search_hits)} (halaman {pno + 1})")

    def _refresh_search_view(self):
        if not self._search_hits:
            self.view.set_search_hits([], -1)
            return
        self.view.set_search_hits(list(self._search_hits), self._search_idx)

    def _search_scroll_to_hit(self):
        if not self._search_hits or not (0 <= self._search_idx < len(self._search_hits)):
            return
        pno, rect = self._search_hits[self._search_idx]
        self.view.scroll_to_pdf_rect(pno, rect)

    # ---------------------------------------------------------- page changes
    def rotate_page(self, delta):
        if not self.doc.is_open:
            return
        self._mutate("Putar halaman", lambda: self.doc.rotate_page(self.pno, delta))
        self._apply_zoom_mode()

    def delete_page(self):
        if not self.doc.is_open:
            return
        if self.doc.page_count <= 1:
            QMessageBox.information(self, "Tidak bisa", "Dokumen harus punya minimal satu halaman.")
            return
        r = QMessageBox.question(self, "Hapus halaman",
                                 f"Hapus halaman {self.pno + 1}?", QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._mutate("Hapus halaman", lambda: self.doc.delete_page(self.pno), refresh=False)
        self.thumbs.rebuild()
        self._sync_page(min(self.pno, self.doc.page_count - 1))

    def insert_page(self):
        if not self.doc.is_open:
            return
        self._mutate("Sisip halaman", lambda: self.doc.insert_blank(self.pno + 1), refresh=False)
        self.thumbs.rebuild()
        self._sync_page(self.pno + 1)

    def move_page(self, delta):
        if not self.doc.is_open:
            return
        dst = self.pno + delta
        if dst < 0 or dst >= self.doc.page_count:
            return
        src = self.pno
        self._mutate("Pindah halaman", lambda: self.doc.move_page(src, dst), refresh=False)
        self.thumbs.rebuild()
        self._sync_page(dst)

    def extract_pages(self):
        if not self.doc.is_open:
            return
        dlg = PageRangeDialog(self, self.doc.page_count)
        if dlg.exec() != PageRangeDialog.Accepted:
            return
        pages = dlg.pages(self.doc.page_count)
        path, _ = QFileDialog.getSaveFileName(self, "Simpan halaman terpilih",
                                              os.path.join(self._last_folder, "halaman.pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.doc.extract(pages, path)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal", str(exc))
            return
        self.hint_label.setText(f"{len(pages)} halaman diekspor ke {path}")

    def merge_pdf(self):
        if not self.doc.is_open:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Gabung PDF", self._last_folder,
                                                "PDF (*.pdf)")
        if not paths:
            return
        try:
            self.doc.snapshot("Gabung PDF", self.pno)
            total = 0
            for p in paths:
                total += self.doc.merge(p)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal menggabung", str(exc))
            return
        self.dirty = True
        self.thumbs.rebuild()
        self._sync_page(self.pno)
        self._update_title()
        self.hint_label.setText(f"{total} halaman ditambahkan dari {len(paths)} file.")

    def compress(self):
        if not self.doc.is_open:
            return
        stem = os.path.splitext(os.path.basename(self.doc.path or "dokumen.pdf"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan salinan terkompresi",
            os.path.join(self._last_folder, f"{stem}_compressed.pdf"), "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self.doc.path and os.path.abspath(path) == os.path.abspath(self.doc.path):
            QMessageBox.warning(self, "Pilih nama lain",
                                "Pilih nama file baru untuk versi terkompresi.")
            return
        before = os.path.getsize(self.doc.path) if self.doc.path and os.path.exists(self.doc.path) else 0
        tmp_src = self.doc.temp_pdf()
        pw = self.doc.password

        def job(_worker):
            wdoc = PdfDoc()
            try:
                wdoc.open(tmp_src, pw)
                wdoc.compress_to(path)
            finally:
                wdoc.cleanup()
                if os.path.exists(tmp_src):
                    try:
                        os.unlink(tmp_src)
                    except OSError:
                        pass

        ok, res = run_in_background(
            self, "Kompres PDF", "Mengompres dokumen…", job,
            maximum=0, cancelable=False)
        if not ok:
            QMessageBox.critical(self, "Gagal", str(res))
            return
        after = os.path.getsize(path)
        gain = ""
        if before:
            pct = (1 - after / before) * 100
            gain = f" ({pct:+.0f}% dari {before / 1024 / 1024:.2f} MB)"
        QMessageBox.information(self, "Selesai",
                                f"File terkompresi disimpan:\n{path}\n\n"
                                f"Ukuran: {after / 1024 / 1024:.2f} MB{gain}")

    def edit_metadata(self):
        if not self.doc.is_open:
            return
        dlg = MetadataDialog(self, self.doc.metadata, details=self.doc.document_details())
        if dlg.exec() != MetadataDialog.Accepted:
            return
        meta = self.doc.metadata
        meta.update(dlg.values())
        self._mutate("Ubah properti", lambda: self.doc.set_metadata(meta))
        self.hint_label.setText("Properti dokumen diperbarui.")

    def protect(self):
        if not self.doc.is_open:
            return
        dlg = ProtectDialog(self)
        if dlg.exec() != ProtectDialog.Accepted:
            return
        stem = os.path.splitext(os.path.basename(self.doc.path or "dokumen.pdf"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan PDF terproteksi",
            os.path.join(self._last_folder, f"{stem}_protected.pdf"), "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.doc.protect(path, **dlg.values())
        except Exception as exc:
            QMessageBox.critical(self, "Gagal", str(exc))
            return
        QMessageBox.information(self, "Terproteksi",
                                f"PDF terkunci disimpan:\n{path}\n\nBuka dengan password user yang tadi dibuat.")

    def remove_password(self):
        if not self.doc.is_open:
            return
        if not self.doc.info()["encrypted"]:
            QMessageBox.information(self, "Tidak terkunci", "Dokumen ini tidak memakai password.")
            return
        pw, ok = TextPrompt.get(self, "Hapus password", "Masukkan password dokumen", password=True)
        if not ok:
            return
        stem = os.path.splitext(os.path.basename(self.doc.path or "dokumen.pdf"))[0]
        path, _ = QFileDialog.getSaveFileName(self, "Simpan PDF tanpa password",
                                              os.path.join(self._last_folder, f"{stem}_unlocked.pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return
        try:
            strip_password(self.doc.path, path, pw)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal", str(exc))
            return
        QMessageBox.information(self, "Selesai", f"Salinan tanpa password disimpan:\n{path}")

    def finalize(self):
        if not self.doc.is_open:
            return
        r = QMessageBox.question(
            self, "Finalisasi dokumen",
            "Semua anotasi, catatan, dan isian form akan dijadikan bagian permanen halaman. "
            "Lanjutkan?", QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        def _bake():
            try:
                self.doc.doc.bake(annots=True, widgets=True)
            except Exception:
                for i in range(self.doc.page_count):
                    self.doc.page(i).bake(annots=True, widgets=True)
        self._mutate("Finalisasi", _bake)
        self.hint_label.setText("Anotasi diflatten menjadi konten halaman.")

    def export_png(self):
        if not self.doc.is_open:
            return
        folder = QFileDialog.getExistingDirectory(self, "Pilih folder ekspor", self._last_folder)
        if not folder:
            return
        prog = QProgressDialog("Mengekspor halaman…", "Batal", 0, self.doc.page_count, self)
        prog.setWindowTitle("Ekspor PNG")
        prog.setWindowModality(Qt.WindowModal)
        n = 0
        for i in range(self.doc.page_count):
            if prog.wasCanceled():
                break
            try:
                self.doc.export_png(i, os.path.join(folder, f"page_{i + 1:03d}.png"), dpi=150)
                n += 1
            except Exception:
                pass
            prog.setValue(i + 1)
            QApplication.processEvents()
        prog.close()
        self.hint_label.setText(f"{n} halaman diekspor ke {folder}")

    def export_docx(self):
        if not self.doc.is_open:
            return
        stem = os.path.splitext(os.path.basename(self.doc.path or "dokumen.pdf"))[0]
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Ekspor ke Word (.docx)",
            os.path.join(self._last_folder, f"{stem}.docx"), "Word Document (*.docx)")
        if not out_path:
            return
        if not out_path.lower().endswith(".docx"):
            out_path += ".docx"
        tmp_src = self.doc.temp_pdf()
        pw = self.doc.password
        total_pages = self.doc.page_count

        def job(worker):
            wdoc = PdfDoc()
            try:
                wdoc.open(tmp_src, pw)
                return _export_docx(
                    wdoc, out_path,
                    progress=lambda i, t, pno: worker.report(
                        i, t, f"Mengekspor halaman {pno + 1} dari {total_pages}…"))
            finally:
                wdoc.cleanup()
                if os.path.exists(tmp_src):
                    try:
                        os.unlink(tmp_src)
                    except OSError:
                        pass

        ok, res = run_in_background(
            self, "Ekspor ke Word", "Mengonversi PDF ke .docx…", job,
            maximum=total_pages, cancelable=True)
        if not ok:
            QMessageBox.critical(self, "Gagal ekspor Word", str(res))
            return
        self._last_folder = os.path.dirname(out_path)
        self.hint_label.setText(f"Diekspor ke Word: {os.path.basename(out_path)}")
        QMessageBox.information(
            self, "Ekspor selesai",
            f"{res} halaman diekspor ke:\n{out_path}")

    def export_txt(self):
        if not self.doc.is_open:
            return
        stem = os.path.splitext(os.path.basename(self.doc.path or "dokumen.pdf"))[0]
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Ekspor ke Teks (.txt)",
            os.path.join(self._last_folder, f"{stem}.txt"), "Teks (*.txt)")
        if not out_path:
            return
        if not out_path.lower().endswith(".txt"):
            out_path += ".txt"
        try:
            n = _export_text(self.doc, out_path)
        except Exception as exc:
            QMessageBox.critical(self, "Gagal ekspor teks", self._friendly(exc))
            return
        self._last_folder = os.path.dirname(out_path)
        self.hint_label.setText(f"Teks diekspor: {os.path.basename(out_path)} ({n} halaman)")
        QMessageBox.information(self, "Ekspor selesai", f"Teks dari {n} halaman disimpan:\n{out_path}")

    def crop_document(self):
        if not self.doc.is_open:
            return
        dlg = CropDialog(self, self.doc.page_count, self.pno)
        if dlg.exec() != CropDialog.Accepted:
            return
        v = dlg.values()
        pages = v["pages"]
        if not pages:
            QMessageBox.warning(self, "Halaman kosong", "Pilih minimal satu halaman yang valid.")
            return
        mode = v["mode"]
        res = {"n": 0}

        def apply():
            if mode == "auto":
                res["n"] = self.doc.auto_crop_pages(pages, margin=v["margin"])
            elif mode == "reset":
                res["n"] = self.doc.reset_crop(pages)
            else:
                res["n"] = self.doc.crop_pages(
                    pages, top=v["top"], bottom=v["bottom"],
                    left=v["left"], right=v["right"])

        label = {"auto": "Auto-crop margin", "manual": "Potong margin", "reset": "Reset crop"}[mode]
        self._mutate(label, apply, refresh=False)
        self.thumbs.rebuild()
        self.view.invalidate()
        self._sync_page(self.pno, force_zoom=(self._zoom_mode in ("fitw", "fitp")))
        self.hint_label.setText(f"{label}: {res['n']} halaman diperbarui.")

    def manage_page_images(self):
        if not self.doc.is_open:
            return
        dlg = PageImagesDialog(self, self.doc, self.pno, self._last_folder)
        dlg.exec()
        if dlg.changed:
            self.dirty = True
            self.view.invalidate()
            self.thumbs.update_page(self.pno)
            self._update_title()
            self._update_actions()
            self._update_status()
            self.hint_label.setText(f"Gambar di halaman {self.pno + 1} diperbarui. Ctrl+S untuk simpan.")

    def start_add_form_field(self):
        if not self.doc.is_open:
            return
        dlg = AddFormFieldDialog(self)
        if dlg.exec() != AddFormFieldDialog.Accepted:
            return
        self._pending_form_field = dlg.values()
        self._set_tool("add_form")
        self.hint_label.setText(
            f"Tarik kotak di halaman untuk menempatkan field “{self._pending_form_field['name']}”.")

    def print_doc(self):
        if not self.doc.is_open:
            return
        if self.dirty:
            r = QMessageBox.question(self, "Simpan dulu?",
                                     "Simpan perubahan sebelum mencetak?",
                                     QMessageBox.Save | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return
            if r == QMessageBox.Save:
                self.save()
        try:
            printer = QPrinter(QPrinter.HighResolution)
            printer.setDocName(os.path.basename(self.doc.path or "dokumen.pdf"))
            dlg = QPrintDialog(printer, self)
            dlg.setOptions(QPrintDialog.PrintToFile | QPrintDialog.PrintPageRange
                           | QPrintDialog.PrintCurrentPage | QPrintDialog.PrintShowPageSize)
            dlg.setMinMax(1, self.doc.page_count)
            dlg.setFromTo(1, self.doc.page_count)
            if dlg.exec() != QPrintDialog.Accepted:
                return
            prange = printer.printRange()
            if prange == QPrinter.CurrentPage:
                pages = [self.pno]
            elif prange == QPrinter.PageRange:
                p_from = max(1, printer.fromPage() or 1)
                p_to = min(self.doc.page_count, printer.toPage() or self.doc.page_count)
                if p_from > p_to:
                    p_from, p_to = p_to, p_from
                pages = list(range(p_from - 1, p_to))
            else:
                pages = list(range(self.doc.page_count))
            if not pages:
                return
            painter = QPainter()
            if not painter.begin(printer):
                QMessageBox.critical(self, "Gagal", "Printer tidak bisa dibuka.")
                return
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            render_dpi = min(max(150, printer.resolution()), 300)
            rect = printer.pageRect(QPrinter.DevicePixel)
            prog = QProgressDialog("Mencetak…", "Batal", 0, len(pages), self)
            prog.setWindowModality(Qt.WindowModal)
            for idx, i in enumerate(pages):
                if prog.wasCanceled():
                    break
                p = self.doc.page(i)
                zoom = render_dpi / 72.0
                pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, annots=True)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format_RGB888).copy()
                if idx > 0:
                    printer.newPage()
                pw = printer.pageRect(QPrinter.DevicePixel).width()
                ph = printer.pageRect(QPrinter.DevicePixel).height()
                scale = min(pw / max(1, img.width()), ph / max(1, img.height()))
                w = img.width() * scale
                h = img.height() * scale
                target = QRectF(rect.x() + (pw - w) / 2, rect.y() + (ph - h) / 2, w, h)
                painter.drawImage(target, img)
                prog.setValue(idx + 1)
                prog.setLabelText(f"Mencetak halaman {i + 1} ({idx + 1}/{len(pages)})…")
                QApplication.processEvents()
            painter.end()
            prog.close()
            self.hint_label.setText(f"{len(pages)} halaman dikirim ke printer.")
        except Exception as exc:
            QMessageBox.critical(self, "Gagal mencetak", str(exc))

    # -------------------------------------------------------------- mutations
    def _mutate(self, label, fn, refresh=True):
        if not self.doc.is_open:
            return
        self.doc.snapshot(label, self.pno)
        try:
            fn()
        except Exception as exc:
            QMessageBox.critical(self, "Gagal", f"{label}:\n{self._friendly(exc)}")
            return
        self.dirty = True
        if refresh:
            self.view.invalidate()
            self.thumbs.update_page(self.pno)
            self._update_widgets()
        self._update_title()
        self._update_actions()
        self._update_status()

    def undo(self):
        res = self.doc.undo()
        if not res:
            self.hint_label.setText("Tidak ada yang bisa di-undo.")
            return
        label, page = res
        self.dirty = True
        self.thumbs.rebuild()
        self.view.invalidate()
        self._sync_page(page)
        self._update_title()
        self._update_actions()
        self.hint_label.setText(f"Undo: {label}")

    def redo(self):
        res = self.doc.redo()
        if not res:
            self.hint_label.setText("Tidak ada yang bisa di-redo.")
            return
        label, page = res
        self.dirty = True
        self.thumbs.rebuild()
        self.view.invalidate()
        self._sync_page(page)
        self._update_title()
        self._update_actions()
        self.hint_label.setText(f"Redo: {label}")

    # --------------------------------------------------------------- gestures
    def _on_inline_commit(self, payload):
        if not self.doc.is_open:
            return
        info = payload.get("info") or {}
        text = (payload.get("text") or "").replace("\r\n", "\n").replace("\r", "\n")
        text = "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")
        rich_runs = payload.get("rich_runs")

        def norm(s):
            return " ".join((s or "").replace("\n", " ").split())

        if not text.strip():
            self.hint_label.setText("Teks kosong, tidak ada yang diubah.")
            return
        orig_runs = info.get("rich_runs")
        same_style = (rich_runs is None) or (rich_runs == orig_runs)
        if norm(text) == norm(info.get("text")) and same_style:
            self.hint_label.setText("Tidak ada perubahan teks.")
            return

        def apply():
            return self.doc.replace_text(
                self.pno, info["rect"], text, float(info.get("size") or 10.0),
                info.get("font") or "Helvetica",
                info.get("color") or (0, 0, 0),
                info.get("bg") or (1, 1, 1),
                bold=bool(info.get("bold")), italic=bool(info.get("italic")),
                baseline=info.get("baseline"), single=bool(info.get("single")),
                font_name=info.get("font_name"), line_gap=info.get("line_gap"),
                indent=float(info.get("indent") or 0.0),
                align=info.get("align") or "left",
                rich_runs=rich_runs,
                style_fonts=info.get("style_fonts"))

        self._mutate("Edit teks", apply)
        self.hint_label.setText("Teks diganti langsung di halaman. Ctrl+S untuk simpan.")

    def _on_view_action(self, kind, data):
        if not self.doc.is_open:
            return
        try:
            if kind == "gesture":
                self._handle_gesture(data["tool"], data["rect"],
                                     data.get("p1"), data.get("p2"))
            elif kind == "ink":
                strokes = data["strokes"]
                color = self._color_tuple()
                width = self.width_spin.value()
                self._mutate("Tinta", lambda: self.doc.add_ink(self.pno, strokes, color, width))
            elif kind == "note":
                r = data["rect"]
                point = (r[0], r[1])
                dlg = NoteDialog(self)
                if dlg.exec() != NoteDialog.Accepted:
                    return
                text = dlg.values()["text"]
                if not text.strip():
                    return
                color = self._color_tuple()
                self._mutate("Catatan", lambda: self.doc.add_note(self.pno, point, text, color))
            elif kind == "form_click":
                self._form_at(data["point"])
            elif kind == "form_fill":
                self._form_at(data["point"])
            elif kind == "clear_annots":
                self._clear_annots()
        except Exception:
            QMessageBox.critical(self, "Kesalahan", traceback.format_exc(limit=3))

    def _handle_gesture(self, tool, rect, p1=None, p2=None):
        x0, y0, x1, y1 = rect
        if tool in ("highlight", "underline", "strikeout", "squiggly"):
            color = self._color_tuple()
            self._mutate(f"Anotasi {tool}",
                         lambda: self.doc.annot_text_markup(self.pno, rect, tool, color))
        elif tool == "text":
            dlg = TextDialog(self, "Tambah Teks", "", self.size_spin.value(),
                             self.font_box.currentText(),
                             self.colors["text"].name())
            if dlg.exec() != TextDialog.Accepted:
                return
            v = dlg.values()
            if not v["text"].strip():
                return
            self.colors["text"] = QColor.fromRgbF(*v["color"])
            self._mutate("Tambah teks", lambda: self.doc.add_text(
                self.pno, rect, v["text"], v["fontsize"], v["font"],
                v["color"], bold=v["bold"], italic=v["italic"]))
        elif tool == "edit_text":
            words = self.doc.words(self.pno, clip=rect)
            current = " ".join(w[4] for w in words)
            dlg = TextDialog(self, "Edit Teks", current, self.size_spin.value(),
                             self.font_box.currentText(), "#111111",
                             hint="Teks lama di dalam kotak akan dihapus permanen lalu diganti. "
                                  "Font bisa bergeser sedikit dari aslinya.",
                             multi=True)
            if dlg.exec() != TextDialog.Accepted:
                return
            v = dlg.values()
            bg = self.doc.sample_color(self.pno, rect)
            self._mutate("Edit teks", lambda: self.doc.replace_text(
                self.pno, rect, v["text"], v["fontsize"], v["font"],
                v["color"], bg, bold=v["bold"], italic=v["italic"]))
        elif tool in ("rect", "ellipse"):
            color = self._color_tuple()
            width = self.width_spin.value()
            self._mutate(f"Bentuk {tool}", lambda: self.doc.add_shape(
                self.pno, rect, tool, color, width))
        elif tool in ("line", "arrow"):
            color = self._color_tuple()
            width = self.width_spin.value()
            a = p1 if p1 is not None else (x0, y0)
            b = p2 if p2 is not None else (x1, y1)
            if abs(a[0] - b[0]) < 1 and abs(a[1] - b[1]) < 1:
                return
            self._mutate("Garis" if tool == "line" else "Panah",
                         lambda: self.doc.add_line(self.pno, a, b, color, width,
                                                   arrow=(tool == "arrow")))
        elif tool == "callout":
            text, ok = TextPrompt.get(self, "Callout", "Isi komentar")
            if not ok or not text.strip():
                return
            pw, ph = self.doc.page_size(self.pno)
            target = (min(max(x0 - 30, 4), pw - 4), min(y1 + 50, ph - 4))
            color = self._color_tuple()
            self._mutate("Callout", lambda: self.doc.add_callout(
                self.pno, rect, text, target, color=color,
                fill=(1.0, 1.0, 0.88), fontsize=max(8.0, self.size_spin.value() * 0.8)))
        elif tool == "stamp":
            values = getattr(self, "_stamp_values", None)
            if not values:
                self._choose_stamp()
                values = getattr(self, "_stamp_values", None)
            if not values:
                return
            r = rect
            if r[2] - r[0] < 24 or r[3] - r[1] < 12:
                r = (x0, y0, x0 + 170, y0 + 48)
            self._mutate("Stempel", lambda: self.doc.add_stamp_text(
                self.pno, r, values["text"], values["color"], (1, 1, 1),
                values["fontsize"]))
        elif tool == "redact":
            r = QMessageBox.warning(
                self, "Redaksi permanen",
                "Isi di area ini akan dihapus permanen dari file (bukan sekadar ditutup). "
                "Lanjutkan?", QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
            self._mutate("Redaksi", lambda: self.doc.redact(self.pno, rect))
        elif tool == "add_form":
            spec = self._pending_form_field
            if not spec:
                self.start_add_form_field()
                spec = self._pending_form_field
            if not spec:
                self._set_tool("select")
                return
            created = {"name": ""}

            def _add():
                created["name"] = self.doc.add_form_field(
                    self.pno, rect, spec["kind"], spec["name"],
                    options=spec.get("options"), default=spec.get("default", ""),
                    fontsize=spec.get("fontsize", 11.0))

            self._mutate("Tambah field formulir", _add)
            self._pending_form_field = None
            self._set_tool("form")
            self.hint_label.setText(
                f"Field “{created['name']}” ditambahkan. Klik field untuk mengisinya.")
        elif tool == "signature":
            if not self._sig_image_path:
                self._make_signature()
                if not self._sig_image_path:
                    return
            path = self._sig_image_path
            self._mutate("Tanda tangan", lambda: self.doc.insert_image(
                self.pno, rect, path, keep_proportion=True))
            self.hint_label.setText("Tanda tangan ditempel. Simpan dengan Ctrl+S.")
        elif tool == "image":
            if not self._pending_image:
                self._pick_image()
                if not self._pending_image:
                    return
            path = self._pending_image
            self._mutate("Sisip gambar", lambda: self.doc.insert_image(
                self.pno, rect, path, keep_proportion=True))
        elif tool == "cert":
            self._place_signature_field(rect)

    def _form_at(self, point):
        widgets = self.doc.widgets(self.pno)
        target = None
        for w in widgets:
            r = w["rect"]
            if r[0] <= point[0] <= r[2] and r[1] <= point[1] <= r[3]:
                target = w
                break
        if target is None:
            self.hint_label.setText("Klik tepat di dalam kotak field formulir.")
            return
        dlg = FormFieldDialog(self, target)
        if dlg.exec() != FormFieldDialog.Accepted:
            return
        value = dlg.value()
        self._mutate("Isi form", lambda: self.doc.set_widget(self.pno, target["name"], value))
        self.hint_label.setText(f"Field “{target['label']}” diisi: {value}")

    # ---------------------------------------------------------------- annotations
    def _on_annot_selected(self, annot):
        if annot:
            content = (annot.get("content") or "").strip()
            self.annot_label.setText(
                f"{kind_label(annot['kind'])} · halaman {self.pno + 1}\n"
                f"{content[:140] if content else '(tanpa teks)'}")
            self.dock_props.raise_()
        else:
            self.annot_label.setText("Tidak ada anotasi terpilih.\nKlik anotasi di halaman.")
        self._update_annot_buttons()

    def _update_annot_buttons(self):
        has = self.view.selected_annot() is not None
        self.annot_props_btn.setEnabled(has)
        self.annot_del_btn.setEnabled(has)

    def _on_annot_changed(self, data):
        xref = data.get("xref")
        rect = data.get("rect")
        if xref is None or rect is None:
            return
        self._mutate(data.get("label") or "Ubah anotasi",
                     lambda: self.doc.update_annotation(self.pno, xref, rect=rect))
        self._refresh_comments()

    def _on_annot_deleted(self, data):
        xref = data.get("xref")
        if xref is None:
            return
        self._mutate("Hapus anotasi",
                     lambda: self.doc.delete_annotation(self.pno, xref))
        self._refresh_comments()

    def _open_annot_props(self, annot):
        dlg = AnnotPropsDialog(self, annot)
        if dlg.exec() != AnnotPropsDialog.Accepted:
            return
        values = dlg.values()
        self._mutate("Properti anotasi",
                     lambda: self.doc.update_annotation(self.pno, annot["xref"], **values))
        self._refresh_comments()

    def _edit_selected_annot(self):
        annot = self.view.selected_annot()
        if annot is not None:
            self._open_annot_props(annot)

    def _delete_selected_annot(self):
        annot = self.view.selected_annot()
        if annot is not None:
            self._on_annot_deleted({"xref": annot["xref"]})

    def _clear_annots(self):
        if not self.doc.is_open:
            return
        r = QMessageBox.question(
            self, "Hapus semua anotasi",
            f"Hapus semua anotasi di halaman {self.pno + 1}?",
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return

        def clear():
            for a in list(self.doc.annotations(self.pno)):
                self.doc.delete_annotation(self.pno, a["xref"])
        self._mutate("Hapus anotasi halaman", clear)
        self._refresh_comments()

    # ------------------------------------------------------------- side panels
    def _refresh_comments(self):
        if not hasattr(self, "comment_list"):
            return
        self.comment_list.clear()
        if not self.doc.is_open:
            return
        total = 0
        for pno in range(self.doc.page_count):
            for a in self.doc.annotations(pno):
                content = (a.get("content") or a.get("subject") or a.get("kind") or "").strip()
                item = QListWidgetItem(f"{kind_label(a['kind'])} · hal {pno + 1} — {content[:90]}")
                item.setData(Qt.UserRole, (pno, a["xref"]))
                item.setToolTip(content)
                self.comment_list.addItem(item)
                total += 1
        self.dock_comments.setWindowTitle(f"Komentar ({total})" if total else "Komentar")

    def _goto_comment(self, item):
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        pno, xref = data
        self.go_page(pno)
        self.view.select_annot(xref)

    def _delete_comment(self):
        item = self.comment_list.currentItem()
        if item is None:
            return
        pno, xref = item.data(Qt.UserRole)
        if pno != self.pno:
            self.go_page(pno)
        self._mutate("Hapus komentar",
                     lambda: self.doc.delete_annotation(pno, xref))
        self._refresh_comments()

    def _reply_comment(self):
        item = self.comment_list.currentItem()
        if item is None or not self.doc.is_open:
            return
        pno, xref = item.data(Qt.UserRole)
        dlg = TextPrompt(self, "Balas Komentar", "Tulis balasan untuk anotasi ini:")
        if dlg.exec() != TextPrompt.Accepted:
            return
        reply = dlg.text().strip()
        if not reply:
            return
        annots = self.doc.annotations(pno)
        cur = next((a for a in annots if a["xref"] == xref), None)
        old = (cur.get("content") or "").strip() if cur else ""
        new_content = f"{old}\n↳ {reply}" if old else f"↳ {reply}"
        self._mutate("Balas komentar",
                     lambda: self.doc.update_annotation(pno, xref, content=new_content))
        self._refresh_comments()

    def _refresh_layers(self):
        if not hasattr(self, "layer_list"):
            return
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        if not self.doc.is_open:
            self.layer_summary.setText("Tidak ada dokumen.")
            self.dock_layers.setWindowTitle("Layer (OCG)")
            self.layer_list.blockSignals(False)
            return
        layers = self.doc.layers()
        if not layers:
            self.layer_summary.setText("Dokumen ini tidak memiliki layer (OCG).")
            self.dock_layers.setWindowTitle("Layer (OCG)")
        else:
            self.layer_summary.setText(f"{len(layers)} layer ditemukan. Centang untuk menampilkan:")
            self.dock_layers.setWindowTitle(f"Layer ({len(layers)})")
            for lyr in layers:
                it = QListWidgetItem(lyr["name"])
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if lyr["on"] else Qt.Unchecked)
                it.setData(Qt.UserRole, lyr["xref"])
                self.layer_list.addItem(it)
        self.layer_list.blockSignals(False)

    def _on_layer_item_changed(self, item: QListWidgetItem):
        if not self.doc.is_open or item is None:
            return
        xref = item.data(Qt.UserRole)
        if xref is None:
            return
        on = item.checkState() == Qt.Checked
        if self.doc.set_layer_visible(int(xref), on):
            self.view.invalidate()
            self.thumbs.rebuild()
            if self._organize_mode:
                self.organize_view.rebuild()
            self.hint_label.setText(
                f"Layer “{item.text()}” {'ditampilkan' if on else 'disembunyikan'}.")

    def _refresh_fields(self):
        if not hasattr(self, "field_list"):
            return
        self.field_list.clear()
        if not self.doc.is_open:
            self.field_summary.setText("Tidak ada dokumen.")
            self.dock_fields.setWindowTitle("Field Formulir")
            return
        widgets = self.doc.all_widgets()
        if not widgets:
            self.field_summary.setText("Dokumen ini tidak memiliki field formulir.")
            self.dock_fields.setWindowTitle("Field Formulir")
            return
        self.field_summary.setText(f"{len(widgets)} field formulir:")
        self.dock_fields.setWindowTitle(f"Field Formulir ({len(widgets)})")
        for w in widgets:
            val = w.get("value")
            val_s = "✓" if val is True else ("☐" if val is False else str(val or ""))
            it = QListWidgetItem(f"Hal {w['page'] + 1} · {w['name']} ({w['type']}) = {val_s}")
            it.setData(Qt.UserRole, w)
            self.field_list.addItem(it)

    def _goto_field(self, item: QListWidgetItem):
        if item is None:
            return
        w = item.data(Qt.UserRole)
        if w and isinstance(w, dict):
            self.go_page(w["page"])

    def _edit_field_from_panel(self, item: QListWidgetItem):
        if item is None or not self.doc.is_open:
            return
        w = item.data(Qt.UserRole)
        if not w or not isinstance(w, dict):
            return
        pno = w["page"]
        self.go_page(pno)
        dlg = FormFieldDialog(self, w)
        if dlg.exec() != FormFieldDialog.Accepted:
            return
        val = dlg.value()
        self._mutate("Isi formulir", lambda: self.doc.set_widget(pno, w["name"], val))
        self._refresh_fields()

    def _refresh_outline(self):
        if not hasattr(self, "outline_tree"):
            return
        self.outline_tree.clear()
        if not self.doc.is_open:
            return
        stack: list[QTreeWidgetItem] = []
        for e in self.doc.outline():
            item = QTreeWidgetItem([e["title"]])
            item.setData(0, Qt.UserRole, e["page"])
            level = max(1, int(e.get("level") or 1))
            if level <= 1 or not stack:
                self.outline_tree.addTopLevelItem(item)
                stack = [item]
            else:
                parent = stack[min(level - 2, len(stack) - 1)]
                parent.addChild(item)
                stack = stack[:level - 1] + [item]
        self.outline_tree.expandAll()

    def _goto_outline(self, item, _col=0):
        if item is None:
            return
        page = item.data(0, Qt.UserRole)
        if page is not None:
            self.go_page(int(page))

    def _add_bookmark(self):
        if not self.doc.is_open:
            return
        title, ok = TextPrompt.get(self, "Bookmark baru",
                                   f"Judul untuk halaman {self.pno + 1}")
        if not ok or not title.strip():
            return
        entries = self.doc.outline()
        entries.append({"level": 1, "title": title.strip(), "page": self.pno})
        self._mutate("Tambah bookmark", lambda: self.doc.set_outline(entries))
        self._refresh_outline()

    def _remove_bookmark(self):
        item = self.outline_tree.currentItem()
        if item is None or not self.doc.is_open:
            return
        page = item.data(0, Qt.UserRole)
        title = item.text(0)
        entries = [e for e in self.doc.outline()
                   if not (e["title"] == title and e["page"] == page)]
        self._mutate("Hapus bookmark", lambda: self.doc.set_outline(entries))
        self._refresh_outline()

    # ------------------------------------------------------------ new features
    def search_replace(self):
        if not self.doc.is_open:
            return
        dlg = SearchReplaceDialog(self, self.doc, self.pno, self.search_edit.text())
        if dlg.exec() != SearchReplaceDialog.Accepted:
            return
        values = dlg.values()
        if not values["query"].strip():
            return
        self.doc.snapshot("Cari & ganti", self.pno)
        try:
            results = self.doc.search_replace(
                values["query"], values["replacement"], pages=values["pages"],
                match_case=values["match_case"], whole_word=values["whole_word"],
                regex=values["regex"])
        except Exception as exc:
            QMessageBox.critical(self, "Gagal mengganti", self._friendly(exc))
            return
        total = sum(n for _p, n in results)
        self.dirty = True
        self.view.invalidate()
        self.thumbs.rebuild()
        self._update_title()
        self._update_actions()
        self._update_status()
        self._refresh_comments()
        if total:
            pages = ", ".join(str(p + 1) for p, _n in results)
            QMessageBox.information(
                self, "Selesai",
                f"{total} teks diganti di halaman {pages}.\n"
                "Font asli tiap baris dipakai ulang.")
            self.hint_label.setText(f"{total} teks diganti.")
        else:
            QMessageBox.information(self, "Tidak ada", "Tidak ada teks yang cocok.")

    def watermark(self):
        if not self.doc.is_open:
            return
        dlg = WatermarkDialog(self, self.doc.page_count)
        if dlg.exec() != WatermarkDialog.Accepted:
            return
        values = dlg.values()
        if not values["text"].strip():
            return
        self._mutate("Watermark",
                     lambda: self.doc.watermark(**values))
        self.hint_label.setText("Watermark diterapkan.")

    def page_numbers(self):
        if not self.doc.is_open:
            return
        dlg = PageNumberDialog(self, self.doc.page_count)
        if dlg.exec() != PageNumberDialog.Accepted:
            return
        self._mutate("Nomor halaman",
                     lambda: self.doc.page_numbers(**dlg.values()))
        self.hint_label.setText("Nomor halaman ditambahkan.")

    def header_footer(self):
        if not self.doc.is_open:
            return
        dlg = HeaderFooterDialog(self, self.doc.page_count)
        if dlg.exec() != HeaderFooterDialog.Accepted:
            return
        self._mutate("Header & footer",
                     lambda: self.doc.header_footer(**dlg.values()))
        self.hint_label.setText("Header/footer ditambahkan.")

    def sanitize(self):
        if not self.doc.is_open:
            return
        r = QMessageBox.question(
            self, "Bersihkan dokumen",
            "Hapus metadata, JavaScript, file tertanam, teks tersembunyi, dan lampiran? "
            "Anotasi dan isi halaman tetap aman.",
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._mutate("Bersihkan dokumen", lambda: self.doc.sanitize(
            metadata=True, javascript=True, embedded=True, hidden=True,
            attachments=True, links=False, annotations=False))
        self.hint_label.setText("Metadata, JavaScript, dan file tersembunyi dibersihkan.")

    def ocr_document(self):
        if not self.doc.is_open:
            return
        if not self.doc.ocr_available():
            box = QMessageBox(self)
            box.setWindowTitle("OCR belum tersedia")
            box.setIcon(QMessageBox.Information)
            box.setText("Tidak ada mesin OCR yang bisa dipakai di komputer ini.")
            box.setInformativeText(
                "PDF Studio bisa memakai OCR bawaan Windows 10/11, atau "
                "Tesseract kalau dipasang.\n\n"
                "Kalau memakai Windows, pastikan bahasa OCR sudah terpasang "
                "(Settings → Time & language → Language & region).\n\n"
                "Alternatif: unduh Tesseract untuk Windows di\n"
                "https://github.com/UB-Mannheim/tesseract/wiki")
            box.exec()
            return
        engine = self.doc.ocr_engine_name() or "OCR"
        pages = self.doc.pages_without_text()
        if not pages:
            QMessageBox.information(
                self, "Sudah ada teks",
                "Semua halaman sudah punya layer teks. OCR tidak diperlukan.")
            return
        r = QMessageBox.question(
            self, "Jalankan OCR",
            f"{len(pages)} halaman belum punya layer teks (hasil scan?).\n"
            f"Mesin OCR: {engine}\n\n"
            "OCR akan menambahkan teks tak terlihat supaya halaman bisa "
            "dicari, disalin, dan diedit. Prosesnya bisa memakan waktu "
            "beberapa menit.\n\nLanjutkan?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r != QMessageBox.Yes:
            return
        self.doc.snapshot("OCR", self.pno)
        tmp_src = self.doc.temp_pdf()
        tmp_out = tmp_src + ".ocr.pdf"
        pw = self.doc.password
        total_doc_pages = self.doc.page_count

        def job(worker):
            wdoc = PdfDoc()
            try:
                wdoc.open(tmp_src, pw)

                def progress(i, total, pno):
                    return worker.report(i, total, f"OCR halaman {pno + 1} dari {total_doc_pages}…")

                done, words = wdoc.ocr_pages(pages, progress=progress)
                if done:
                    wdoc.save_as(tmp_out)
                return done, words
            finally:
                wdoc.cleanup()
                if os.path.exists(tmp_src):
                    try:
                        os.unlink(tmp_src)
                    except OSError:
                        pass

        ok, res = run_in_background(
            self, "OCR dokumen", "Menyiapkan OCR…", job,
            maximum=len(pages), cancelable=True)
        if not ok:
            if os.path.exists(tmp_out):
                try:
                    os.unlink(tmp_out)
                except OSError:
                    pass
            QMessageBox.critical(self, "OCR gagal", str(res))
            return
        done, words = res
        if not done or not os.path.exists(tmp_out):
            if os.path.exists(tmp_out):
                try:
                    os.unlink(tmp_out)
                except OSError:
                    pass
            self.hint_label.setText("OCR dibatalkan.")
            return
        try:
            self.doc._load_from(tmp_out, self.pno)
        finally:
            try:
                os.unlink(tmp_out)
            except OSError:
                pass
        self.dirty = True
        self.thumbs.rebuild()
        self.view.invalidate()
        self._update_title()
        self._update_actions()
        self._update_status()
        self._refresh_search_view()
        self.hint_label.setText(
            f"OCR selesai: {done} halaman, {words} kata dikenali.")
        QMessageBox.information(
            self, "OCR selesai",
            f"{done} halaman diproses dengan {words} kata.\n\n"
            "Sekarang halaman scan bisa dicari (Ctrl+F), disalin, dan diedit "
            "dengan alat Edit Teks. Simpan dengan Ctrl+S.")

    def _ocr_scanned_page(self, pno):
        """One-page OCR offered when Edit Text hits a scanned page."""
        if not self.doc.is_open:
            return
        if not self.doc.ocr_available():
            QMessageBox.information(
                self, "OCR belum tersedia",
                "Halaman ini hasil scan dan belum punya teks.\n\n"
                "Tidak ada mesin OCR yang bisa dipakai. OCR bawaan Windows "
                "10/11 butuh paket bahasa; alternatifnya pasang Tesseract.")
            return
        engine = self.doc.ocr_engine_name() or "OCR"
        r = QMessageBox.question(
            self, "Halaman hasil scan",
            f"Halaman {pno + 1} kelihatannya hasil scan (gambar, tanpa teks).\n"
            f"Mesin OCR: {engine}\n\n"
            "Jalankan OCR sekarang? Setelah selesai, klik lagi teksnya untuk "
            "diedit.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r != QMessageBox.Yes:
            return
        self.doc.snapshot("OCR halaman", pno)
        tmp_src = self.doc.temp_pdf()
        tmp_out = tmp_src + ".ocr.pdf"
        pw = self.doc.password

        def job(_worker):
            wdoc = PdfDoc()
            try:
                wdoc.open(tmp_src, pw)
                count = wdoc.ocr_page(pno)
                if count:
                    wdoc.save_as(tmp_out)
                return count
            finally:
                wdoc.cleanup()
                if os.path.exists(tmp_src):
                    try:
                        os.unlink(tmp_src)
                    except OSError:
                        pass

        ok, res = run_in_background(
            self, "OCR halaman", f"Menjalankan OCR halaman {pno + 1}…", job,
            maximum=0, cancelable=False)
        if not ok:
            if os.path.exists(tmp_out):
                try:
                    os.unlink(tmp_out)
                except OSError:
                    pass
            QMessageBox.critical(self, "OCR gagal", str(res))
            return
        count = res
        if not count or not os.path.exists(tmp_out):
            if os.path.exists(tmp_out):
                try:
                    os.unlink(tmp_out)
                except OSError:
                    pass
            QMessageBox.information(
                self, "OCR selesai",
                "Tidak ada teks yang bisa dikenali di halaman ini.")
            return
        try:
            self.doc._load_from(tmp_out, pno)
        finally:
            try:
                os.unlink(tmp_out)
            except OSError:
                pass
        self.dirty = True
        self.thumbs.update_page(pno)
        self.view.invalidate()
        self._update_title()
        self._update_actions()
        self._update_status()
        self._refresh_search_view()
        self.hint_label.setText(
            f"OCR halaman {pno + 1}: {count} kata. Klik teksnya untuk edit, "
            "lalu Ctrl+S untuk simpan.")
        QMessageBox.information(
            self, "OCR selesai",
            f"{count} kata dikenali di halaman {pno + 1}.\n\n"
            "Klik lagi teks di halaman pakai alat Edit Teks untuk "
            "mengubahnya. Simpan dengan Ctrl+S.")

    def remove_flattened_highlight(self):
        """Erase yellow/gray highlight or shadow bands baked into the page content."""
        if not self.doc.is_open:
            return
        bands = self.doc.highlight_bands(self.pno)
        if not bands:
            QMessageBox.information(
                self, "Tidak ada latar stabilo / shadow",
                "Di halaman ini tidak ada blok stabilo kuning atau shadow abu-abu "
                "yang menyatu dengan isi halaman.\n\nKalau stabilonya masih terlihat, "
                "kemungkinan itu anotasi: klik kanan di atasnya lalu pilih “Hapus semua "
                "anotasi di halaman”.")
            return
        r = QMessageBox.question(
            self, "Hapus latar stabilo / shadow",
            f"Ditemukan {len(bands)} blok latar stabilo / shadow di halaman {self.pno + 1}.\n"
            "Warna latar akan diubah jadi putih dan teks di atasnya tetap utuh.\n\n"
            "Lanjutkan?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r != QMessageBox.Yes:
            return
        result = {"ops": 0}

        def apply():
            result["ops"] = self.doc.remove_highlight_bands(self.pno)

        self._mutate("Hapus latar stabilo", apply)
        if not result["ops"]:
            QMessageBox.information(
                self, "Tidak berubah",
                "Latar stabilo / shadow tidak bisa diubah otomatis di halaman ini.")
            return
        self.hint_label.setText(
            f"Latar stabilo / shadow halaman {self.pno + 1} dibersihkan. "
            "Ctrl+S untuk simpan.")

    def batch(self):
        dlg = BatchDialog(self, self._last_folder)
        if dlg.exec() != BatchDialog.Accepted:
            return
        values = dlg.values()
        files = values["files"]
        if not files:
            QMessageBox.information(self, "Kosong", "Tambahkan minimal satu file PDF.")
            return
        out_dir = values["out"] or os.path.join(self._last_folder, "PDFStudio-Batch")
        os.makedirs(out_dir, exist_ok=True)

        def job(worker):
            done = 0
            errors = []
            tmpdir = tempfile.mkdtemp(prefix="pdfstudio_batch_")
            try:
                for i, path in enumerate(files):
                    if not worker.report(i, len(files), f"{os.path.basename(path)} ({i + 1}/{len(files)})"):
                        break
                    try:
                        doc = PdfDoc(tmpdir)
                        doc.open(path)
                        stem = os.path.splitext(os.path.basename(path))[0]
                        if values["watermark"] and values["wm_text"].strip():
                            doc.watermark(values["wm_text"])
                        if values["numbers"]:
                            doc.page_numbers()
                        if values["flatten"]:
                            try:
                                doc.doc.bake(annots=True, widgets=True)
                            except Exception:
                                pass
                        out = os.path.join(out_dir, f"{stem}_pdfstudio.pdf")
                        if values["protect"] and values["password"]:
                            doc.protect(out, values["password"], values["password"])
                        else:
                            doc.save_as(out, compress=values["compress"])
                        if values["png"]:
                            png_dir = os.path.join(out_dir, f"{stem}_png")
                            os.makedirs(png_dir, exist_ok=True)
                            doc.export_all_png(png_dir, dpi=150)
                        doc.close()
                        done += 1
                    except Exception as exc:
                        errors.append(f"{os.path.basename(path)}: {self._friendly(exc)}")
                worker.report(len(files), len(files), "Selesai")
                return done, errors
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)

        ok, res = run_in_background(
            self, "Batch", "Memproses file…", job,
            maximum=len(files), cancelable=True)
        if not ok:
            QMessageBox.critical(self, "Batch gagal", str(res))
            return
        done, errors = res
        msg = f"{done} dari {len(files)} file selesai.\nFolder: {out_dir}"
        if errors:
            msg += "\n\nGagal:\n" + "\n".join(errors[:8])
        QMessageBox.information(self, "Batch selesai", msg)
        self._last_folder = out_dir

    def compare(self):
        if not self.doc.is_open:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Pilih PDF pembanding",
                                              self._last_folder, "PDF (*.pdf)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = self.doc.compare_text(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Gagal membandingkan", self._friendly(exc))
            return
        QApplication.restoreOverrideCursor()
        CompareDialog(self, result, self.doc.path or "", path).exec()

    def attachments(self):
        if not self.doc.is_open:
            return
        dlg = AttachmentsDialog(self, self.doc)
        dlg.exec()
        if getattr(dlg, "changed", False):
            self.dirty = True
            self._update_title()
            self._update_actions()
            self.hint_label.setText("Lampiran diperbarui. Ctrl+S untuk simpan.")

    def insert_pages_pdf(self):
        if not self.doc.is_open:
            return
        dlg = InsertPagesDialog(self, self._last_folder, self.doc.page_count)
        if dlg.exec() != InsertPagesDialog.Accepted:
            return
        values = dlg.values()
        if not values["path"] or not os.path.exists(values["path"]):
            QMessageBox.warning(self, "File tidak ada", "Pilih file PDF sumber dulu.")
            return
        try:
            probe = fitz.open(values["path"])
            count = probe.page_count
            probe.close()
        except Exception as exc:
            QMessageBox.critical(self, "Gagal", self._friendly(exc))
            return
        pages = parse_pages(values["pages_text"], count)
        if not pages:
            QMessageBox.warning(self, "Halaman kosong", "Nomor halaman sumber tidak valid.")
            return
        self._mutate("Sisip halaman",
                     lambda: self.doc.insert_pages_from(values["path"], pages, values["at"]),
                     refresh=False)
        self.thumbs.rebuild()
        self._sync_page(values["at"])
        self._refresh_comments()
        self.hint_label.setText(f"{len(pages)} halaman disisipkan.")

    def duplicate_page(self):
        if not self.doc.is_open:
            return
        self._mutate("Duplikat halaman", lambda: self.doc.duplicate_page(self.pno),
                     refresh=False)
        self.thumbs.rebuild()
        self._sync_page(self.pno + 1)
        self.hint_label.setText("Halaman diduplikat.")

    def _thumb_move(self, src, dst):
        if not self.doc.is_open:
            return
        self._mutate("Pindah halaman", lambda: self.doc.move_page(src, dst),
                     refresh=False)
        self.thumbs.rebuild()
        if self._organize_mode:
            self.organize_view.rebuild()
        self._sync_page(dst)

    def toggle_organize_mode(self, on=None):
        if not self.doc.is_open:
            self._organize_mode = False
            self.act_organize.setChecked(False)
            self.center_stack.setCurrentWidget(self.scroll)
            return
        if on is None:
            on = not self._organize_mode
        self._organize_mode = bool(on)
        self.act_organize.setChecked(self._organize_mode)
        if self._organize_mode:
            self.organize_view.set_document(self.doc)
            self.center_stack.setCurrentWidget(self.organize_view)
            self.hint_label.setText(
                "Kelola Halaman — klik/Ctrl+klik/Shift+klik pilih banyak, seret untuk pindah, klik ganda buka halaman.")
        else:
            self.center_stack.setCurrentWidget(self.scroll)
            self.view.invalidate()
            self._sync_page(min(self.pno, max(0, self.doc.page_count - 1)))
            self._update_status()

    def _on_organize_page_activated(self, pno: int):
        self.toggle_organize_mode(False)
        self.go_page(pno)

    def _on_organize_move(self, src: int, dst: int):
        if not self.doc.is_open:
            return
        self._mutate("Pindah halaman", lambda: self.doc.move_page(src, dst),
                     refresh=False)
        self.thumbs.rebuild()
        self.organize_view.rebuild()
        self._sync_page(dst)

    def _on_organize_batch(self, action: str, pages: list[int]):
        if not self.doc.is_open:
            return
        if action in ("rotate_l", "rotate_r"):
            if not pages:
                return
            delta = -90 if action == "rotate_l" else 90
            def _rot():
                for p in pages:
                    self.doc.rotate_page(p, delta)
            self._mutate(f"Putar {len(pages)} halaman", _rot, refresh=False)
            self.thumbs.rebuild()
            self.organize_view.rebuild()
        elif action == "insert_blank":
            at = (pages[-1] + 1) if pages else self.doc.page_count
            self._mutate("Sisip halaman kosong", lambda: self.doc.insert_blank(at),
                         refresh=False)
            self.thumbs.rebuild()
            self.organize_view.rebuild()
        elif action == "insert_pdf":
            self.insert_pages_pdf()
            if self._organize_mode:
                self.organize_view.rebuild()
        elif action == "duplicate":
            if not pages:
                return
            def _dup():
                for p in reversed(pages):
                    self.doc.duplicate_page(p)
            self._mutate(f"Duplikat {len(pages)} halaman", _dup, refresh=False)
            self.thumbs.rebuild()
            self.organize_view.rebuild()
        elif action == "extract":
            if not pages:
                return
            out, _ = QFileDialog.getSaveFileName(
                self, "Ekstrak halaman terpilih",
                self._suggest_out("ekstrak.pdf"), "PDF (*.pdf)")
            if not out:
                return
            try:
                self.doc.extract(pages, out)
                self.hint_label.setText(f"{len(pages)} halaman diekstrak ke {os.path.basename(out)}.")
            except Exception as exc:
                QMessageBox.critical(self, "Gagal", self._friendly(exc))
        elif action == "delete":
            if not pages or self.doc.page_count - len(pages) < 1:
                QMessageBox.information(self, "Tidak bisa hapus",
                                        "Dokumen harus menyisakan minimal 1 halaman.")
                return
            if QMessageBox.question(
                self, "Hapus halaman",
                f"Hapus {len(pages)} halaman terpilih?",
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes:
                return
            def _del():
                for p in reversed(pages):
                    self.doc.delete_page(p)
            self._mutate(f"Hapus {len(pages)} halaman", _del, refresh=False)
            self.pno = min(self.pno, self.doc.page_count - 1)
            self.thumbs.rebuild()
            self.organize_view.rebuild()

    def _thumb_action(self, action, row):
        if not self.doc.is_open:
            return
        self.go_page(row)
        if action == "rotate_l":
            self.rotate_page(-90)
        elif action == "rotate_r":
            self.rotate_page(90)
        elif action == "duplicate":
            self.duplicate_page()
        elif action == "delete":
            self.delete_page()
        elif action == "insert":
            self.insert_page()

    def _choose_stamp(self):
        dlg = StampDialog(self)
        if dlg.exec() != StampDialog.Accepted:
            self._stamp_values = None
            return
        self._stamp_values = dlg.values()
        self.hint_label.setText("Klik atau tarik kotak di halaman untuk menempel stempel.")

    def command_palette(self):
        cmds = []
        for key, act in self.tool_actions.items():
            cmds.append({
                "title": f"Alat: {act.text()}",
                "hint": TOOL_HINTS.get(key, ""),
                "shortcut": "",
                "run": lambda _c=False, k=key: self._set_tool(k),
            })
        for attr in dir(self):
            if not attr.startswith("act_"):
                continue
            act = getattr(self, attr, None)
            if not isinstance(act, QAction):
                continue
            text = act.text().replace("&", "").replace("…", "").strip()
            if not text:
                continue
            cmds.append({
                "title": text,
                "shortcut": act.shortcut().toString(),
                "run": act.trigger,
            })
        CommandPalette(self, cmds).exec()

    def zoom_to_selection(self):
        if not self.doc.is_open:
            return
        bbox = self.view.selection_bbox()
        if not bbox:
            self.hint_label.setText("Pilih dulu teks atau anotasi yang mau di-zoom.")
            return
        vp = self.scroll.viewport().size()
        w = max(1.0, bbox[2] - bbox[0])
        h = max(1.0, bbox[3] - bbox[1])
        z = min((vp.width() - 60) / w, (vp.height() - 60) / h)
        self._set_zoom(max(0.2, min(6.0, z)))
        self.hint_label.setText("Zoom ke seleksi.")

    def toggle_read_mode(self, on=None):
        if on is None:
            on = not self._read_mode
        self._read_mode = bool(on)
        self.act_read.setChecked(self._read_mode)
        for widget in (self.menuBar(), self.right_rail):
            widget.setVisible(not self._read_mode)
        if self._read_mode:
            self.tool_rail.setVisible(False)
        self.doc_tabs_bar.setVisible(not self._read_mode and bool(self._tabs))
        for dock in (self.dock_tools, self.dock_thumbs, self.dock_props,
                     self.dock_comments, self.dock_outline, self.dock_fields,
                     self.dock_layers, self.dock_search):
            dock.setVisible(not self._read_mode)
        self.view.set_read_mode(self._read_mode)
        if self._read_mode:
            self.context_bar.setVisible(False)
            self.find_bar.setVisible(False)
            self.sig_banner.hide()
            self.hint_label.setText("Mode baca — F11 untuk kembali.")
        else:
            self._set_tool("select")
            self._refresh_sig_banner()
        self._sync_page(self.pno)

    def set_theme(self, name):
        name = "light" if name == "light" else "dark"
        self._settings.setValue("theme", name)
        theme.set_current_theme(name)
        self.act_dark.setChecked(name == "dark")
        self.act_light.setChecked(name == "light")
        self.setStyleSheet(theme.THEME if name == "dark" else theme.LIGHT_THEME)
        self._refresh_icons()
        self.view.set_theme(name)
        self.zoom_box.lineEdit().setAlignment(Qt.AlignCenter)

    def _friendly(self, exc):
        if isinstance(exc, PermissionError):
            return ("File sedang dipakai aplikasi lain, atau kamu tidak punya izin "
                    "menulis ke folder itu.")
        if isinstance(exc, FileNotFoundError):
            return "File tidak ditemukan. Mungkin sudah dipindah atau dihapus."
        if isinstance(exc, IsADirectoryError):
            return "Yang dipilih adalah folder, bukan file."
        text = str(exc).strip()
        return text or exc.__class__.__name__

    # ---------------------------------------------------------- signature flow
    def new_signature(self):
        self._sig_image_path = None
        self._make_signature()

    def new_image(self):
        self._pending_image = None
        self._pick_image()

    def _make_signature(self):
        dlg = SignatureDialog(self)
        if dlg.exec() != SignatureDialog.Accepted:
            self._set_tool("select")
            return
        path = dlg.result_path()
        if not path or not os.path.exists(path):
            img = dlg.result_image()
            if img.isNull():
                self._set_tool("select")
                return
            try:
                path = sigstore.save_signature_image(img)
            except Exception:
                path = os.path.join(tempfile.gettempdir(), "pdfstudio_signature.png")
                if not img.save(path, "PNG"):
                    self._set_tool("select")
                    return
        self._sig_image_path = path
        self._set_tool("signature")
        self.hint_label.setText("Tarik kotak di halaman untuk menempatkan tanda tangan.")

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih gambar", self._last_folder,
                                              "Gambar (*.png *.jpg *.jpeg *.webp *.bmp);;Semua file (*)")
        if not path:
            self._set_tool("select")
            return
        self._pending_image = path
        self._set_tool("image")
        self.hint_label.setText("Tarik kotak di halaman untuk menempatkan gambar.")

    def start_digital_sign(self):
        if not self.doc.is_open:
            return
        dlg = DigitalSignDialog(self)
        if dlg.exec() != DigitalSignDialog.Accepted:
            self._set_tool("select")
            return
        stem = os.path.splitext(os.path.basename(self.doc.path or "dokumen.pdf"))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan PDF tertanda tangan",
            os.path.join(self._last_folder, f"{stem}_signed.pdf"), "PDF (*.pdf)")
        if not path:
            self._set_tool("select")
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._pending_sign = (dlg.values(), path)
        self._set_tool("cert")
        self.hint_label.setText("Tarik kotak di halaman untuk menempatkan tanda tangan digital.")

    def _place_signature_field(self, rect):
        if not self._pending_sign:
            return
        values, path = self._pending_sign
        use_orig = bool(
            self.doc.path and os.path.exists(self.doc.path)
            and os.path.abspath(self.doc.path) != os.path.abspath(path)
            and not self.dirty
        )
        tmp_src = None if use_orig else self.doc.temp_pdf()
        src_path = self.doc.path if use_orig else tmp_src
        pw = self.doc.password
        pno = self.pno

        def job(_worker):
            wdoc = PdfDoc()
            try:
                wdoc.open(src_path, pw)
                wdoc.digital_sign(path, pno, rect, values["pfx"],
                                  values["password"], values["reason"],
                                  values["location"])
            finally:
                wdoc.cleanup()
                if tmp_src and os.path.exists(tmp_src):
                    try:
                        os.unlink(tmp_src)
                    except OSError:
                        pass

        ok, res = run_in_background(
            self, "Tanda Tangan Digital", "Menandatangani dokumen…", job,
            maximum=0, cancelable=False)
        self._pending_sign = None
        self._set_tool("select")
        if not ok:
            QMessageBox.critical(self, "Gagal menandatangani", str(res))
            return
        r = QMessageBox.question(
            self, "Tanda tangan digital berhasil",
            f"PDF tertanda tangan disimpan:\n{path}\n\nBuka di tab baru sekarang?",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self.open_file(path)
        if not self.dirty:
            self.hint_label.setText(f"Tertanda tangan: {path}")

    # ------------------------------------------------------------- misc slots
    def show_about(self):
        AboutDialog(self, VERSION).exec()

    def show_shortcuts(self):
        ShortcutsDialog(self).exec()

    # ----------------------------------------------------------------- events
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            for u in ev.mimeData().urls():
                low = u.toLocalFile().lower()
                if low.endswith((".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                    ev.acceptProposedAction()
                    return
        ev.ignore()

    def dropEvent(self, ev):
        pdfs = []
        imgs = []
        for u in ev.mimeData().urls():
            p = u.toLocalFile()
            low = p.lower()
            if low.endswith(".pdf"):
                pdfs.append(p)
            elif low.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                imgs.append(p)
        for p in pdfs:
            self.open_file(p)
        if imgs:
            self.create_from_images(imgs)

    def closeEvent(self, ev):
        self._save_active_tab_state()
        for idx, tab in enumerate(list(self._tabs)):
            if tab.dirty:
                if idx != self._active_tab:
                    self._activate_tab(idx)
                if not self._confirm_discard():
                    ev.ignore()
                    return
        self._save_view_state()
        self._settings.setValue("geometry", self.saveGeometry())
        if self._docks_initialized:
            self._settings.setValue("dockState_v2", self.saveState())
        for tab in self._tabs:
            recovery.discard_snapshot(tab.doc.path)
            try:
                tab.doc.cleanup()
            except Exception:
                pass
        self._tabs.clear()
        self._active_tab = -1
        try:
            self.doc.cleanup()
        except Exception:
            pass
        ev.accept()

