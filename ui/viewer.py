"""Page canvas: rendering, text selection, annotation gestures."""
from __future__ import annotations

import hashlib

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QSize, QPoint, QTimer
from PySide6.QtGui import (QColor, QCursor, QImage, QPainter, QPen, QBrush,
                           QPainterPath, QKeyEvent, QFont, QFontMetricsF,
                           QFontDatabase, QTextBlockFormat, QTextCharFormat,
                           QTextCursor)
from PySide6.QtWidgets import QWidget, QTextEdit, QFrame, QMenu, QApplication

TOOL_CURSORS = {
    "select": Qt.IBeamCursor,
    "hand": Qt.OpenHandCursor,
    "note": Qt.PointingHandCursor,
    "form": Qt.PointingHandCursor,
    "text": Qt.CrossCursor,
    "edit_text": Qt.IBeamCursor,
    "line": Qt.CrossCursor,
    "arrow": Qt.CrossCursor,
    "callout": Qt.CrossCursor,
    "stamp": Qt.PointingHandCursor,
    "rect": Qt.CrossCursor,
    "ellipse": Qt.CrossCursor,
}

DRAG_TOOLS = {"highlight", "underline", "strikeout", "squiggly", "rect",
              "ellipse", "text", "edit_text", "signature", "cert", "image",
              "redact", "form", "add_form", "line", "arrow", "callout"}

_EDITOR_FONTS: dict[str, str] = {}


class InlineTextEditor(QTextEdit):
    """Seamless on-canvas paragraph editor drawn directly over the PDF page."""

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent, info, zoom, click_point=None, offset=(0.0, 0.0)):
        super().__init__(parent)
        self._done = False
        self._ox, self._oy = float(offset[0]), float(offset[1])
        self._zoom = float(zoom)
        self.setFrameShape(QFrame.NoFrame)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        font, px_size = self._load_font(info, zoom)
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.document().setDocumentMargin(0)

        color = info.get("color") or (0, 0, 0)
        bg = info.get("bg") or (1, 1, 1)
        color_mode = getattr(parent, "color_mode", "normal")
        if color_mode == "night":
            color = tuple(1.0 - c for c in color)
            bg = tuple(1.0 - c for c in bg)
        elif color_mode == "sepia":
            bg = (bg[0] * 246 / 255.0, bg[1] * 236 / 255.0, bg[2] * 212 / 255.0)
        qt_color = QColor.fromRgbF(*[max(0.0, min(1.0, c)) for c in color])
        qt_bg = QColor.fromRgbF(*[max(0.0, min(1.0, c)) for c in bg])
        import re as _re
        safe_fam = _re.sub(r"[^a-zA-Z0-9 _\-]", "", font.family()) or "Segoe UI"
        self.setStyleSheet(
            "QTextEdit {"
            f" background: rgb({qt_bg.red()},{qt_bg.green()},{qt_bg.blue()});"
            f" color: rgb({qt_color.red()},{qt_color.green()},{qt_color.blue()});"
            f" font-family: '{safe_fam}';"
            f" font-size: {px_size}px;"
            f" font-weight: {'bold' if font.bold() else 'normal'};"
            f" font-style: {'italic' if font.italic() else 'normal'};"
            " border: 1px dashed rgba(76, 141, 255, 190); border-radius: 0px; padding: 0px;"
            " selection-background-color: #b9d4ff; selection-color: #111; }")

        x0, y0, x1, y1 = info["rect"]
        fm = QFontMetricsF(font)
        baseline = info.get("baseline")
        # Align Qt text baseline tightly with the PDF baseline (compensating 1px border).
        base_top = self._oy + (baseline if baseline is not None else y0) * zoom - fm.ascent() - 1
        rect_top = self._oy + y0 * zoom - 1
        top = base_top if baseline is not None else rect_top
        orig_bottom = self._oy + y1 * zoom + 2
        self._min_h = max(int(round(orig_bottom - top)), int(round(fm.height())) + 4)

        page_box = parent._page_box(parent.pno)
        page_right = page_box["x"] + page_box["w"] - 4
        left = self._ox + x0 * zoom - 1
        width = max(56.0, (x1 - x0) * zoom + 4.0)
        max_w = max(56.0, page_right - left)
        width = min(width, max_w)
        self._content_w = max(20.0, width - 2.0)

        gap_pt = float(info.get("line_gap") or 0.0)
        self._line_height_px = gap_pt * zoom if gap_pt > 0 else 0.0
        self._indent_px = float(info.get("indent") or 0.0) * zoom
        self._align = info.get("align") or "left"
        self._base_bold = bool(info.get("bold"))
        self._base_italic = bool(info.get("italic"))
        rich_runs = info.get("rich_runs")
        if rich_runs:
            self.clear()
            cur = self.textCursor()
            for chunk, rb, ri in rich_runs:
                cf = QTextCharFormat()
                cf.setFontWeight(QFont.Bold if rb else QFont.Normal)
                cf.setFontItalic(bool(ri))
                cur.insertText(chunk, cf)
        else:
            self.setPlainText(info.get("text") or "")
        self._apply_line_height()
        self.document().setModified(False)

        self.setGeometry(int(round(left)), int(round(top)),
                         int(round(width)), self._min_h)
        self._fit_height()
        self.textChanged.connect(self._fit_height)
        if click_point is not None:
            lx = max(0, int(click_point[0] * zoom - x0 * zoom))
            ly = max(0, int(self._oy + click_point[1] * zoom - top))
            self.setTextCursor(self.cursorForPosition(QPoint(lx, ly)))
        else:
            self.moveCursor(QTextCursor.End)

    @staticmethod
    def _resolve_system_font(display: str) -> str | None:
        raw = (display or "").strip()
        if not raw:
            return None
        low = raw.lower().replace(" ", "").replace("-", "").replace("_", "")
        aliases = {
            "segoeui": "Segoe UI",
            "timesnewroman": "Times New Roman",
            "timesnewromanpsmt": "Times New Roman",
            "timesnewromanps": "Times New Roman",
            "times": "Times New Roman",
            "arialmt": "Arial",
            "arial": "Arial",
            "helvetica": "Arial",
            "couriernew": "Courier New",
            "couriernewpsmt": "Courier New",
            "courier": "Courier New",
            "calibri": "Calibri",
            "cambria": "Cambria",
            "georgia": "Georgia",
            "verdana": "Verdana",
            "tahoma": "Tahoma",
            "trebuchetms": "Trebuchet MS",
            "garamond": "Garamond",
            "bookantiqua": "Book Antiqua",
            "palatinolinotype": "Palatino Linotype",
            "consolas": "Consolas",
            "comicsansms": "Comic Sans MS",
        }
        installed = set(QFontDatabase.families())
        if raw in installed:
            return raw
        mapped = aliases.get(low)
        if mapped and mapped in installed:
            return mapped
        # Insert spaces before capitals (e.g. "SegoeUI" -> "Segoe UI")
        import re
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)
        if spaced in installed:
            return spaced
        return None

    def _load_font(self, info, zoom: float) -> tuple[QFont, int]:
        font = QFont()
        display = info.get("font_display") or info.get("font") or "Segoe UI"
        family = self._resolve_system_font(display)
        if not family:
            buf = info.get("font_buffer")
            if buf:
                key = hashlib.md5(buf).hexdigest()
                cached = _EDITOR_FONTS.get(key)
                if cached is None:
                    from PySide6.QtCore import QByteArray
                    fid = QFontDatabase.addApplicationFontFromData(QByteArray(buf))
                    fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                    cached = fams[0] if fams else ""
                    _EDITOR_FONTS[key] = cached
                if cached:
                    family = cached
        if not family:
            family = self._resolve_system_font(info.get("font") or "") or "Segoe UI"
        font.setFamily(family)
        size = float(info.get("size") or 10.0)
        px = max(6, int(round(size * zoom)))
        font.setPixelSize(px)
        if info.get("bold"):
            font.setBold(True)
        if info.get("italic"):
            font.setItalic(True)
        return font, px

    def _apply_line_height(self):
        fm = QFontMetricsF(self.font())
        cur = self.textCursor()
        cur.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        if self._line_height_px >= fm.height() * 0.9:
            fmt.setLineHeight(float(self._line_height_px), int(QTextBlockFormat.FixedHeight.value))
        if self._indent_px > 1.0:
            fmt.setTextIndent(float(self._indent_px))
        if self._align == "justify":
            fmt.setAlignment(Qt.AlignJustify)
        elif self._align == "center":
            fmt.setAlignment(Qt.AlignHCenter)
        elif self._align == "right":
            fmt.setAlignment(Qt.AlignRight)
        cur.mergeBlockFormat(fmt)

    def _fit_height(self):
        doc = self.document()
        doc.setTextWidth(self._content_w)
        doc_h = int(round(doc.size().height())) + 4
        h = max(self._min_h, doc_h)
        if self.height() != h:
            self.setFixedHeight(max(18, h))

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fit_height()
        self.viewport().update()

    def extract_rich_runs(self) -> list[tuple[str, bool, bool]]:
        """Extract contiguous (text, bold, italic) runs from the QTextDocument."""
        runs: list[list] = []
        blk = self.document().begin()
        first_blk = True
        while blk.isValid():
            if not first_blk:
                if runs:
                    runs[-1][0] += "\n"
                else:
                    runs.append(["\n", self._base_bold, self._base_italic])
            first_blk = False
            it = blk.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    t = frag.text().replace("\u2028", "\n").replace("\u2029", "\n")
                    if t:
                        cf = frag.charFormat()
                        w = cf.fontWeight()
                        rb = (w >= QFont.Bold) if w > 0 else self._base_bold
                        ri = cf.fontItalic() if cf.hasProperty(QTextCharFormat.FontItalic) else self._base_italic
                        if runs and runs[-1][1] == rb and runs[-1][2] == ri:
                            runs[-1][0] += t
                        else:
                            runs.append([t, rb, ri])
                it += 1
            blk = blk.next()
        return [(c, b, it) for c, b, it in runs if c]

    def _toggle_char_style(self, *, bold: bool = False, italic: bool = False):
        cur = self.textCursor()
        cf = cur.charFormat()
        upd = QTextCharFormat()
        if bold:
            is_b = cf.fontWeight() >= QFont.Bold
            upd.setFontWeight(QFont.Normal if is_b else QFont.Bold)
        if italic:
            upd.setFontItalic(not cf.fontItalic())
        cur.mergeCharFormat(upd)
        self.mergeCurrentCharFormat(upd)

    def keyPressEvent(self, ev: QKeyEvent):
        if (ev.modifiers() & Qt.ControlModifier) and ev.key() == Qt.Key_B:
            self._toggle_char_style(bold=True)
            return
        if (ev.modifiers() & Qt.ControlModifier) and ev.key() == Qt.Key_I:
            self._toggle_char_style(italic=True)
            return
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            if ev.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(ev)
                self._apply_line_height()
                self._fit_height()
            else:
                self._finish(True)
            return
        if ev.key() == Qt.Key_Escape:
            self._finish(False)
            return
        super().keyPressEvent(ev)
        self._fit_height()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if ev.reason() in (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
            return
        if not self._done:
            self._finish(True)

    def _finish(self, save: bool):
        if self._done:
            return
        self._done = True
        text = self.toPlainText()
        self.hide()
        if save:
            self.committed.emit(text)
        else:
            self.cancelled.emit()
        self.deleteLater()

    def commit_now(self):
        self._finish(True)

    def cancel_now(self):
        self._finish(False)



class PageView(QWidget):
    action = Signal(str, dict)          # tool gesture -> controller
    status = Signal(str)
    selectionChanged = Signal(str)
    zoomRequested = Signal(float)
    pageRequested = Signal(int)         # +1 next page, -1 previous page (legacy wheel mode)
    pageActivated = Signal(int)         # page under the user / viewport centre changed
    inlineCommit = Signal(dict)         # {"info": ..., "text": ...}
    inlineCancel = Signal()
    annotSelected = Signal(object)      # annotation dict or None
    annotChanged = Signal(dict)         # {"xref": ..., "rect": ..., "label": ...}
    annotDeleted = Signal(dict)         # {"xref": ...}
    annotProps = Signal(object)         # {"xref": ...}
    scanNeedsOcr = Signal(int)          # scanned page clicked with Edit Text
    linkClicked = Signal(dict)          # {"uri": ..., "page": ..., "rect": ...}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.doc = None
        self.pno = 0
        self.zoom = 1.0
        self.tool = "select"
        self.tool_color = (1.0, 0.85, 0.0)
        self.tool_width = 2.0
        self.tool_fontsize = 12.0
        self.tool_font = "Helvetica"
        self._theme_name = "dark"
        self.layout_mode = "continuous"      # continuous | single | two_page
        self.color_mode = "normal"           # normal | night | sepia
        self._cache: dict = {}
        self._links_cache: dict[int, list[dict]] = {}
        self._hover_link = None
        self._img = None
        self._layout: list[dict] = []       # continuous page strip geometry
        self._page_count = 0
        self._gap = 18
        self._render_queue: list[tuple] = []
        self._failed: set = set()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(0)
        self._render_timer.timeout.connect(self._render_next)
        self._drag_start = None
        self._drag_cur = None
        self._press_pos = None
        self._panning = False
        self._pan_last = None
        self._wheel_acc = 0
        self._ink = []
        self._search_hits: list[QRectF] = []
        self._search_cur = -1
        self._sel_rects: list[QRectF] = []
        self._widget_rects: list[QRectF] = []
        self._page_w = 0.0
        self._page_h = 0.0
        self._sel_text = ""
        self._editor = None
        self._annots = []
        self._sel_annot = None
        self._hover_info = None
        self._hover_point = None
        self._hover_pno = None
        self._annot_drag = None
        self.read_mode = False
        self.setCursor(QCursor(TOOL_CURSORS["select"]))

    # ------------------------------------------------------------- lifecycle
    def set_document(self, doc):
        self.cancel_inline()
        self.doc = doc
        self.pno = 0
        self._cache.clear()
        self._links_cache.clear()
        self._hover_link = None
        self._img = None
        self._layout = []
        self._render_queue = []
        self._sel_rects = []
        self._search_hits = []
        self._search_cur = -1
        self._widget_rects = []
        self._annots = []
        self._sel_annot = None
        if doc is not None:
            self._page_count = doc.page_count
            self._update_size()

    def set_theme(self, name: str):
        self._theme_name = "light" if name == "light" else "dark"
        self.update()

    def set_layout_mode(self, mode: str):
        if mode not in ("continuous", "single", "two_page"):
            return
        if self.layout_mode == mode:
            return
        self.cancel_inline()
        self.layout_mode = mode
        self._update_size()
        self.scroll_to_page(self.pno)
        self.update()

    def set_color_mode(self, mode: str):
        if mode not in ("normal", "night", "sepia"):
            return
        if self.color_mode == mode:
            return
        self.color_mode = mode
        self._cache.clear()
        self._render_queue = []
        self._failed = set()
        self.refresh()

    def _apply_color_mode(self, img: QImage) -> QImage:
        if self.color_mode == "night":
            out = img.copy()
            out.invertPixels(QImage.InvertRgb)
            return out
        if self.color_mode == "sepia":
            out = img.copy()
            p = QPainter(out)
            p.setCompositionMode(QPainter.CompositionMode_Multiply)
            p.fillRect(out.rect(), QColor(246, 236, 212))
            p.end()
            return out
        return img

    def _links_for(self, pno: int) -> list[dict]:
        if self.doc is None or pno < 0 or pno >= self._page_count:
            return []
        cached = self._links_cache.get(pno)
        if cached is None:
            try:
                cached = self.doc.links(pno)
            except Exception:
                cached = []
            self._links_cache[pno] = cached
        return cached

    def _link_at(self, pt, pno: int | None = None) -> dict | None:
        pno = self.pno if pno is None else int(pno)
        x, y = pt
        for lk in self._links_for(pno):
            r = lk.get("rect")
            if not r:
                continue
            if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                if lk.get("uri") or lk.get("page") is not None:
                    return lk
        return None

    def set_page(self, pno: int):
        self.cancel_inline()
        self.pno = max(0, min(int(pno), max(0, self._page_count - 1)))
        self._wheel_acc = 0
        self._sel_rects = []
        self._ink = []
        self._drag_start = self._drag_cur = None
        self._annots = []
        self._sel_annot = None
        self._hover_info = None
        self._hover_pno = None
        self._hover_link = None
        self.annotSelected.emit(None)
        if self.layout_mode == "single":
            self._update_size()
        self.refresh()
        self.scroll_to_page(self.pno)
        self.pageActivated.emit(self.pno)

    def _page_box(self, pno: int | None = None):
        pno = self.pno if pno is None else int(pno)
        for b in self._layout:
            if b["pno"] == pno:
                return b
        return {"pno": pno, "x": 0.0, "y": 0.0,
                "w": self._page_w * self.zoom, "h": self._page_h * self.zoom}

    def page_at(self, pt) -> int:
        """Page under a widget-space point (or the nearest one)."""
        if not self._layout:
            return 0
        x = float(pt.x())
        y = float(pt.y())
        for box in self._layout:
            if (box["x"] <= x <= box["x"] + box["w"]
                    and box["y"] <= y <= box["y"] + box["h"]):
                return box["pno"]
        row_matches = [b for b in self._layout if b["y"] <= y <= b["y"] + b["h"]]
        candidates = row_matches or self._layout
        return min(
            candidates,
            key=lambda b: ((b["x"] + b["w"] / 2) - x) ** 2
            + ((b["y"] + b["h"] / 2) - y) ** 2,
        )["pno"]

    def activate_page(self, pno: int) -> None:
        pno = max(0, min(int(pno), max(0, self._page_count - 1)))
        if pno != self.pno:
            self.cancel_inline()
            self.pno = pno
            self._sel_rects = []
            self._sel_annot = None
            self._hover_info = None
            self._hover_pno = None
            self._annots = []
            self.refresh_annots()
            self.annotSelected.emit(None)
            try:
                self.page_pixmap(self.pno)
            except Exception:
                pass
            self.update()
        self.pageActivated.emit(self.pno)

    def scroll_to_page(self, pno: int, margin: int = 18) -> None:
        sa = self._scroll_area()
        if sa is None or not self._layout:
            return
        box = self._page_box(pno)
        sa.verticalScrollBar().setValue(int(max(0.0, box["y"] - margin)))

    def active_page_changed(self, pno: int) -> None:
        """Called by the scroll area when the visible page changes."""
        if pno != self.pno:
            self.pno = max(0, min(pno, max(0, self._page_count - 1)))
            self._annots = []
            self._sel_rects = []
            self._sel_annot = None
            self._hover_info = None
            self._hover_pno = None
            self.refresh_annots()
            try:
                self.page_pixmap(self.pno)
            except Exception:
                pass
            self.update()
        self.pageActivated.emit(self.pno)

    def sync_active_from_viewport(self) -> int:
        """Pick the page in the middle of the viewport after a scroll."""
        sa = self._scroll_area()
        if sa is None or not self._layout:
            return self.pno
        cy = sa.verticalScrollBar().value() + sa.viewport().height() / 2
        pno = self.page_at(QPointF(0.0, cy))
        if pno != self.pno:
            self.active_page_changed(pno)
        return pno

    def scroll_to_pdf_rect(self, pno: int, rect, bias: float = 0.35) -> None:
        """Scroll so that *rect* on *pno* sits comfortably in the viewport."""
        sa = self._scroll_area()
        if sa is None or not self._layout:
            return
        rr = self._pdf_to_widget_rect(rect, pno)
        bar = sa.verticalScrollBar()
        target = rr.center().y() - sa.viewport().height() * bias
        bar.setValue(int(max(0.0, target)))

    def set_tool(self, name: str):
        self.cancel_inline()
        self.tool = name
        self._drag_start = self._drag_cur = None
        self._ink = []
        self._hover_info = None
        self.setCursor(QCursor(TOOL_CURSORS.get(name, Qt.CrossCursor)))
        self.update()

    def set_style(self, color=None, width=None, fontsize=None, font=None):
        if color is not None:
            self.tool_color = color
        if width is not None:
            self.tool_width = width
        if fontsize is not None:
            self.tool_fontsize = fontsize
        if font is not None:
            self.tool_font = font

    # ------------------------------------------------------------ annotations
    def set_read_mode(self, on: bool):
        self.read_mode = on
        self._sel_annot = None
        self._hover_info = None
        if on:
            self.set_tool("hand")
        self.update()

    def refresh_annots(self):
        if self.doc is None or self.read_mode:
            self._annots = []
            return
        try:
            self._annots = self.doc.annotations(self.pno)
        except Exception:
            self._annots = []
        if self._sel_annot is not None:
            match = [a for a in self._annots if a["xref"] == self._sel_annot["xref"]]
            self._sel_annot = match[0] if match else None
            if self._sel_annot is None:
                self.annotSelected.emit(None)
        self.update()

    def selected_annot(self):
        return self._sel_annot

    def select_annot(self, xref: int | None):
        self._sel_annot = next((a for a in self._annots if a["xref"] == xref), None)
        self.annotSelected.emit(self._sel_annot)
        self.update()

    def _annot_at(self, pt, text_first: bool = False):
        markup = {"highlight", "underline", "strikeout", "squiggly"}
        for a in reversed(self._annots):
            r = a["rect"]
            if not (r[0] - 3 <= pt[0] <= r[2] + 3 and r[1] - 3 <= pt[1] <= r[3] + 3):
                continue
            if text_first and a["kind"] in markup:
                # text markup sits under real text: a plain drag selects text.
                # Ctrl+click (or right-click) selects the markup itself.
                continue
            return a
        return None

    def _handle_at(self, pt):
        """Return the resize handle (nw..w) under a PDF-space point."""
        a = self._sel_annot
        if not a:
            return None
        r = a["rect"]
        tol = 7.0 / max(self.zoom, 0.1)
        xs = {"l": r[0], "c": (r[0] + r[2]) / 2, "r": r[2]}
        ys = {"t": r[1], "m": (r[1] + r[3]) / 2, "b": r[3]}
        for name, (hx, hy) in {
            "nw": (xs["l"], ys["t"]), "n": (xs["c"], ys["t"]),
            "ne": (xs["r"], ys["t"]), "e": (xs["r"], ys["m"]),
            "se": (xs["r"], ys["b"]), "s": (xs["c"], ys["b"]),
            "sw": (xs["l"], ys["b"]), "w": (xs["l"], ys["m"]),
        }.items():
            if abs(pt[0] - hx) <= tol and abs(pt[1] - hy) <= tol:
                return name
        return None

    def _cursor_for_handle(self, h):
        return {
            "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
            "ne": Qt.SizeFDiagCursor, "sw": Qt.SizeFDiagCursor,
            "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
            "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
        }.get(h, Qt.SizeAllCursor)

    def _resize_rect(self, orig, handle, dx, dy):
        x0, y0, x1, y1 = orig
        if "w" in handle:
            x0 += dx
        if "e" in handle:
            x1 += dx
        if "n" in handle:
            y0 += dy
        if "s" in handle:
            y1 += dy
        if x1 - x0 < 6:
            if "w" in handle:
                x0 = x1 - 6
            else:
                x1 = x0 + 6
        if y1 - y0 < 6:
            if "n" in handle:
                y0 = y1 - 6
            else:
                y1 = y0 + 6
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


    def _page_size(self):
        if self.doc is None:
            return 612.0, 792.0
        return self.doc.page_size(self.pno)

    def _update_size(self):
        if self.doc is None:
            self._layout = []
            self._page_w, self._page_h = 612.0, 792.0
            self.setFixedSize(QSize(1, 1))
            return
        self._page_count = self.doc.page_count
        self.pno = max(0, min(self.pno, max(0, self._page_count - 1)))
        sizes = []
        for i in range(self._page_count):
            try:
                sizes.append(self.doc.page_size(i))
            except Exception:
                sizes.append((612.0, 792.0))
        if not sizes:
            self._layout = []
            self.setFixedSize(QSize(1, 1))
            return
        scaled = [(max(1, int(w * self.zoom + 0.5)),
                   max(1, int(h * self.zoom + 0.5))) for w, h in sizes]
        layout = []
        if self.layout_mode == "single":
            w, h = scaled[self.pno]
            total_w = w
            total_h = float(h)
            layout.append({"pno": self.pno, "x": 0.0, "y": 0.0,
                           "w": float(w), "h": float(h)})
        elif self.layout_mode == "two_page":
            rows = []
            for i in range(0, len(scaled), 2):
                pair = [(i, scaled[i][0], scaled[i][1])]
                if i + 1 < len(scaled):
                    pair.append((i + 1, scaled[i + 1][0], scaled[i + 1][1]))
                row_w = sum(p[1] for p in pair) + (self._gap if len(pair) > 1 else 0)
                row_h = max(p[2] for p in pair)
                rows.append((pair, row_w, row_h))
            total_w = max(r[1] for r in rows)
            y = 0.0
            for pair, row_w, row_h in rows:
                x = (total_w - row_w) / 2.0
                for pno, w, h in pair:
                    layout.append({"pno": pno, "x": x, "y": y + (row_h - h) / 2.0,
                                   "w": float(w), "h": float(h)})
                    x += w + self._gap
                y += row_h + self._gap
            total_h = y - self._gap
        else:
            total_w = max(w for w, _h in scaled)
            y = 0.0
            for i, (w, h) in enumerate(scaled):
                layout.append({"pno": i, "x": (total_w - w) / 2.0,
                               "y": y, "w": float(w), "h": float(h)})
                y += h + self._gap
            total_h = y - self._gap
        self._layout = layout
        self._page_w, self._page_h = sizes[self.pno]
        self.setFixedSize(QSize(max(1, total_w + 2), max(1, int(total_h) + 2)))

    def set_zoom(self, z: float):
        z = max(0.05, min(8.0, z))
        if abs(z - self.zoom) < 1e-4:
            return
        self.cancel_inline()
        self.zoom = z
        self._cache.clear()          # images at the old zoom can never be reused
        self._render_queue = []
        self._failed = set()
        self._update_size()
        self.refresh()

    # -------------------------------------------------------------- painting
    def _render_key(self, pno: int):
        dpr = max(1.0, self.devicePixelRatioF())
        return (int(pno), round(self.zoom, 3), round(dpr, 2))

    def _trim_cache(self, limit=24):
        while len(self._cache) > limit:
            self._cache.pop(next(iter(self._cache)))

    def page_pixmap(self, pno: int | None = None):
        """Return QImage for *pno* (default: active page) at current zoom."""
        pno = self.pno if pno is None else int(pno)
        if self.doc is None:
            return None
        key = self._render_key(pno)
        img = self._cache.get(key)
        if img is not None:
            return img
        try:
            pix = self.doc.render(pno, self.zoom, key[2])
        except Exception:
            return None
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        img = self._apply_color_mode(img)
        self._trim_cache()
        self._cache[key] = img
        return img

    def _page_image(self, pno: int):
        """Non-blocking cache lookup used while painting."""
        img = self._cache.get(self._render_key(pno))
        if img is None:
            key = self._render_key(pno)
            if key not in self._render_queue and key not in self._failed:
                self._render_queue.append(key)
            self._schedule_render()
        return img

    def _schedule_render(self):
        if self._render_queue and not self._render_timer.isActive():
            self._render_timer.start()

    def _render_next(self):
        if self.doc is None or not self._render_queue:
            return
        key = self._render_queue.pop(0)
        pno, z, dpr = key
        if key in self._cache:
            self._schedule_render()
            return
        try:
            pix = self.doc.render(pno, z, dpr)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGB888).copy()
            img = self._apply_color_mode(img)
        except Exception:
            img = None
        if img is None:
            self._failed.add(key)
        else:
            self._trim_cache()
            self._cache[key] = img
        self.update()
        self._schedule_render()

    def paintEvent(self, ev):
        p = QPainter(self)
        light = self._theme_name == "light"
        p.fillRect(self.rect(), QColor("#dde1e7" if light else "#131417"))
        if not self._layout:
            p.end()
            return
        clip = ev.rect()
        base_font = p.font()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for box in self._layout:
            top = box["y"]
            bottom = top + box["h"]
            if bottom < clip.top() - 1 or top > clip.bottom() + 1:
                continue
            img = self._page_image(box["pno"])
            target = QRectF(box["x"] + 0.5, top + 0.5, box["w"], box["h"])
            if img is not None:
                p.drawImage(target, img)
            else:
                p.fillRect(target, QColor("#ffffff" if light else "#1b1d21"))
            p.setPen(QPen(QColor("#c4cad4" if light else "#2f333a"), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(target)
            if not self.read_mode:
                f = QFont(base_font)
                f.setPointSizeF(max(7.0, base_font.pointSizeF() * 0.85))
                p.setFont(f)
                p.setPen(QColor("#6b7078"))
                p.drawText(QRectF(box["x"], bottom + 1, box["w"], 15),
                           Qt.AlignRight | Qt.AlignTop, str(box["pno"] + 1))
                p.setFont(base_font)

        # search highlights (may live on any page of the strip)
        for i, (pno, r) in enumerate(self._search_hits):
            rr = self._pdf_to_widget_rect(r, pno)
            if not rr.intersects(QRectF(self.rect())):
                continue
            col = QColor(255, 176, 32, 110) if i == self._search_cur else QColor(255, 225, 60, 80)
            p.fillRect(rr, col)
            p.setPen(QPen(QColor(255, 160, 20, 220) if i == self._search_cur else QColor(200, 170, 20, 120), 1.4))
            p.drawRect(rr)

        # text selection
        if self._sel_rects:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(80, 150, 255, 90))
            for r in self._sel_rects:
                p.drawRect(self._pdf_to_widget_rect(r))

        # form field hints
        if self.tool == "form":
            for r in self._widget_rects:
                rr = self._pdf_to_widget_rect(r)
                p.setBrush(QColor(229, 72, 77, 30))
                p.setPen(QPen(QColor(229, 72, 77, 200), 1, Qt.DashLine))
                p.drawRect(rr)

        # ink preview
        if self._ink:
            p.setPen(QPen(QColor.fromRgbF(*self.tool_color), max(1.0, self.tool_width * self.zoom),
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            for stroke in self._ink:
                path = QPainterPath()
                pts = [self._pdf_to_widget(pt) for pt in stroke]
                if not pts:
                    continue
                path.moveTo(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                p.drawPath(path)

        # drag band
        if self._drag_start and self._drag_cur:
            r = self._band_rect()
            if self.tool in ("rect", "ellipse", "redact"):
                p.setPen(QPen(QColor.fromRgbF(*self.tool_color), 1.4, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                if self.tool == "ellipse":
                    p.drawEllipse(r)
                else:
                    p.drawRect(r)
            elif self.tool in ("line", "arrow"):
                p.setPen(QPen(QColor.fromRgbF(*self.tool_color),
                              max(1.0, self.tool_width * self.zoom),
                              Qt.SolidLine, Qt.RoundCap))
                a = self._drag_start
                b = self._drag_cur
                p.drawLine(a, b)
                if self.tool == "arrow":
                    p.setBrush(QColor.fromRgbF(*self.tool_color))
                    p.drawEllipse(b, 3.5, 3.5)
            else:
                p.setPen(QPen(QColor(229, 72, 77), 1.2, Qt.DashLine))
                p.setBrush(QColor(229, 72, 77, 28))
                p.drawRect(r)

        # hover outline while the text tool is active (hidden during live edit)
        if self.tool == "edit_text" and self._hover_info is not None and self._editor is None:
            hr = self._pdf_to_widget_rect(self._hover_info["rect"], self._hover_pno)
            p.setPen(QPen(QColor(76, 141, 255, 210), 1.3, Qt.DashLine))
            p.setBrush(QColor(76, 141, 255, 22))
            p.drawRect(hr.adjusted(-1, -1, 1, 1))

        # selected annotation + resize handles
        if self._sel_annot is not None and not self.read_mode:
            rr = self._pdf_to_widget_rect(self._sel_annot["rect"])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(76, 141, 255), 1.4, Qt.DashLine))
            p.drawRect(rr)
            p.setPen(QPen(QColor("#ffffff"), 1.0))
            p.setBrush(QColor(76, 141, 255))
            hs = 4.0
            for hx, hy in ((rr.left(), rr.top()), (rr.center().x(), rr.top()),
                           (rr.right(), rr.top()), (rr.right(), rr.center().y()),
                           (rr.right(), rr.bottom()), (rr.center().x(), rr.bottom()),
                           (rr.left(), rr.bottom()), (rr.left(), rr.center().y())):
                p.drawRect(QRectF(hx - hs, hy - hs, hs * 2, hs * 2))
        p.end()

    def _pdf_to_widget(self, pt, pno: int | None = None) -> QPointF:
        box = self._page_box(self.pno if pno is None else pno)
        return QPointF(box["x"] + pt[0] * self.zoom,
                       box["y"] + pt[1] * self.zoom)

    def _pdf_to_widget_rect(self, r, pno: int | None = None) -> QRectF:
        box = self._page_box(self.pno if pno is None else pno)
        x0, y0, x1, y1 = (r[0], r[1], r[2], r[3]) if not isinstance(r, QRectF) else (r.x(), r.y(), r.right(), r.bottom())
        return QRectF(box["x"] + x0 * self.zoom, box["y"] + y0 * self.zoom,
                      (x1 - x0) * self.zoom, (y1 - y0) * self.zoom)

    def _widget_to_pdf(self, pt: QPointF, pno: int | None = None):
        box = self._page_box(self.pno if pno is None else pno)
        return ((pt.x() - box["x"]) / self.zoom,
                (pt.y() - box["y"]) / self.zoom)

    def _band_rect(self):
        a = self._drag_start
        b = self._drag_cur
        return QRectF(min(a.x(), b.x()), min(a.y(), b.y()),
                      abs(b.x() - a.x()), abs(b.y() - a.y()))

    def _band_pdf(self):
        r = self._band_rect()
        x0, y0 = self._widget_to_pdf(r.topLeft())
        x1, y1 = self._widget_to_pdf(r.bottomRight())
        return (x0, y0, x1, y1)

    # ------------------------------------------------------------ inline edit
    def inline_active(self) -> bool:
        return self._editor is not None

    def open_inline_editor(self, info, click_point=None):
        if self.doc is None:
            return
        self.cancel_inline()
        info = dict(info)
        info["font_buffer"] = self.doc.embedded_font(self.pno, info.get("font_name"))
        box = self._page_box(self.pno)
        ed = InlineTextEditor(self, info, self.zoom, click_point,
                              offset=(box["x"], box["y"]))
        ed.committed.connect(lambda text, i=info, e=ed: self._inline_done(i, text, e.extract_rich_runs()))
        ed.cancelled.connect(self._inline_abort)
        self._editor = ed
        ed.show()
        ed.raise_()
        ed.setFocus()
        self.status.emit("Ketik untuk mengubah teks · Ctrl+B Tebal · Ctrl+I Miring · Enter simpan · Shift+Enter baris baru · Esc batal")

    def _inline_done(self, info, text, rich_runs=None):
        self._editor = None
        self.inlineCommit.emit({"info": info, "text": text, "rich_runs": rich_runs})

    def _inline_abort(self):
        self._editor = None
        self.inlineCancel.emit()

    def commit_inline(self):
        if self._editor is not None:
            self._editor.commit_now()

    def cancel_inline(self):
        if self._editor is not None:
            self._editor.cancel_now()

    def _needs_ocr_here(self):
        """Offer OCR when the user clicks a page that is only a scan."""
        try:
            scanned = self.doc.needs_ocr(self.pno)
        except Exception:
            scanned = False
        if scanned:
            self.scanNeedsOcr.emit(self.pno)
        return scanned

    def edit_text_at(self, point):
        """Open the in-place editor for the paragraph under *point*."""
        if self.doc is None:
            return
        try:
            info = self.doc.text_at(self.pno, point)
        except Exception:
            info = None
        if not info:
            if self._needs_ocr_here():
                return
            self.status.emit("Nggak ada teks di titik itu. Klik tepat di atas teks.")
            return
        self._sel_rects = []
        self.open_inline_editor(info, point)

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        pos = ev.position()
        # Editing is per page: the page under the pointer becomes the active
        # page before any tool gesture is interpreted.
        if self._editor is not None:
            self.commit_inline()
        pno = self.page_at(pos)
        if pno != self.pno:
            self.activate_page(pno)
        if ev.button() == Qt.RightButton:
            self._context_menu(ev.position())
            return
        self._press_pos = pos
        if self.tool == "hand" or (ev.modifiers() & Qt.ControlModifier and self.tool == "select"):
            self._panning = True
            self._pan_last = pos
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self.tool == "select" and not self.read_mode:
            pt = self._widget_to_pdf(pos)
            handle = self._handle_at(pt)
            if handle:
                self._annot_drag = {"mode": "resize", "handle": handle,
                                    "orig": tuple(self._sel_annot["rect"]),
                                    "start": pt}
                return
            annot = self._annot_at(pt, text_first=not (ev.modifiers() & Qt.ControlModifier))
            if annot is not None:
                self.select_annot(annot["xref"])
                self._annot_drag = {"mode": "move", "handle": None,
                                    "orig": tuple(annot["rect"]), "start": pt}
                self.setCursor(Qt.SizeAllCursor)
                return
            if self._sel_annot is not None:
                self.select_annot(None)
        if self.tool == "note":
            self.action.emit("note", {"rect": (*self._widget_to_pdf(pos),) * 2})
            return
        if self.tool == "form":
            pt = self._widget_to_pdf(pos)
            for r in self._widget_rects:
                if r[0] <= pt[0] <= r[2] and r[1] <= pt[1] <= r[3]:
                    self.action.emit("form_fill", {"point": pt, "rect": tuple(r)})
                    return
            self.action.emit("form_click", {"point": pt})
            return
        if self.tool == "ink":
            self._ink = [[self._widget_to_pdf(pos)]]
            return
        self._drag_start = pos
        self._drag_cur = pos
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._panning and self._pan_last is not None:
            delta = pos - self._pan_last
            self._pan_last = pos
            sa = self._scroll_area()
            if sa is not None:
                h = sa.horizontalScrollBar()
                v = sa.verticalScrollBar()
                h.setValue(h.value() - int(delta.x()))
                v.setValue(v.value() - int(delta.y()))
            return
        if self._annot_drag is not None:
            pt = self._widget_to_pdf(pos)
            dx = pt[0] - self._annot_drag["start"][0]
            dy = pt[1] - self._annot_drag["start"][1]
            orig = self._annot_drag["orig"]
            if self._annot_drag["mode"] == "move":
                new = (orig[0] + dx, orig[1] + dy, orig[2] + dx, orig[3] + dy)
            else:
                new = self._resize_rect(orig, self._annot_drag["handle"], dx, dy)
            if self._sel_annot is not None:
                self._sel_annot["rect"] = new
                self._annot_drag["new"] = new
                self.update()
            return
        if self.tool == "select" or self.read_mode:
            hpno = self.page_at(pos)
            hpt = self._widget_to_pdf(pos, hpno)
            link = self._link_at(hpt, hpno)
            if link != self._hover_link:
                self._hover_link = link
                if link:
                    tip = (f"Buka tautan: {link['uri']}" if link.get("uri")
                           else f"Ke halaman {int(link['page']) + 1}")
                    self.setToolTip(tip)
                else:
                    self.setToolTip("")
            if self.read_mode:
                self.setCursor(QCursor(Qt.PointingHandCursor if link else Qt.ArrowCursor))
            else:
                pt = self._widget_to_pdf(pos)
                if link is not None:
                    self.setCursor(QCursor(Qt.PointingHandCursor))
                elif hpno != self.pno:
                    self.setCursor(QCursor(Qt.ArrowCursor))
                elif self._handle_at(pt):
                    self.setCursor(QCursor(self._cursor_for_handle(self._handle_at(pt))))
                elif self._annot_at(pt, text_first=not (ev.modifiers() & Qt.ControlModifier)) is not None:
                    self.setCursor(QCursor(Qt.SizeAllCursor))
                else:
                    self.setCursor(QCursor(Qt.IBeamCursor))
        if self.tool == "edit_text":
            hpno = self.page_at(pos)
            hpt = self._widget_to_pdf(pos, hpno)
            info = None
            try:
                info = self.doc.text_at(hpno, hpt) if self.doc else None
            except Exception:
                info = None
            if (info and info.get("rect")) != (self._hover_info and self._hover_info.get("rect")):
                self._hover_info = info
                self._hover_pno = hpno if info else None
                self.update()
            self.setCursor(QCursor(Qt.PointingHandCursor if info else Qt.IBeamCursor))
        if self.tool == "ink" and self._ink:
            self._ink[-1].append(self._widget_to_pdf(pos))
            self.update()
            return
        if self._drag_start is not None:
            self._drag_cur = pos
            self.update()

    def mouseReleaseEvent(self, ev):
        if self._panning:
            self._panning = False
            self._pan_last = None
            self.setCursor(Qt.OpenHandCursor if self.tool == "hand" else Qt.IBeamCursor)
            return
        if self._annot_drag is not None:
            drag = self._annot_drag
            self._annot_drag = None
            self.setCursor(QCursor(Qt.IBeamCursor))
            xref = self._sel_annot["xref"] if self._sel_annot else None
            new = drag.get("new")
            if xref is not None and new is not None:
                orig = drag["orig"]
                if max(abs(a - b) for a, b in zip(new, orig)) > 0.4:
                    label = ("Geser anotasi" if drag["mode"] == "move"
                             else "Ubah ukuran anotasi")
                    self.annotChanged.emit({"xref": xref, "rect": new,
                                            "label": label})
            self.update()
            return
        if self.tool == "ink":
            strokes = [s for s in self._ink if len(s) > 1]
            self._ink = []
            if strokes:
                self.action.emit("ink", {"strokes": strokes})
            self.update()
            return
        if self._drag_start is None:
            return
        rect = self._band_pdf()
        self._drag_start, self._drag_cur = None, None
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        if self.tool == "edit_text":
            press = self._press_pos
            self._press_pos = None
            info = None
            if press is not None:
                try:
                    info = self.doc.text_at(self.pno, self._widget_to_pdf(press))
                except Exception:
                    info = None
            if info is None:
                # A press that Qt turned into a double click may leave a stale
                # press position; fall back to where the pointer was released.
                try:
                    info = self.doc.text_at(self.pno, self._widget_to_pdf(ev.position()))
                except Exception:
                    info = None
                press = ev.position()
            small = w * self.zoom < 6 and h * self.zoom < 6
            same_para = False
            if info and press is not None and not small:
                ex, ey = rect[2], rect[3]
                x0, y0, x1, y1 = info["rect"]
                same_para = (x0 - 2 <= ex <= x1 + 2
                             and y0 - info.get("size", 10) <= ey <= y1 + 2)
            if info and (small or same_para):
                self._sel_rects = []
                self.update()
                self.open_inline_editor(info, self._widget_to_pdf(press))
                return
            if small:
                self.update()
                if self._needs_ocr_here():
                    return
                self.status.emit("Nggak ada teks di titik itu. Klik tepat di atas teks.")
                return
            self.action.emit("gesture", {"tool": self.tool, "rect": rect})
        elif self.tool == "select" or self.read_mode:
            is_click = w * self.zoom < 4 and h * self.zoom < 4
            if is_click:
                pt = self._widget_to_pdf(ev.position())
                link = self._link_at(pt, self.pno)
                if link is not None:
                    self.linkClicked.emit(link)
                    self.update()
                    return
            if self.tool == "select" and not self.read_mode:
                self._select_text(rect, click=is_click)
        elif w * self.zoom < 3 and h * self.zoom < 3 and self.tool not in ("text", "note", "signature", "cert", "stamp", "callout"):
            self.status.emit("Tarik kotak di area yang diinginkan.")
        else:
            payload = {"tool": self.tool, "rect": rect}
            if self.tool in ("line", "arrow"):
                payload["p1"] = self._widget_to_pdf(self._press_pos)
                payload["p2"] = self._widget_to_pdf(ev.position())
            self.action.emit("gesture", payload)
        self.update()

    def mouseDoubleClickEvent(self, ev):
        pos = ev.position()
        pno = self.page_at(pos)
        if pno != self.pno:
            self.activate_page(pno)
        if self.tool == "edit_text":
            try:
                info = self.doc.text_at(self.pno, self._widget_to_pdf(pos))
            except Exception:
                info = None
            if info:
                self._drag_start = self._drag_cur = None
                self.open_inline_editor(info, pos)
                return
            if self._needs_ocr_here():
                return
        if self.tool == "select":
            pt = self._widget_to_pdf(pos)
            # A double click on an annotation must keep it selected instead of
            # selecting the text that happens to sit underneath it.
            annot = self._annot_at(pt, text_first=False)
            if annot is not None:
                self.select_annot(annot["xref"])
                self.update()
                return
            w, h = self._page_w, self._page_h
            step = 20 / max(self.zoom, 0.2)
            self._select_text((0, pt[1] - step, w, pt[1] + step))
            self.update()

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier:
            self.zoomRequested.emit(1.15 if ev.angleDelta().y() > 0 else 1 / 1.15)
            ev.accept()
            return
        sa = self._scroll_area()
        if sa is None:
            ev.ignore()
            return
        pixel = ev.pixelDelta()
        angle = ev.angleDelta()
        if not pixel.isNull():
            dx, dy = pixel.x(), pixel.y()
        else:
            dx, dy = int(angle.x() / 120 * 60), int(angle.y() / 120 * 60)
        if dx == 0 and dy == 0:
            ev.ignore()
            return
        hbar = sa.horizontalScrollBar()
        vbar = sa.verticalScrollBar()
        if ev.modifiers() & Qt.ShiftModifier and dx == 0:
            dx, dy = dy, 0
        hbar.setValue(hbar.value() - dx)
        vbar.setValue(vbar.value() - dy)
        ev.accept()

    def keyPressEvent(self, ev: QKeyEvent):
        if ev.key() == Qt.Key_Escape:
            self._drag_start = self._drag_cur = None
            self._ink = []
            if self._sel_annot is not None:
                self.select_annot(None)
            self.update()
        elif ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._sel_annot is not None:
            self.annotDeleted.emit({"xref": self._sel_annot["xref"]})
        else:
            super().keyPressEvent(ev)

    # ---------------------------------------------------------- annot context
    def _context_menu(self, pos):
        if self.doc is None or self.read_mode:
            return
        pt = self._widget_to_pdf(pos)
        annot = self._annot_at(pt)
        menu = QMenu(self)
        if annot is not None:
            self.select_annot(annot["xref"])
            act_del = menu.addAction("Hapus anotasi")
            act_props = menu.addAction("Properti anotasi…")
            act_copy = None
            if annot.get("content"):
                act_copy = menu.addAction("Salin isi anotasi")
            menu.addSeparator()
        else:
            act_del = act_props = act_copy = None
        act_clear = menu.addAction("Hapus semua anotasi di halaman")
        chosen = menu.exec(self.mapToGlobal(pos.toPoint()))
        if chosen is None:
            return
        if chosen is act_del and annot is not None:
            self.annotDeleted.emit({"xref": annot["xref"]})
        elif chosen is act_props and annot is not None:
            self.annotProps.emit(annot)
        elif act_copy is not None and chosen is act_copy:
            QApplication.clipboard().setText(annot.get("content") or "")
            self.status.emit("Isi anotasi disalin.")
        elif chosen is act_clear:
            self.action.emit("clear_annots", {})

    def _scroll_area(self):
        w = self.parentWidget()
        while w is not None:
            if w.__class__.__name__ == "QScrollArea":
                return w
            w = w.parentWidget()
        return None

    # -------------------------------------------------------------- selection
    def _select_text(self, rect, click=False):
        self._sel_rects = []
        if self.doc is None:
            return
        if click:
            x, y = rect[0], rect[1]
            rect = (x - 3, y - 3, x + 3, y + 3)
        try:
            words = self.doc.words(self.pno, clip=rect)
        except Exception:
            words = []
        if not words:
            self.selectionChanged.emit("")
            self.status.emit("Tidak ada teks di area itu.")
            self.update()
            return
        rects = [(w[0], w[1], w[2], w[3]) for w in words]
        if click:
            x0, y0 = rect[0], rect[1]
            best = min(rects, key=lambda r: (r[1] - y0) ** 2 + (r[0] - x0) ** 2)
            rects = [best]
        self._sel_rects = rects
        self._emit_selection()

    def _emit_selection(self):
        if self.doc is None or not self._sel_rects:
            self.selectionChanged.emit("")
            return
        words = self.doc.words(self.pno)
        chosen = []
        for r in self._sel_rects:
            for w in words:
                if abs(w[0] - r[0]) < 0.6 and abs(w[1] - r[1]) < 0.6:
                    chosen.append(w)
                    break
        chosen.sort(key=lambda w: (round(w[1], 1), w[0]))
        lines, cur, last_y = [], [], None
        for w in chosen:
            if last_y is not None and abs(w[1] - last_y) > 3:
                lines.append(" ".join(cur))
                cur = []
            cur.append(w[4])
            last_y = w[1]
        if cur:
            lines.append(" ".join(cur))
        text = "\n".join(lines)
        self._sel_text = text
        self.selectionChanged.emit(text)
        self.update()

    def selection_text(self) -> str:
        return self._sel_text

    def selection_bbox(self):
        """PDF-space bounding box of the current text/annotation selection."""
        rects = [tuple(r) for r in self._sel_rects]
        if self._sel_annot is not None:
            rects.append(tuple(self._sel_annot["rect"]))
        if not rects:
            return None
        return (min(r[0] for r in rects), min(r[1] for r in rects),
                max(r[2] for r in rects), max(r[3] for r in rects))

    def viewport_center_ratio(self):
        try:
            sa = self._scroll_area()
            if sa is None or self.width() < 2 or self.height() < 2:
                return None
            h = sa.horizontalScrollBar()
            v = sa.verticalScrollBar()
            vw = sa.viewport().width()
            vh = sa.viewport().height()
            cx = (h.value() + vw / 2) / self.width()
            cy = (v.value() + vh / 2) / self.height()
            return (max(0.0, min(1.0, cx)), max(0.0, min(1.0, cy)))
        except Exception:
            return None

    def restore_center(self, ratio):
        if not ratio:
            return
        try:
            sa = self._scroll_area()
            if sa is None:
                return
            vw = sa.viewport().width()
            vh = sa.viewport().height()
            sa.horizontalScrollBar().setValue(int(ratio[0] * self.width() - vw / 2))
            sa.verticalScrollBar().setValue(int(ratio[1] * self.height() - vh / 2))
        except Exception:
            pass

    def select_all(self):
        if self.doc is None:
            return
        words = self.doc.words(self.pno)
        self._sel_rects = [(w[0], w[1], w[2], w[3]) for w in words]
        self._emit_selection()

    def clear_selection(self):
        self._sel_rects = []
        self._sel_text = ""
        self.update()

    # ------------------------------------------------------------------ search
    def set_search_hits(self, hits, current=-1):
        """hits: ``[(pno, (x0, y0, x1, y1)), ...]`` for the whole document.

        A bare rect is accepted too and is attached to the active page, which
        keeps older callers working.
        """
        out = []
        for item in hits or []:
            if (isinstance(item, (tuple, list)) and len(item) == 2
                    and isinstance(item[0], int)):
                pno, r = item
            else:
                pno, r = self.pno, item
            out.append((int(pno), QRectF(float(r[0]), float(r[1]),
                                         float(r[2]) - float(r[0]),
                                         float(r[3]) - float(r[1]))))
        self._search_hits = out
        self._search_cur = current
        self.update()

    def set_widget_rects(self, rects):
        self._widget_rects = [tuple(r) for r in rects]
        self.update()

    def invalidate(self):
        self._cache.clear()
        self._links_cache.clear()
        self._hover_link = None
        self._render_queue = []
        self._failed = set()
        self.refresh()

    def refresh(self):
        if self.doc is None:
            self.setFixedSize(QSize(1, 1))
            self.update()
            return
        self._update_size()
        self.refresh_annots()
        # Keep the page being worked on instantly visible; neighbours are
        # filled in one-per-tick by the deferred renderer.
        try:
            self.page_pixmap(self.pno)
        except Exception:
            pass
        self.update()
