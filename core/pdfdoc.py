"""Core PDF document engine for PDF Studio (PyMuPDF wrapper)."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import datetime

from core import ocr as _winocr

try:
    import pymupdf as fitz
except ImportError:  # older wheels
    import fitz

_FONT_CODES = {
    "Helvetica": {False: {False: "helv", True: "heit"}, True: {False: "hebo", True: "hebi"}},
    "Times": {False: {False: "tiro", True: "tiit"}, True: {False: "tibo", True: "tibi"}},
    "Courier": {False: {False: "cour", True: "coit"}, True: {False: "cobo", True: "cobi"}},
}


def font_code(font: str, bold: bool = False, italic: bool = False) -> str:
    return _FONT_CODES.get(font, _FONT_CODES["Helvetica"])[bool(bold)][bool(italic)]


_SYS_TTF_FILES = {
    "Helvetica": {
        False: {False: "arial.ttf", True: "ariali.ttf"},
        True: {False: "arialbd.ttf", True: "arialbi.ttf"},
    },
    "Times": {
        False: {False: "times.ttf", True: "timesi.ttf"},
        True: {False: "timesbd.ttf", True: "timesbi.ttf"},
    },
    "Courier": {
        False: {False: "cour.ttf", True: "couri.ttf"},
        True: {False: "courbd.ttf", True: "courbi.ttf"},
    },
}


def _system_ttf_path(font: str, bold: bool = False, italic: bool = False) -> str | None:
    if os.name != "nt":
        return None
    fdir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    fname = _SYS_TTF_FILES.get(font, _SYS_TTF_FILES["Helvetica"])[bool(bold)][bool(italic)]
    cand = os.path.join(fdir, fname)
    if os.path.isfile(cand):
        return cand
    fallback = os.path.join(fdir, "segoeui.ttf")
    return fallback if os.path.isfile(fallback) else None

ANNOT_STYLES = ["highlight", "underline", "strikeout", "squiggly"]

_TERMINAL_CHARS = (".", "!", "?", ":", ";", "\u3002", "\uff01", "\uff1f")


def _rect(x0, y0, x1, y1):
    return fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def span_color(span) -> tuple[float, float, float]:
    """RGB floats (0..1) from a PyMuPDF text span."""
    c = span.get("color", 0)
    if isinstance(c, (tuple, list)):
        return tuple(float(v) for v in c[:3])
    return (((c >> 16) & 255) / 255.0,
            ((c >> 8) & 255) / 255.0,
            (c & 255) / 255.0)


def font_family(font_name: str) -> str:
    """Map a PDF font name onto one of the three built-in fallback families."""
    base = (font_name or "").split("+")[-1].lower()
    if any(k in base for k in ("courier", "mono", "consol", "code", "fixed")):
        return "Courier"
    if "sans" not in base and any(k in base for k in
                                  ("times", "georgia", "garamond", "serif",
                                   "cambria", "book", "roman")):
        return "Times"
    return "Helvetica"


def display_font_name(font_name: str) -> str:
    """Strip the subset prefix and style suffix, e.g. AAAAAA+DMSans-Bold -> DMSans."""
    base = (font_name or "").split("+")[-1]
    base = base.split(",")[0]
    for suffix in ("-BoldItalic", "-BoldOblique", "-Bold", "-Italic", "-Oblique",
                   "-Regular", "-Medium", "-Light", "-Semibold", "-SemiBold",
                   "-Black", "-Thin", "-ExtraBold", "-Condensed",
                   "BoldItalic", "Bold", "Italic", "Regular", "Medium", "Light",
                   "Semibold", "SemiBold", "Black", "Thin", "ExtraBold"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base or "Helvetica"


def _span_bold(span) -> bool:
    return "bold" in (span.get("font") or "").lower() or bool(span.get("flags", 0) & 16)


def _span_italic(span) -> bool:
    return ("italic" in (span.get("font") or "").lower()
            or "oblique" in (span.get("font") or "").lower()
            or bool(span.get("flags", 0) & 2))


_LIST_PREFIX_RE = re.compile(
    r"^(?:[\u2022\u25cf\u25cb\u25aa\u25a0\u2013\u2014\-*]\s+"
    r"|(?:[0-9]{1,3}(?:\.[0-9]{1,3})*[.)]|[a-zA-Z][.)]|\([0-9a-zA-Z]{1,3}\))\s+"
    r"|BAB\s+[IVX0-9]+)",
    re.IGNORECASE,
)


def _line_meta(line: dict) -> dict | None:
    spans = [s for s in line.get("spans", []) if s.get("text")]
    text = "".join(s["text"] for s in spans)
    if not text.strip():
        return None
    r = fitz.Rect(line["bbox"])
    first = spans[0]
    origin_y = float(first["origin"][1]) if first.get("origin") else float(r.y1)
    return {
        "rect": (float(r.x0), float(r.y0), float(r.x1), float(r.y1)),
        "spans": spans,
        "text": text,
        "size": float(first.get("size") or 10.0),
        "bold": _span_bold(first),
        "origin_y": origin_y,
    }


def _should_merge_lines(group: list[dict], cur: dict) -> bool:
    prev = group[-1]
    prev_text = prev["text"].rstrip()
    cur_text = cur["text"].lstrip()
    if not cur_text or _LIST_PREFIX_RE.match(cur_text):
        return False
    sz = prev["size"]
    if abs(cur["size"] - sz) > 0.7 or cur["bold"] != prev["bold"]:
        return False

    dy = cur["origin_y"] - prev["origin_y"]
    if dy <= 0.5:
        return False
    if len(group) >= 2:
        gaps = [b["origin_y"] - a["origin_y"] for a, b in zip(group, group[1:]) if b["origin_y"] - a["origin_y"] > 0.5]
        est_gap = sorted(gaps)[len(gaps) // 2] if gaps else sz * 1.35
        if dy > max(est_gap * 1.28, sz * 1.6):
            return False
    else:
        if dy > sz * 2.15:
            return False

    px0, _py0, px1, _py1 = prev["rect"]
    cx0, _cy0, cx1, _cy1 = cur["rect"]
    body_x0 = min(ln["rect"][0] for ln in group[1:]) if len(group) >= 2 else px0
    max_x1 = max(ln["rect"][2] for ln in group)

    # New indented paragraph starts further right than previous body lines.
    if cx0 > body_x0 + 8.0:
        return False

    # First-line indent: line 0 starts 8..65pt to the right of body line 1.
    if len(group) == 1 and px0 > cx0 + 8.0:
        if (px0 - cx0) > 65.0:
            return False
        # Line 0 should reach reasonably close to the right edge (not a centered heading).
        if (px1 - px0) < 120.0 or px1 < cx1 - 40.0:
            return False
    else:
        if abs(cx0 - body_x0) > 7.0:
            return False

    # If the previous line was short and ended a sentence, it closed the paragraph.
    if prev_text.endswith(_TERMINAL_CHARS):
        if len(group) >= 2 and px1 < max_x1 - 32.0:
            return False
        if len(group) == 1 and px1 < cx1 - 38.0:
            return False
        # Short standalone lines (e.g. demo list/labels) shouldn't merge if gap is wide.
        if (px1 - px0) < 260.0 and dy > sz * 1.75:
            return False

    return True


def _paragraphs(block) -> list[list[dict]]:
    """Split a PyMuPDF text block into paragraphs."""
    lines = [m for ln in block.get("lines", []) if (m := _line_meta(ln)) is not None]
    groups: list[list[dict]] = []
    for ln in lines:
        if groups and _should_merge_lines(groups[-1], ln):
            groups[-1].append(ln)
        else:
            groups.append([ln])
    return groups


def _page_paragraphs(data: dict) -> list[list[dict]]:
    """Group text lines across the whole page into logical paragraphs."""
    all_lines: list[dict] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for ln in block.get("lines", []):
            m = _line_meta(ln)
            if m is not None:
                all_lines.append(m)
    # Sort primarily top-to-bottom (bucketed slightly), then left-to-right.
    all_lines.sort(key=lambda m: (round(m["rect"][1] / 2.0), m["rect"][0]))
    groups: list[list[dict]] = []
    for ln in all_lines:
        # Try matching the most recent compatible open group (handles multi-column safely).
        merged = False
        for g in reversed(groups[-4:]):
            if _should_merge_lines(g, ln):
                g.append(ln)
                merged = True
                break
        if not merged:
            groups.append([ln])
    return groups


class PdfDoc:
    """Owns a fitz.Document plus an undo history of temp snapshots."""

    def __init__(self, tmpdir: str | None = None):
        self.doc = None
        self.path: str | None = None
        self.password: str | None = None
        self._owns_tmpdir = tmpdir is None
        self.tmpdir = tmpdir or tempfile.mkdtemp(prefix="pdfstudio_")
        os.makedirs(self.tmpdir, exist_ok=True)
        self._undo: list[tuple[str, int, str]] = []
        self._redo: list[tuple[str, int, str]] = []
        self._restoring = False
        self._font_cache: dict[tuple[int, str], bytes | None] = {}

    # ------------------------------------------------------------------ open
    def open(self, path: str, password: str | None = None) -> None:
        self.close()
        doc = fitz.open(path)
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                doc.close()
                raise PermissionError("Dokumen terkunci. Password salah atau kosong.")
        self.doc = doc
        self.path = os.path.abspath(path)
        self.password = password
        self._font_cache.clear()
        self._clear_hist()

    def close(self) -> None:
        self._clear_hist()
        self._font_cache.clear()
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
        self.doc = None
        self.path = None
        self.password = None

    def cleanup(self) -> None:
        """Close the document and remove the owned temp directory."""
        self.close()
        if self._owns_tmpdir and self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

    @property
    def is_open(self) -> bool:
        return self.doc is not None

    def require(self):
        if self.doc is None:
            raise RuntimeError("Tidak ada dokumen yang terbuka.")
        return self.doc

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc else 0

    def page(self, i: int):
        return self.doc[i]

    def page_size(self, i: int) -> tuple[float, float]:
        r = self.doc[i].rect
        return r.width, r.height

    def page_label(self, i: int) -> str:
        return str(i + 1)

    # ------------------------------------------------------------- rendering
    def render(self, i: int, zoom: float, dpr: float = 1.0):
        page = self.doc[i]
        mat = fitz.Matrix(zoom * dpr, zoom * dpr)
        return page.get_pixmap(matrix=mat, alpha=False, annots=True)

    def page_annot_names(self, i: int) -> list[str]:
        return [a.type[1] for a in self.doc[i].annots() or []]

    def sample_color(self, i: int, rect, fallback=(1, 1, 1)):
        """Dominant background RGB (0..1) of an area - used to blend edited text."""
        try:
            from collections import Counter
            page = self.doc[i]
            clip = _rect(*rect) & page.rect
            if clip.is_empty:
                return fallback
            pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(1.0, 1.0), alpha=False)
            if pix.width < 1 or pix.height < 1:
                return fallback
            counts: Counter[tuple[int, int, int]] = Counter()
            step_x = max(1, pix.width // 24)
            step_y = max(1, pix.height // 12)
            for y in range(0, pix.height, step_y):
                for x in range(0, pix.width, step_x):
                    r, g, b = pix.pixel(x, y)[:3]
                    counts[(r, g, b)] += 1
            if not counts:
                return fallback
            r, g, b = counts.most_common(1)[0][0]
            if r >= 250 and g >= 250 and b >= 250:
                return (1.0, 1.0, 1.0)
            return (min(1.0, r / 255.0), min(1.0, g / 255.0), min(1.0, b / 255.0))
        except Exception:
            return fallback

    @staticmethod
    def _has_image_behind(page, rect) -> bool:
        try:
            for info in page.get_image_info(xrefs=False) or []:
                bbox = info.get("bbox")
                if bbox and not (fitz.Rect(bbox) & rect).is_empty:
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------ navigation
    def text(self, i: int) -> str:
        try:
            return self.doc[i].get_text("text")
        except Exception:
            return ""

    def words(self, i: int, clip=None):
        return self.doc[i].get_text("words", clip=clip) or []

    def _filter_search_rects(self, page, query: str, rects, *,
                             match_case: bool = False, whole_word: bool = False):
        if not match_case and not whole_word:
            return list(rects)
        out = []
        q_cmp = query if match_case else query.lower()
        for r in rects:
            try:
                exact = (page.get_text("text", clip=r + (-1.5, -1.5, 1.5, 1.5)) or "").strip()
            except Exception:
                exact = ""
            e_cmp = exact if match_case else exact.lower()
            if q_cmp not in e_cmp:
                continue
            if whole_word:
                try:
                    wide = page.get_text("text", clip=r + (-14.0, -2.0, 14.0, 2.0)) or ""
                except Exception:
                    wide = exact
                flags = 0 if match_case else re.IGNORECASE
                if not re.search(rf"(?<!\w){re.escape(query)}(?!\w)", wide, flags):
                    continue
            out.append(r)
        return out

    def search(self, query: str, start_page: int = 0, *,
               match_case: bool = False, whole_word: bool = False) -> list[tuple[int, tuple]]:
        hits = []
        if not query.strip():
            return hits
        n = self.page_count
        order = list(range(start_page, n)) + list(range(0, start_page))
        for pno in order:
            try:
                rects = self.doc[pno].search_for(query)
                rects = self._filter_search_rects(
                    self.doc[pno], query, rects,
                    match_case=match_case, whole_word=whole_word)
            except Exception:
                rects = []
            for r in rects:
                hits.append((pno, (r.x0, r.y0, r.x1, r.y1)))
        return hits

    def search_with_context(self, query: str, *, match_case: bool = False,
                            whole_word: bool = False) -> list[dict]:
        """Search entire document in page order, returning page, rect, and text snippet."""
        results: list[dict] = []
        q = (query or "").strip()
        if not q or self.doc is None:
            return results
        for pno in range(self.page_count):
            page = self.doc[pno]
            try:
                rects = page.search_for(q)
                rects = self._filter_search_rects(
                    page, q, rects, match_case=match_case, whole_word=whole_word)
            except Exception:
                rects = []
            for r in rects:
                line_clip = fitz.Rect(
                    max(page.rect.x0, r.x0 - 110.0),
                    max(page.rect.y0, r.y0 - 4.0),
                    min(page.rect.x1, r.x1 + 140.0),
                    min(page.rect.y1, r.y1 + 4.0),
                )
                try:
                    snip = " ".join((page.get_text("text", clip=line_clip) or "").split())
                except Exception:
                    snip = q
                if len(snip) > 90:
                    snip = snip[:89] + "…"
                results.append({
                    "page": pno,
                    "rect": (float(r.x0), float(r.y0), float(r.x1), float(r.y1)),
                    "snippet": snip or q,
                })
        return results

    # ------------------------------------------------------------------- OCR
    @staticmethod
    def _tesseract_available() -> bool:
        try:
            fitz.get_tessdata()
            return True
        except Exception:
            return False

    @staticmethod
    def ocr_available() -> bool:
        """True when Tesseract or the built-in Windows OCR can run."""
        if PdfDoc._tesseract_available():
            return True
        try:
            return _winocr.available()
        except Exception:
            return False

    @staticmethod
    def ocr_engine_name() -> str:
        if PdfDoc._tesseract_available():
            return "Tesseract"
        try:
            return _winocr.engine_name()
        except Exception:
            return ""

    def pages_without_text(self) -> list[int]:
        missing = []
        for i in range(self.page_count):
            try:
                text = self.doc[i].get_text("text").strip()
            except Exception:
                text = ""
            if len(text) < 8:
                missing.append(i)
        return missing

    def needs_ocr(self, pno: int) -> bool:
        """A page that is basically a scan: an image but (almost) no text."""
        if pno < 0 or pno >= self.page_count:
            return False
        try:
            page = self.doc[pno]
            if len(page.get_text("text").strip()) >= 8:
                return False
            return bool(page.get_images(full=True))
        except Exception:
            return False

    def ocr_page(self, pno: int, language: str = "eng", dpi: int = 300) -> int:
        """Add an invisible OCR text layer to a scanned page.

        Uses Tesseract when installed, otherwise the OCR engine built into
        Windows 10/11. Returns the number of recognised words.
        """
        page = self.doc[pno]
        if self._tesseract_available():
            return self._ocr_page_tesseract(page, language=language, dpi=dpi)
        if _winocr.available():
            return self._ocr_page_windows(page, dpi=dpi)
        raise RuntimeError(
            "OCR belum tersedia. Pasang Tesseract OCR, atau jalankan di "
            "Windows 10/11 yang punya bahasa OCR terpasang.")

    def _insert_word_layer(self, page, words, scale: float,
                           size_factor: float = 0.82,
                           fit_width: bool = False) -> int:
        font = None
        if fit_width:
            try:
                font = fitz.Font("helv")
            except Exception:
                font = None
        count = 0
        for x0, y0, x1, y1, word, *_rest in words:
            word = (word or "").strip()
            if not word:
                continue
            size = max(2.0, (y1 - y0) * scale * size_factor)
            if font is not None:
                target_w = max(2.0, (x1 - x0) * scale)
                unit = font.text_length(word, fontsize=1.0)
                if unit > 0:
                    size = target_w / unit
                    cap = max(2.0, (y1 - y0) * scale)
                    size = min(max(size, cap * 0.65), cap * 1.9)
            point = fitz.Point(x0 * scale, y1 * scale)
            try:
                page.insert_text(point, word, fontsize=size,
                                 fontname="helv", render_mode=3,
                                 color=(0, 0, 0))
                count += 1
            except Exception:
                continue
        return count

    def _ocr_page_tesseract(self, page, language: str = "eng",
                            dpi: int = 300) -> int:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        blob = pix.pdfocr_tobytes(compress=True, language=language)
        ocr_doc = fitz.open(stream=blob, filetype="pdf")
        try:
            ocr_page = ocr_doc[0]
            words = ocr_page.get_text("words") or []
            if not words:
                return 0
            scale = page.rect.width / max(1e-6, ocr_page.rect.width)
            return self._insert_word_layer(page, words, scale)
        finally:
            ocr_doc.close()

    def _ocr_page_windows(self, page, dpi: int = 300) -> int:
        """OCR through Windows.Media.Ocr (no external install needed)."""
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        fd, png = tempfile.mkstemp(prefix="pdfstudio_ocr_", suffix=".png")
        os.close(fd)
        try:
            pix.save(png)
            data = _winocr.recognize(png)
        finally:
            try:
                os.unlink(png)
            except Exception:
                pass
        words = []
        for line in data.get("lines", []):
            for w in line.get("words", []):
                text = str(w.get("t") or "").strip()
                try:
                    x, y = float(w["x"]), float(w["y"])
                    ww, hh = float(w["w"]), float(w["h"])
                except Exception:
                    continue
                if not text or ww <= 0 or hh <= 0:
                    continue
                words.append((x, y, x + ww, y + hh, text))
        if not words:
            return 0
        try:
            img_w = float(data.get("width") or pix.width)
        except Exception:
            img_w = float(pix.width)
        scale = page.rect.width / max(1.0, img_w)
        # Windows returns a tight box per word: fitting the Helvetica glyphs to
        # that width keeps neighbouring words from merging and matches the
        # scanned text closely enough for click-to-edit.
        return self._insert_word_layer(page, words, scale, size_factor=1.34,
                                       fit_width=True)

    def ocr_pages(self, pages: list[int], language: str = "eng",
                  progress=None) -> tuple[int, int]:
        """OCR several pages; returns (pages_done, words_added)."""
        done = words = 0
        for i, pno in enumerate(pages):
            if progress is not None and not progress(i, len(pages), pno):
                break
            words += self.ocr_page(pno, language=language)
            done += 1
        return done, words

    # ----------------------------------------------------------- annotations
    def _line_rects(self, pno: int, rect):
        page = self.doc[pno]
        words = page.get_text("words", clip=rect) or []
        lines: dict[tuple, list] = {}
        for x0, y0, x1, y1, _w, b, l, _wn in words:
            lines.setdefault((b, l), []).append(fitz.Rect(x0, y0, x1, y1))
        out = []
        for rs in lines.values():
            r = rs[0]
            for extra in rs[1:]:
                r |= extra
            out.append(r)
        return out

    def annot_text_markup(self, pno: int, rect, kind: str, color, opacity: float = 0.4) -> int:
        page = self.doc[pno]
        rect = _rect(*rect)
        targets = self._line_rects(pno, rect) or [rect]
        n = 0
        for r in targets:
            if kind == "highlight":
                a = page.add_highlight_annot(r)
            elif kind == "underline":
                a = page.add_underline_annot(r)
            elif kind == "strikeout":
                a = page.add_strikeout_annot(r)
            else:
                a = page.add_squiggly_annot(r)
            if a is None:
                continue
            a.set_colors(stroke=color)
            if kind != "highlight":
                a.set_opacity(1.0)
            else:
                a.set_opacity(opacity)
            a.set_info(title="PDF Studio", content="", subject=kind.title())
            a.update()
            n += 1
        return n

    def add_note(self, pno: int, point, text: str, color=(1.0, 0.85, 0.2)) -> None:
        page = self.doc[pno]
        a = page.add_text_annot(fitz.Point(*point), text or "Catatan")
        try:
            a.set_colors(stroke=color)
            a.set_info(title="PDF Studio", content=text or "")
            a.update()
        except Exception:
            pass

    def add_text(self, pno: int, rect, text: str, fontsize: float,
                 font: str = "Helvetica", color=(0, 0, 0), align: int = 0,
                 bold: bool = False, italic: bool = False) -> bool:
        """Insert real (selectable) text into the page content stream."""
        page = self.doc[pno]
        rect = _rect(*rect)
        rect.normalize()
        if rect.width < 6 or rect.height < 4:
            rect = fitz.Rect(rect.x0, rect.y0, rect.x0 + 180, rect.y0 + 20)
        fname = font_code(font, bold, italic)
        size = float(fontsize)
        while size > 3.5:
            rc = page.insert_textbox(rect, text, fontsize=size, fontname=fname,
                                     color=color, align=align)
            if rc >= 0:
                return True
            size -= 0.5
        # last resort: write it anyway at a generous box
        big = fitz.Rect(rect.x0, rect.y0, max(rect.x1, page.rect.x1 - 20),
                        max(rect.y1, page.rect.y1 - 20))
        try:
            page.insert_textbox(big, text, fontsize=fontsize, fontname=fname,
                                color=color, align=align)
            return True
        except Exception:
            return False

    def add_ink(self, pno: int, strokes, color, width: float = 2.0) -> None:
        if not strokes:
            return
        page = self.doc[pno]
        a = page.add_ink_annot([[(float(x), float(y)) for x, y in s]
                                for s in strokes if len(s) > 1])
        if a is None:
            return
        a.set_colors(stroke=color)
        a.set_border(width=max(0.5, width))
        a.set_info(title="PDF Studio", subject="Ink")
        a.update()

    def add_shape(self, pno: int, rect, kind: str, color, width: float = 1.5) -> None:
        page = self.doc[pno]
        r = _rect(*rect)
        if r.width < 2 or r.height < 2:
            return
        a = page.add_rect_annot(r) if kind == "rect" else page.add_circle_annot(r)
        if a is None:
            return
        a.set_colors(stroke=color)
        a.set_border(width=max(0.5, width))
        a.set_info(title="PDF Studio", subject=kind.title())
        a.update()

    def insert_image(self, pno: int, rect, image_path: str, keep_proportion: bool = True) -> bool:
        page = self.doc[pno]
        r = _rect(*rect)
        if r.width < 4 or r.height < 4:
            r = fitz.Rect(r.x0, r.y0, r.x0 + 160, r.y0 + 160)
        try:
            page.insert_image(r, filename=image_path, keep_proportion=keep_proportion, overlay=True)
            return True
        except Exception:
            return False

    def _resolve_style_font(self, page, pno: int, font: str, bold: bool,
                            italic: bool, font_name: str | None,
                            needs_unicode: bool):
        """Return (face, emb_name, fb_face, fb_name) for one (bold, italic) style."""
        import hashlib
        fb_name = font_code(font, bold, italic)
        fb_face = None
        if needs_unicode:
            ttf = _system_ttf_path(font, bold, italic)
            if ttf:
                try:
                    fb_face = fitz.Font(fontfile=ttf)
                    fb_name = "PSS" + hashlib.md5(ttf.encode("utf-8")).hexdigest()[:5].upper()
                    page.insert_font(fontname=fb_name, fontfile=ttf)
                except Exception:
                    fb_face = None
                    fb_name = font_code(font, bold, italic)
        emb_name = None
        face = None
        buf = self._embedded_font_buffer(pno, font_name) if font_name else None
        if buf:
            try:
                face = fitz.Font(fontbuffer=buf)
                emb_name = "PSF" + hashlib.md5(buf).hexdigest()[:5].upper()
                page.insert_font(fontname=emb_name, fontbuffer=buf)
            except Exception:
                face = None
                emb_name = None
        return face, emb_name, fb_face, fb_name

    def replace_text(self, pno: int, rect, new_text: str, fontsize: float,
                     font: str, color, bg, bold: bool = False,
                     italic: bool = False, baseline: float | None = None,
                     single: bool = False, font_name: str | None = None,
                     line_gap: float | None = None, indent: float = 0.0,
                     align: str = "left",
                     rich_runs: list[tuple[str, bool, bool]] | None = None,
                     style_fonts: dict[tuple[bool, bool], str] | None = None,
                     write_rect=None) -> bool:
        """Replace the text inside *rect* (redact + retype).

        Inline edits (a *baseline* is given) reuse the font embedded in the PDF
        for every glyph it contains and fall back per-character for the rest,
        so the result blends in with the rest of the page.
        """
        page = self.doc[pno]
        r = _rect(*rect)
        wr = _rect(*write_rect) if write_rect is not None else r
        redact_fill = bg if self._has_image_behind(page, r) else False
        page.add_redact_annot(r, fill=redact_fill)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
        text = (new_text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")
        if not text.strip():
            return True

        needs_uni = any(ord(ch) > 126 for ch in text)
        base_style = (bool(bold), bool(italic))
        face, emb_name, fb_face, fb_name = self._resolve_style_font(
            page, pno, font, bool(bold), bool(italic), font_name, needs_uni)

        if baseline is not None:
            style_map = {base_style: (face, emb_name, fb_face, fb_name)}
            cleaned_runs = None
            if rich_runs:
                cleaned_runs = []
                for chunk, rb, ri in rich_runs:
                    c = (chunk or "").replace("\r\n", "\n").replace("\r", "\n")
                    if c:
                        st = (bool(rb), bool(ri))
                        cleaned_runs.append((c, st[0], st[1]))
                        if st not in style_map:
                            sf_name = (style_fonts or {}).get(st)
                            style_map[st] = self._resolve_style_font(
                                page, pno, font, st[0], st[1], sf_name, needs_uni)
            return self._insert_inline_flow(
                page, wr, text, float(fontsize), baseline,
                float(line_gap or fontsize * 1.35),
                color, face, emb_name, fb_name, single,
                indent=float(indent or 0.0), align=align or "left",
                fb_face=fb_face, rich_runs=cleaned_runs, style_map=style_map,
                base_style=base_style)

        # Box based insertion (drag-a-rectangle editor path).
        if face is not None:
            try:
                chars = {ord(ch) for ch in text if ch not in "\n\t"}
                if chars and all(face.has_glyph(cp) for cp in chars):
                    return self._insert_paragraph(
                        page, r, text, float(fontsize), emb_name, color,
                        None, single,
                        lambda s, size: face.text_length(s, fontsize=size))
            except Exception:
                pass
        return self._insert_paragraph(
            page, r, text, float(fontsize), fb_name, color, None, single,
            lambda s, size: fitz.get_text_length(s, fontname=fb_name, fontsize=size))

    def _insert_inline_flow(self, page, r, text, size, baseline, gap, color,
                            face, emb_name, fb_name, single,
                            indent: float = 0.0, align: str = "left",
                            fb_face=None,
                            rich_runs: list[tuple[str, bool, bool]] | None = None,
                            style_map: dict | None = None,
                            base_style: tuple[bool, bool] = (False, False)) -> bool:
        """Typeset wrapped text with per-glyph font switching, mixed styles, indent & justify."""
        if not style_map:
            style_map = {base_style: (face, emb_name, fb_face, fb_name)}
        font_faces: dict[str, object] = {}
        for _st, (f_emb, n_emb, f_fb, n_fb) in style_map.items():
            if f_emb is not None and n_emb:
                font_faces[n_emb] = f_emb
            if f_fb is not None and n_fb:
                font_faces[n_fb] = f_fb

        glyph_ok: dict[tuple[tuple[bool, bool], str], bool] = {}

        def font_for(ch: str, st: tuple[bool, bool] = base_style) -> str:
            f_emb, n_emb, _f_fb, n_fb = style_map.get(st, style_map[base_style])
            if f_emb is None or not n_emb or ch in "\n\t":
                return n_fb
            key = (st, ch)
            ok = glyph_ok.get(key)
            if ok is None:
                ok = bool(f_emb.has_glyph(ord(ch)))
                glyph_ok[key] = ok
            return n_emb if ok else n_fb

        def width_of(chunk: str, fname: str, sz: float) -> float:
            fobj = font_faces.get(fname)
            if fobj is not None:
                return fobj.text_length(chunk, fontsize=sz)
            return fitz.get_text_length(chunk, fontname=fname, fontsize=sz)

        def runs(word):
            """Merge a word into runs of the same font (kerning happens inside)."""
            out: list[list[str]] = []
            for ch, fn in word:
                if out and out[-1][1] == fn:
                    out[-1][0] += ch
                else:
                    out.append([ch, fn])
            return [(chunk, fn) for chunk, fn in out]

        def word_width(word, sz: float) -> float:
            return sum(width_of(chunk, fn, sz) for chunk, fn in runs(word))

        # Slightly generous so rounding/kerning never wraps a line that fits.
        limit = r.width + 0.75
        ind = max(0.0, min(float(indent), max(0.0, r.width * 0.4)))

        char_stream: list[tuple[str, tuple[bool, bool]]] = []
        if rich_runs:
            for chunk, rb, ri in rich_runs:
                st = (bool(rb), bool(ri))
                for ch in chunk:
                    char_stream.append((ch, st))
            # Strip leading/trailing newlines consistently
            while char_stream and char_stream[0][0] == "\n":
                char_stream.pop(0)
            while char_stream and char_stream[-1][0] == "\n":
                char_stream.pop()
        else:
            char_stream = [(ch, base_style) for ch in text]

        def build(sz: float):
            lines: list[dict] = [{"words": [], "indented": True, "hard_end": True}]
            line_w = 0.0
            word: list[tuple[str, str]] = []
            space_font = font_for(" ", base_style)
            space_w = width_of(" ", space_font, sz)

            def cur_limit() -> float:
                return max(24.0, limit - (ind if lines[-1]["indented"] else 0.0))

            def flush_word() -> None:
                nonlocal line_w
                if not word:
                    return
                ww = word_width(word, sz)
                sep = space_w if lines[-1]["words"] else 0.0
                if lines[-1]["words"] and line_w + sep + ww > cur_limit():
                    lines[-1]["hard_end"] = False
                    lines.append({"words": [], "indented": False, "hard_end": True})
                    line_w = 0.0
                    sep = 0.0
                lines[-1]["words"].append(list(word))
                line_w += sep + ww
                word.clear()

            for ch, st in char_stream:
                if ch == "\n":
                    flush_word()
                    lines[-1]["hard_end"] = True
                    lines.append({"words": [], "indented": True, "hard_end": True})
                    line_w = 0.0
                elif ch == " ":
                    flush_word()
                else:
                    word.append((ch, font_for(ch, st)))
            flush_word()
            return lines

        # A single line that grew a little: shrink to keep it on one line.
        if single and "\n" not in text and len(build(size)) > 1:
            s = size
            while s > size * 0.72:
                s -= 0.25
                if len(build(s)) == 1:
                    size = s
                    break

        lines = build(size)
        space_font = font_for(" ")
        base_space_w = width_of(" ", space_font, size)

        for i, line in enumerate(lines):
            words = line["words"]
            if not words:
                continue
            line_x0 = r.x0 + (ind if line["indented"] else 0.0)
            y = baseline + i * gap
            # Compute word spacing (justify non-final wrapped lines if paragraph was justified)
            word_widths = [word_width(w, size) for w in words]
            space_w = base_space_w
            if align == "justify" and not line["hard_end"] and len(words) >= 2:
                avail = (r.x1 - line_x0) - sum(word_widths)
                gaps_n = len(words) - 1
                if avail > base_space_w * gaps_n:
                    cand = avail / gaps_n
                    if cand <= base_space_w * 3.5:
                        space_w = cand
            x = line_x0
            for wi, w in enumerate(words):
                for chunk, fname in runs(w):
                    page.insert_text((x, y), chunk, fontname=fname,
                                     fontsize=size, color=color)
                    x += width_of(chunk, fname, size)
                if wi + 1 < len(words):
                    x += space_w
        return True

    def _insert_paragraph(self, page, r, text, size, fname, color,
                          baseline, single, measure) -> bool:
        """Insert text keeping the original baseline / paragraph box."""
        if single and baseline is not None and "\n" not in text:
            if measure(text, size) <= r.width * 1.02:
                page.insert_text((r.x0, baseline), text, fontname=fname,
                                 fontsize=size, color=color)
                return True
            # A little longer: shrink slightly so it stays on one line.
            s = size
            while s > size * 0.72:
                s -= 0.25
                if measure(text, s) <= r.width * 1.02:
                    page.insert_text((r.x0, baseline), text, fontname=fname,
                                     fontsize=s, color=color)
                    return True
            # Much longer: wrap below the original line at full size.
            tall = fitz.Rect(r.x0 - 0.4, baseline - size * 1.15,
                             r.x1 + 0.4,
                             min(page.rect.y1 - 2, baseline + size * 4.5))
            try:
                page.insert_textbox(tall, text, fontsize=size, fontname=fname,
                                    color=color, align=0)
                return True
            except Exception:
                return False

        box = fitz.Rect(r.x0 - 0.4, r.y0 - 0.4, r.x1 + 0.4, r.y1 + 0.8)
        s = size
        while s >= 4.5:
            rc = page.insert_textbox(box, text, fontsize=s, fontname=fname,
                                     color=color, align=0)
            if rc >= 0:
                return True
            s -= 0.25
        tall = fitz.Rect(r.x0 - 0.4, r.y0 - 0.4, r.x1 + 0.4,
                         min(page.rect.y1 - 2, r.y0 + max(r.height * 4, size * 5)))
        try:
            page.insert_textbox(tall, text, fontsize=size, fontname=fname,
                                color=color, align=0)
            return True
        except Exception:
            return False

    def embedded_font(self, pno: int, font_name: str | None):
        """Public access to the embedded font bytes (used by the UI preview)."""
        return self._embedded_font_buffer(pno, font_name)

    def _embedded_font_buffer(self, pno: int, font_name: str | None):
        """Bytes of the embedded font matching *font_name* (subset-aware)."""
        if not font_name:
            return None
        key = (pno, font_name)
        if key in self._font_cache:
            return self._font_cache[key]
        result = None
        target = font_name.split("+")[-1].replace(" ", "").replace("-", "").lower()
        try:
            for entry in self.doc[pno].get_fonts(full=True):
                xref, ext, _typ, basefont = entry[0], entry[1], entry[2], entry[3]
                name = (basefont or "").split("+")[-1]
                if name.replace(" ", "").replace("-", "").lower() != target:
                    continue
                if ext not in ("ttf", "otf", "cff", "ttc", "pfb"):
                    continue
                _n, _e, _t, buf = self.doc.extract_font(xref)
                if buf:
                    result = buf
                    break
        except Exception:
            result = None
        self._font_cache[key] = result
        return result

    def text_at(self, pno: int, point, tolerance: float = 9.0):
        """Return the paragraph under *point* (for in-place text editing)."""
        page = self.doc[pno]
        try:
            data = page.get_text("dict")
        except Exception:
            return None
        x, y = float(point[0]), float(point[1])
        best = None
        best_dist = 1e9
        for group in _page_paragraphs(data):
            for ln in group:
                rx0, ry0, rx1, ry1 = ln["rect"]
                dx = max(rx0 - x, 0.0, x - rx1)
                dy = max(ry0 - y, 0.0, y - ry1)
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < best_dist - 0.01:
                    best_dist = dist
                    best = group
        if best is None or best_dist > tolerance:
            return None
        return self._group_info(pno, best)

    def _group_info(self, pno: int, group) -> dict:
        """Describe one paragraph (a group of wrapped lines) for editing."""
        rects = [ln["rect"] for ln in group]
        x0 = min(r[0] for r in rects)
        y0 = min(r[1] for r in rects)
        x1 = max(r[2] for r in rects)
        y1 = max(r[3] for r in rects)
        first = group[0]["spans"][0]
        size = float(first.get("size") or 10.0)

        parts: list[str] = []
        rich_runs: list[list] = []
        style_fonts: dict[tuple[bool, bool], str] = {}
        for ln in group:
            t = ln["text"].strip()
            join_space = bool(parts and not (parts[-1].endswith("-") or t[:1] in ".,;:)]}"))
            if parts and not join_space:
                parts[-1] += t
            else:
                parts.append(t)
            if join_space and rich_runs:
                rich_runs[-1][0] += " "
            # Extract per-span bold/italic runs for this line
            ln_raw = "".join(s["text"] for s in ln["spans"])
            lead = len(ln_raw) - len(ln_raw.lstrip())
            trail = len(ln_raw) - len(ln_raw.rstrip())
            end_limit = len(ln_raw) - trail
            pos = 0
            for sp in ln["spans"]:
                stxt = sp.get("text") or ""
                s_end = pos + len(stxt)
                lo = max(pos, lead)
                hi = min(s_end, end_limit)
                if hi > lo:
                    chunk = stxt[lo - pos:hi - pos]
                    sb, si = _span_bold(sp), _span_italic(sp)
                    sfont = sp.get("font") or ""
                    if sfont and (sb, si) not in style_fonts:
                        style_fonts[(sb, si)] = sfont
                    if rich_runs and rich_runs[-1][1] == sb and rich_runs[-1][2] == si:
                        rich_runs[-1][0] += chunk
                    else:
                        rich_runs.append([chunk, sb, si])
                pos = s_end
        text = " ".join(parts)
        rich_tuples = [(c, b, it) for c, b, it in rich_runs if c]

        font_raw = first.get("font") or "Helvetica"
        origins = []
        for ln in group:
            sp = ln["spans"][0]
            if sp.get("origin"):
                origins.append(float(sp["origin"][1]))
        gaps = [b - a for a, b in zip(origins, origins[1:]) if b - a > 0.5]
        line_gap = sorted(gaps)[len(gaps) // 2] if gaps else size * 1.35

        indent = max(0.0, float(rects[0][0]) - x0) if len(group) >= 2 else 0.0
        align = "left"
        if len(group) >= 2 and (x1 - x0) >= 160.0:
            body_lines = rects[:-1]
            right_flush = sum(1 for r in body_lines if abs(r[2] - x1) <= 6.0)
            if right_flush >= max(1, len(body_lines) - 1):
                align = "justify"

        return {
            "rect": (x0, y0, x1, y1),
            "lines": [ln["rect"] for ln in group],
            "text": text,
            "font": font_family(font_raw),
            "font_name": font_raw,
            "font_display": display_font_name(font_raw),
            "size": size,
            "color": span_color(first),
            "bold": _span_bold(first),
            "italic": _span_italic(first),
            "baseline": float(first.get("origin", (x0, y1))[1]) if first.get("origin") else None,
            "line_gap": line_gap,
            "indent": indent,
            "align": align,
            "rich_runs": rich_tuples,
            "style_fonts": style_fonts,
            "single": len(group) == 1,
            "bg": self.sample_color(pno, (x0, y0, x1, y1)),
        }

    def redact(self, pno: int, rect) -> None:
        page = self.doc[pno]
        page.add_redact_annot(_rect(*rect), fill=(0, 0, 0))
        page.apply_redactions()

    # ------------------------------------------------------------------ forms
    def widgets(self, pno: int) -> list[dict]:
        page = self.doc[pno]
        out = []
        try:
            for w in page.widgets() or []:
                out.append({
                    "name": w.field_name,
                    "label": w.field_label or w.field_name,
                    "type": w.field_type_string,
                    "value": w.field_value,
                    "rect": (w.rect.x0, w.rect.y0, w.rect.x1, w.rect.y1),
                    "choices": list(w.choice_values or []),
                })
        except Exception:
            pass
        return out

    def set_widget(self, pno: int, field_name: str, value) -> bool:
        try:
            for w in self.doc[pno].widgets() or []:
                if w.field_name != field_name:
                    continue
                if w.field_type_string in ("CheckBox", "RadioButton"):
                    w.field_value = bool(value)
                else:
                    w.field_value = "" if value is None else str(value)
                w.update()
                return True
        except Exception:
            return False
        return False

    def add_form_field(self, pno: int, rect, kind: str, name: str = "", *,
                       options: list[str] | None = None, default: str = "",
                       fontsize: float = 11.0) -> str:
        """Create a new interactive AcroForm widget (text / checkbox / combobox)."""
        page = self.doc[pno]
        r = _rect(*rect)
        if r.width < 12 or r.height < 12:
            if kind == "checkbox":
                r = fitz.Rect(r.x0, r.y0, r.x0 + 18, r.y0 + 18)
            else:
                r = fitz.Rect(r.x0, r.y0, r.x0 + 160, r.y0 + 24)
        existing = {w.field_name for p in self.doc for w in (p.widgets() or []) if w.field_name}
        base = re.sub(r"[^a-zA-Z0-9_]+", "_", (name or kind or "field").strip()).strip("_") or "field"
        fname = base
        idx = 2
        while fname in existing:
            fname = f"{base}_{idx}"
            idx += 1

        w = fitz.Widget()
        w.rect = r
        w.field_name = fname
        w.border_color = (0.25, 0.45, 0.78)
        w.border_width = 1.0
        w.fill_color = (0.95, 0.97, 1.0)
        w.text_color = (0.05, 0.05, 0.05)
        w.text_fontsize = max(6.0, float(fontsize))
        if kind == "checkbox":
            w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
            w.field_value = False
        elif kind == "combobox":
            w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
            choices = [o.strip() for o in (options or []) if o.strip()] or ["Pilihan 1", "Pilihan 2"]
            w.choice_values = choices
            w.field_value = default if default in choices else choices[0]
        else:
            w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            w.field_value = str(default or "")
        page.add_widget(w)
        return fname

    # ------------------------------------------------------------- crop & images
    def crop_pages(self, pages: list[int] | None, *, top: float = 0.0,
                   bottom: float = 0.0, left: float = 0.0, right: float = 0.0) -> int:
        """Trim page margins in points by shrinking each page's CropBox."""
        targets = list(range(self.page_count)) if pages is None else [
            p for p in pages if 0 <= p < self.page_count
        ]
        changed = 0
        for pno in targets:
            page = self.doc[pno]
            cb = fitz.Rect(page.cropbox)
            new_r = fitz.Rect(
                cb.x0 + max(0.0, left),
                cb.y0 + max(0.0, top),
                cb.x1 - max(0.0, right),
                cb.y1 - max(0.0, bottom),
            )
            if new_r.width < 72.0 or new_r.height < 72.0:
                continue
            page.set_cropbox(new_r)
            changed += 1
        return changed

    def auto_crop_pages(self, pages: list[int] | None, margin: float = 14.0) -> int:
        """Automatically crop excess white margins around visible page content."""
        targets = list(range(self.page_count)) if pages is None else [
            p for p in pages if 0 <= p < self.page_count
        ]
        changed = 0
        pad = max(0.0, float(margin))
        for pno in targets:
            page = self.doc[pno]
            mb = fitz.Rect(page.mediabox)
            bounds: list[fitz.Rect] = []
            for b in page.get_text("blocks") or []:
                if len(b) >= 4:
                    r = fitz.Rect(b[:4])
                    if not r.is_empty:
                        bounds.append(r)
            for info in page.get_image_info(xrefs=False) or []:
                if info.get("bbox"):
                    r = fitz.Rect(info["bbox"])
                    if not r.is_empty and (r.width < mb.width * 0.98 or r.height < mb.height * 0.98):
                        bounds.append(r)
            for dr in page.get_drawings() or []:
                if dr.get("rect"):
                    r = fitz.Rect(dr["rect"])
                    if not r.is_empty and (r.width < mb.width * 0.98 or r.height < mb.height * 0.98):
                        bounds.append(r)
            if not bounds:
                continue
            union = fitz.Rect(bounds[0])
            for r in bounds[1:]:
                union |= r
            new_r = (union + (-pad, -pad, pad, pad)) & mb
            if new_r.width < 72.0 or new_r.height < 72.0:
                continue
            page.set_cropbox(new_r)
            changed += 1
        return changed

    def reset_crop(self, pages: list[int] | None = None) -> int:
        """Restore CropBox back to full MediaBox."""
        targets = list(range(self.page_count)) if pages is None else [
            p for p in pages if 0 <= p < self.page_count
        ]
        for pno in targets:
            page = self.doc[pno]
            page.set_cropbox(page.mediabox)
        return len(targets)

    def page_images(self, pno: int) -> list[dict]:
        """List embedded images on page *pno* with xref, bbox, dimensions, and size."""
        page = self.doc[pno]
        out: list[dict] = []
        seen: set[int] = set()
        for info in page.get_image_info(xrefs=True) or []:
            xref = int(info.get("xref") or 0)
            if not xref or xref in seen:
                continue
            seen.add(xref)
            bbox = info.get("bbox") or (0, 0, 0, 0)
            w = int(info.get("width") or 0)
            h = int(info.get("height") or 0)
            ext = "png"
            size = int(info.get("size") or 0)
            try:
                ex = self.doc.extract_image(xref)
                if ex:
                    ext = ex.get("ext") or ext
                    size = len(ex.get("image") or b"") or size
                    w = int(ex.get("width") or w)
                    h = int(ex.get("height") or h)
            except Exception:
                pass
            if w <= 1 and h <= 1:
                continue
            out.append({
                "xref": xref,
                "bbox": tuple(float(v) for v in bbox),
                "width": w,
                "height": h,
                "ext": ext,
                "size": size,
            })
        return out

    def delete_page_image(self, pno: int, xref: int) -> bool:
        page = self.doc[pno]
        try:
            page.delete_image(int(xref))
            return True
        except Exception:
            return False

    def replace_page_image(self, pno: int, xref: int, image_path: str) -> bool:
        page = self.doc[pno]
        try:
            page.replace_image(int(xref), filename=image_path)
            return True
        except Exception:
            return False

    def extract_page_image(self, xref: int, out_path: str) -> bool:
        ex = self.doc.extract_image(int(xref))
        if not ex or not ex.get("image"):
            return False
        raw = ex["image"]
        ext = (ex.get("ext") or "png").lower()
        target_ext = os.path.splitext(out_path)[1].lstrip(".").lower()
        if target_ext == "png" and ext != "png":
            pix = fitz.Pixmap(self.doc, int(xref))
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            pix.save(out_path)
        else:
            with open(out_path, "wb") as fh:
                fh.write(raw)
        return True

    # ------------------------------------------------------------- page edits
    def rotate_page(self, pno: int, delta: int) -> None:
        page = self.doc[pno]
        page.set_rotation((page.rotation + delta) % 360)

    def delete_page(self, pno: int) -> None:
        self.doc.delete_page(pno)

    def insert_blank(self, pno: int) -> None:
        ref = self.doc[min(pno, self.page_count - 1)]
        self.doc.new_page(pno, width=ref.rect.width, height=ref.rect.height)

    def move_page(self, src: int, dst: int) -> None:
        self.doc.move_page(src, dst)

    def extract(self, pages: list[int], out_path: str) -> None:
        new = fitz.open()
        pages = sorted(set(p for p in pages if 0 <= p < self.page_count))
        if not pages:
            raise ValueError("Tidak ada halaman yang dipilih.")
        runs = []
        start = prev = pages[0]
        for p in pages[1:]:
            if p == prev + 1:
                prev = p
            else:
                runs.append((start, prev))
                start = prev = p
        runs.append((start, prev))
        for a, b in runs:
            new.insert_pdf(self.doc, from_page=a, to_page=b)
        new.save(out_path, garbage=3, deflate=True)
        new.close()

    def merge(self, other_path: str) -> int:
        src = fitz.open(other_path)
        if src.needs_pass:
            src.close()
            raise PermissionError("PDF yang digabung terkunci password.")
        before = self.page_count
        self.doc.insert_pdf(src)
        src.close()
        return self.page_count - before

    def export_png(self, pno: int, out_path: str, dpi: int = 200) -> None:
        pix = self.doc[pno].get_pixmap(dpi=dpi)
        pix.save(out_path)

    def export_all_png(self, folder: str, dpi: int = 150) -> int:
        n = 0
        for i in range(self.page_count):
            out = os.path.join(folder, f"page_{i + 1:03d}.png")
            self.export_png(i, out, dpi)
            n += 1
        return n

    # ------------------------------------------------------------ annotations
    def _annot_kind(self, a) -> str:
        t = (a.type[1] or "").lower()
        if t == "line":
            try:
                ends = a.line_ends or (0, 0)
                if ends[0] or ends[1]:
                    return "arrow"
            except Exception:
                pass
            return "line"
        return {
            "freetext": "freetext", "square": "rect", "circle": "ellipse",
            "polygon": "polygon", "polyline": "polyline", "ink": "ink",
            "text": "note", "stamp": "stamp", "highlight": "highlight",
            "underline": "underline", "strikeout": "strikeout",
            "squiggly": "squiggly",
        }.get(t, t or "annot")

    def annotations(self, pno: int) -> list[dict]:
        """Every annotation on a page with editable properties."""
        page = self.doc[pno]
        out = []
        try:
            annots = list(page.annots() or [])
        except Exception:
            return out
        for a in annots:
            try:
                info = a.info or {}
                colors = a.colors or {}
                border = a.border or {}
                r = a.rect
                out.append({
                    "xref": a.xref,
                    "type": a.type[1],
                    "kind": self._annot_kind(a),
                    "rect": (r.x0, r.y0, r.x1, r.y1),
                    "content": a.info.get("content", "") if a.info else "",
                    "title": info.get("title", ""),
                    "subject": info.get("subject", ""),
                    "stroke": tuple(colors.get("stroke") or ()),
                    "fill": tuple(colors.get("fill") or ()),
                    "width": float(border.get("width") or 1.0),
                    "opacity": float(a.opacity if a.opacity is not None else 1.0),
                    "line_ends": tuple(getattr(a, "line_ends", ()) or ()),
                })
            except Exception:
                continue
        return out

    def _annot_by_xref(self, pno: int, xref: int):
        page = self.doc[pno]
        for a in page.annots() or []:
            if a.xref == xref:
                return page, a
        return None, None

    def _freetext_style(self, a) -> tuple[tuple, float, bool]:
        """Read colour, size and weight back from an existing FreeText."""
        color = (0.0, 0.0, 0.0)
        size = 12.0
        try:
            da = self.doc.xref_get_key(a.xref, "DA")[1] or ""
        except Exception:
            da = ""
        import re
        m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da)
        if m:
            color = tuple(float(v) for v in m.groups())
        m = re.search(r"([\d.]+)\s+Tf", da)
        if m:
            size = float(m.group(1))
        subject = ((a.info or {}).get("subject") or "").lower()
        return color, size, subject == "stamp"

    def update_annotation(self, pno: int, xref: int, **kw) -> bool:
        """Move/resize/recolour an existing annotation."""
        page, a = self._annot_by_xref(pno, xref)
        if a is None:
            return False
        is_free = (a.type[1] or "").lower() == "freetext"
        try:
            if "rect" in kw and kw["rect"] is not None:
                a.set_rect(_rect(*kw["rect"]))
            color = kw.get("color")
            fill = kw.get("fill")
            if is_free:
                if fill is not None:
                    # PyMuPDF stores FreeText background in /C
                    self.doc.xref_set_key(a.xref, "C", "[%g %g %g]" % tuple(fill))
            else:
                if color is not None or fill is not None:
                    old = a.colors or {}
                    a.set_colors(stroke=color if color is not None else old.get("stroke"),
                                 fill=fill if fill is not None else old.get("fill"))
            if kw.get("width") is not None:
                a.set_border(width=float(kw["width"]))
            if kw.get("opacity") is not None:
                a.set_opacity(float(kw["opacity"]))
            if kw.get("content") is not None or kw.get("title") is not None:
                info = a.info or {}
                a.set_info(title=kw.get("title", info.get("title", "")),
                           content=kw.get("content", info.get("content", "")),
                           subject=info.get("subject", ""))
            if kw.get("line_ends") is not None:
                a.set_line_ends(*kw["line_ends"])
            if is_free and (color is not None or kw.get("content") is not None):
                old_color, size, bold = self._freetext_style(a)
                self._style_freetext(
                    a, kw.get("content") or (a.info or {}).get("content") or " ",
                    color if color is not None else old_color, size,
                    bold=bold, align="center" if bold else "left")
            a.update()
            return True
        except Exception:
            return False

    def delete_annotation(self, pno: int, xref: int) -> bool:
        page, a = self._annot_by_xref(pno, xref)
        if a is None:
            return False
        try:
            page.delete_annot(a)
            return True
        except Exception:
            return False

    # ------------------------------------------- flattened highlight cleanup
    @staticmethod
    def _is_pale_highlight_color(rgb) -> bool:
        """True for pale yellow highlights or pale gray edit-shadow boxes."""
        try:
            r, g, b = (float(v) for v in rgb[:3])
        except Exception:
            return False
        pale_yellow = (r >= 0.90 and g >= 0.85 and 0.55 <= b <= 0.90
                       and (r - b) >= 0.08 and (g - b) >= 0.05)
        hi = max(r, g, b)
        lo = min(r, g, b)
        pale_gray = (0.86 <= lo <= 0.998 and hi < 0.999 and (hi - lo) <= 0.025)
        return pale_yellow or pale_gray

    def _highlight_fills(self, pno: int):
        """(rect, fill) pairs of pale-yellow bands that sit behind real text."""
        page = self.doc[pno]
        out = []
        try:
            drawings = page.get_drawings()
        except Exception:
            return out
        for d in drawings:
            fill = d.get("fill")
            if not fill or "f" not in (d.get("type") or ""):
                continue
            if not self._is_pale_highlight_color(fill):
                continue
            rect = fitz.Rect(d["rect"])
            if rect.width < 12 or rect.height < 2 or rect.height > 45:
                continue
            try:
                if not page.get_text("words", clip=rect):
                    continue
            except Exception:
                continue
            out.append((rect, tuple(round(float(v), 4) for v in fill[:3])))
        return out

    def highlight_bands(self, pno: int) -> list[tuple]:
        """Baked-in yellow highlight bands on the page (not annotations)."""
        return [(r.x0, r.y0, r.x1, r.y1)
                for r, _fill in self._highlight_fills(pno)]

    def remove_highlight_bands(self, pno: int) -> int:
        """Turn pale-yellow page backgrounds white while keeping the text.

        Only page content is touched. Bright yellow highlight *annotations*
        must be removed with :meth:`delete_annotation` first.
        """
        fills = self._highlight_fills(pno)
        colors = {fill for _r, fill in fills}
        if not colors:
            return 0
        page = self.doc[pno]
        rgb_pat = re.compile(rb"([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+(rg|RG)\b")
        gray_pat = re.compile(rb"(?<![0-9.\-])([0-9.]+)\s+(g|G)\b")
        changed = 0
        for xref in page.get_contents():
            try:
                data = self.doc.xref_stream(xref)
            except Exception:
                continue
            if not data:
                continue

            def repl_rgb(m):
                nonlocal changed
                vals = tuple(round(float(m.group(i)), 4) for i in (1, 2, 3))
                if not any(all(abs(vals[i] - c[i]) <= 0.02 for i in range(3))
                           for c in colors):
                    return m.group(0)
                changed += 1
                return b"1 1 1 " + m.group(4)

            def repl_gray(m):
                nonlocal changed
                val = round(float(m.group(1)), 4)
                if not any(all(abs(val - c[i]) <= 0.02 for i in range(3))
                           for c in colors):
                    return m.group(0)
                changed += 1
                return b"1 " + m.group(2)

            new = rgb_pat.sub(repl_rgb, data)
            new = gray_pat.sub(repl_gray, new)
            if new != data:
                try:
                    self.doc.update_stream(xref, new)
                except Exception:
                    continue
        if changed:
            try:
                self.doc.reload_page(page)
            except Exception:
                pass
        return changed

    def add_line(self, pno: int, p1, p2, color, width: float = 1.5,
                 arrow: bool = False) -> int | None:
        page = self.doc[pno]
        a = page.add_line_annot(tuple(p1), tuple(p2))
        if a is None:
            return None
        a.set_colors(stroke=color)
        a.set_border(width=max(0.5, float(width)))
        if arrow:
            a.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
        a.set_info(title="PDF Studio", subject="Arrow" if arrow else "Line")
        a.update()
        return a.xref

    def add_polyline(self, pno: int, points, color, width: float = 1.5,
                     closed: bool = False) -> int | None:
        page = self.doc[pno]
        pts = [tuple(p) for p in points if p]
        if len(pts) < 2:
            return None
        a = (page.add_polygon_annot(pts) if closed
             else page.add_polyline_annot(pts))
        if a is None:
            return None
        a.set_colors(stroke=color)
        a.set_border(width=max(0.5, float(width)))
        a.set_info(title="PDF Studio", subject="Polygon" if closed else "Polyline")
        a.update()
        return a.xref

    def _style_freetext(self, a, text: str, color, fontsize: float = 12.0,
                        bold: bool = False, align: str = "center") -> None:
        """Give a FreeText annotation real coloured rich text.

        PyMuPDF ignores ``text_color`` when ``richtext=True``, so the running
        content and the default appearance are written by hand.
        """
        import xml.sax.saxutils as sx
        doc = self.doc
        rr, gg, bb = (float(c) for c in tuple(color)[:3])
        hexcol = "#%02x%02x%02x" % (round(rr * 255), round(gg * 255), round(bb * 255))
        family = "Helvetica-Bold" if bold else "Helvetica"
        body = sx.escape(text or "")
        xml = ('<body xmlns="http://www.w3.org/1999/xtml">'
               f'<p style="text-align:{align};font-size:{float(fontsize):g}pt;'
               f'font-family:{family};color:{hexcol}">{body}</p>'
               '</body>')
        try:
            doc.xref_set_key(a.xref, "RC", fitz.get_pdf_str(xml))
            doc.xref_set_key(
                a.xref, "DA",
                "(%g %g %g rg %g %g %g RG /Helv %g Tf)"
                % (rr, gg, bb, rr, gg, bb, float(fontsize)))
            a.update()
        except Exception:
            pass

    def add_callout(self, pno: int, rect, text: str, target=None,
                    color=(0.15, 0.15, 0.15), fill=(1.0, 1.0, 0.85),
                    fontsize: float = 10) -> int | None:
        page = self.doc[pno]
        r = _rect(*rect)
        if r.width < 30 or r.height < 16:
            r = fitz.Rect(r.x0, r.y0, r.x0 + 190, r.y0 + 54)
        try:
            a = page.add_freetext_annot(
                r, text or "Catatan", fontsize=max(6, float(fontsize)),
                fontname="helv", text_color=tuple(color), fill_color=tuple(fill),
                richtext=True, border_color=tuple(color), border_width=1,
                align=0)
        except Exception:
            return None
        if target is not None:
            d = self.doc
            tx, ty = float(target[0]), float(target[1])
            # anchor line from the nearest box edge
            ax = min(max(tx, r.x0), r.x1)
            ay = r.y1
            d.xref_set_key(a.xref, "CL", "[%g %g %g %g]" % (tx, ty, ax, ay))
            d.xref_set_key(a.xref, "IT", "/FreeTextCallout")
        a.set_info(title="PDF Studio", content=text or "")
        self._style_freetext(a, text or "Catatan", color,
                             max(6, float(fontsize)), bold=False, align="left")
        return a.xref

    def add_stamp_text(self, pno: int, rect, text: str, color=(0.8, 0.1, 0.1),
                       fill=(1, 1, 1), fontsize: float = 18,
                       border: bool = True) -> int | None:
        page = self.doc[pno]
        r = _rect(*rect)
        if r.width < 24 or r.height < 12:
            r = fitz.Rect(r.x0, r.y0, r.x0 + 170, r.y0 + 46)
        try:
            a = page.add_freetext_annot(
                r, text or "DRAFT", fontsize=max(6, float(fontsize)),
                fontname="hebo", text_color=tuple(color), fill_color=tuple(fill),
                richtext=True, border_color=tuple(color) if border else None,
                border_width=2 if border else 0, align=1)
        except Exception:
            return None
        a.set_info(title="PDF Studio", subject="Stamp", content=text or "")
        self._style_freetext(a, text or "DRAFT", color,
                             max(6, float(fontsize)), bold=True, align="center")
        return a.xref

    # ---------------------------------------------------------- search/replace
    def _write_line(self, page, point, text, size, font_name, font,
                    color, bold=False, italic=False) -> None:
        """Write one line at a baseline, reusing the embedded font when possible."""
        buf = self._embedded_font_buffer(0, font_name) if font_name else None
        fname = None
        face = None
        if buf:
            try:
                face = fitz.Font(fontbuffer=buf)
                import hashlib
                fname = "PSR" + hashlib.md5(buf).hexdigest()[:5].upper()
                page.insert_font(fontname=fname, fontbuffer=buf)
            except Exception:
                face, fname = None, None
        if face is not None:
            try:
                if all(face.has_glyph(ord(c)) for c in text if c not in "\n\t"):
                    page.insert_text(tuple(point), text, fontsize=float(size),
                                     fontname=fname, color=tuple(color))
                    return
            except Exception:
                pass
        page.insert_text(tuple(point), text, fontsize=float(size),
                         fontname=font_code(font or "Helvetica", bold, italic),
                         color=tuple(color))

    def search_replace(self, query: str, replacement: str, pages=None, *,
                       match_case: bool = False, whole_word: bool = False,
                       regex: bool = False) -> list[tuple[int, int]]:
        """Replace matches inside each paragraph, keeping the original font.

        Returns ``[(page, replaced_paragraphs), ...]``.
        """
        import re
        if not query:
            return []
        flags = 0 if match_case else re.IGNORECASE
        if regex:
            try:
                pat = re.compile(query, flags)
            except re.error as exc:
                raise ValueError(f"Pola regex tidak valid: {exc}") from exc
        else:
            body = re.escape(query)
            if whole_word:
                body = r"\b" + body + r"\b"
            pat = re.compile(body, flags)

        targets = list(pages if pages is not None else range(self.page_count))
        out: list[tuple[int, int]] = []
        for pno in targets:
            if not (0 <= pno < self.page_count):
                continue
            page = self.doc[pno]
            try:
                data = page.get_text("dict")
            except Exception:
                continue
            todo = []
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for group in _paragraphs(block):
                    if not group or not group[0].get("spans"):
                        continue
                    try:
                        info = self._group_info(pno, group)
                    except Exception:
                        continue
                    if not pat.search(info["text"]):
                        continue
                    new_text = pat.sub(lambda _m: replacement, info["text"])
                    if new_text == info["text"]:
                        continue
                    todo.append((info, new_text))
            # bottom-up so a rewritten paragraph never sits on top of a pending one
            count = 0
            for info, new_text in reversed(todo):
                try:
                    ok = self.replace_text(
                        pno, info["rect"], new_text, info["size"], info["font"],
                        info["color"], info["bg"], bold=info["bold"],
                        italic=info["italic"], baseline=info["baseline"],
                        single=info["single"], font_name=info["font_name"],
                        line_gap=info["line_gap"])
                except Exception:
                    ok = False
                if ok:
                    count += 1
            if count:
                out.append((pno, count))
        return out

    # ------------------------------------------------------------- watermark
    def watermark(self, text: str, *, pages=None, size: float = 46,
                  color=(0.85, 0.1, 0.1), opacity: float = 0.18,
                  diagonal: bool = True, tiled: bool = False,
                  bold: bool = True) -> int:
        import math
        if not text.strip():
            return 0
        fontname = "hebo" if bold else "helv"
        font = fitz.Font(fontname)
        angle = 30 if diagonal else 0
        mat = fitz.Matrix(1, 1).prerotate(angle)
        a = math.radians(angle)
        targets = list(pages if pages is not None else range(self.page_count))
        for pno in targets:
            if not (0 <= pno < self.page_count):
                continue
            page = self.doc[pno]
            if tiled:
                step_x = max(120.0, size * max(6, len(text)) * 0.42)
                step_y = max(90.0, size * 2.6)
                y = -step_y / 2
                row = 0
                while y < page.rect.height + step_y:
                    x = -step_x / 2 + (step_x / 2 if row % 2 else 0)
                    while x < page.rect.width + step_x:
                        self._stamp_text(page, text, size, fontname, color,
                                         opacity, (x, y), mat)
                        x += step_x
                    y += step_y
                    row += 1
            else:
                tw = fitz.TextWriter(page.rect)
                tw.append((0, 0), text, fontsize=size, font=font)
                tr = tw.text_rect
                cx, cy = (tr.x0 + tr.x1) / 2, (tr.y0 + tr.y1) / 2
                rx = cx * math.cos(a) + cy * math.sin(a)
                ry = -cx * math.sin(a) + cy * math.cos(a)
                px = page.rect.x0 + page.rect.width / 2 - rx
                py = page.rect.y0 + page.rect.height / 2 - ry
                self._stamp_text(page, text, size, fontname, color, opacity,
                                 (px, py), mat)
        return len(targets)

    def _stamp_text(self, page, text: str, size: float, fontname: str,
                    color, opacity: float, point, mat) -> None:
        """Rotated text that stays real, selectable text."""
        try:
            page.insert_text(tuple(point), text, fontsize=float(size),
                             fontname=fontname, color=tuple(color),
                             fill_opacity=float(opacity),
                             morph=(fitz.Point(*point), mat))
        except TypeError:
            page.insert_text(tuple(point), text, fontsize=float(size),
                             fontname=fontname, color=tuple(color),
                             morph=(fitz.Point(*point), mat))

    # ------------------------------------------------------------ page furniture
    def _furniture(self, text: str, pno: int, fmt: dict, size: float,
                   color, margin: float, font: str, bold: bool,
                   align: str, top: bool) -> None:
        page = self.doc[pno]
        body = text.replace("{page}", str(pno + 1))
        body = body.replace("{total}", str(self.page_count))
        body = body.replace("{date}", datetime.date.today().strftime("%d/%m/%Y"))
        body = body.replace("{title}", (self.metadata.get("title") or "").strip())
        if not body.strip():
            return
        w = fitz.get_text_length(body, fontname=font_code(font, bold, False),
                                 fontsize=size)
        if align == "left":
            x = margin
        elif align == "right":
            x = page.rect.width - margin - w
        else:
            x = (page.rect.width - w) / 2
        y = margin + size if top else page.rect.height - margin
        page.insert_text((x, y), body, fontsize=size,
                         fontname=font_code(font, bold, False), color=tuple(color))

    def page_numbers(self, *, position: str = "bottom-center", start: int = 1,
                     fmt: str = "Halaman {page} dari {total}", size: float = 9,
                     color=(0.25, 0.25, 0.25), margin: float = 26,
                     pages=None, font: str = "Helvetica",
                     bold: bool = False) -> int:
        targets = list(pages if pages is not None else range(self.page_count))
        letter = position.split("-")[0]
        for n, pno in enumerate(targets):
            if not (0 <= pno < self.page_count):
                continue
            body = fmt.replace("{page}", str(start + n)) \
                       .replace("{total}", str(len(targets)))
            page = self.doc[pno]
            w = fitz.get_text_length(body, fontname=font_code(font, bold, False),
                                     fontsize=size)
            x = margin if letter == "left" else (
                page.rect.width - margin - w if letter == "right"
                else (page.rect.width - w) / 2)
            y = (margin + size if position.endswith("top")
                 else page.rect.height - margin)
            page.insert_text((x, y), body, fontsize=size,
                             fontname=font_code(font, bold, False),
                             color=tuple(color))
        return len(targets)

    def header_footer(self, *, header: str = "", footer: str = "",
                      size: float = 9, color=(0.25, 0.25, 0.25),
                      margin: float = 26, pages=None, font: str = "Helvetica",
                      bold: bool = False, align: str = "center") -> int:
        targets = list(pages if pages is not None else range(self.page_count))
        for pno in targets:
            if not (0 <= pno < self.page_count):
                continue
            if header:
                self._furniture(header, pno, {}, size, color, margin, font, bold,
                                align, True)
            if footer:
                self._furniture(footer, pno, {}, size, color, margin, font, bold,
                                align, False)
        return len(targets)

    # ---------------------------------------------------------------- sanitize
    def sanitize(self, *, metadata: bool = True, javascript: bool = True,
                 embedded: bool = True, hidden: bool = True,
                 thumbnails: bool = False, xml: bool = False,
                 links: bool = False, annotations: bool = False,
                 attached: bool = True, attachments: bool | None = None) -> dict:
        if attachments is not None:
            attached = bool(attachments)
        try:
            self.doc.scrub(
                attached_files=attached, clean_pages=True,
                embedded_files=embedded, hidden_text=hidden,
                javascript=javascript, metadata=metadata,
                redactions=annotations, redact_images=0,
                remove_links=links, reset_fields=False, reset_responses=False,
                thumbnails=thumbnails, xml_metadata=xml)
        except TypeError:
            self.doc.scrub(attached_files=attached, embedded_files=embedded,
                           hidden_text=hidden, javascript=javascript,
                           metadata=metadata, redactions=annotations,
                           remove_links=links)
        return {
            "metadata": metadata, "javascript": javascript,
            "embedded": embedded, "hidden": hidden, "links": links,
            "annotations": annotations, "attachments": attached,
        }

    # ----------------------------------------------------------------- outline
    def outline(self) -> list[dict]:
        out = []
        try:
            for level, title, pno in self.doc.get_toc(simple=True):
                out.append({"level": int(level), "title": title or "",
                            "page": max(0, int(pno) - 1)})
        except Exception:
            pass
        return out

    def set_outline(self, entries) -> None:
        toc = []
        for e in entries:
            page = int(e.get("page", 0)) + 1
            page = max(1, min(page, self.page_count))
            toc.append([max(1, int(e.get("level", 1))),
                        (e.get("title") or "Tanpa judul").strip(), page])
        self.doc.set_toc(toc)

    # -------------------------------------------------------------- attachments
    def attachments(self) -> list[dict]:
        out = []
        try:
            for i in range(self.doc.embfile_count()):
                info = self.doc.embfile_info(i) or {}
                out.append({
                    "index": i,
                    "name": info.get("filename") or info.get("name") or f"file{i}",
                    "size": info.get("size") or 0,
                    "desc": info.get("desc") or "",
                    "date": info.get("modDate") or "",
                })
        except Exception:
            pass
        return out

    def add_attachment(self, path: str, desc: str = "") -> None:
        name = os.path.basename(path)
        data = open(path, "rb").read()
        try:
            self.doc.embfile_add(name, data, filename=name, desc=desc or name)
        except TypeError:
            self.doc.embfile_add(name, data)

    def extract_attachment(self, name: str, out_path: str) -> None:
        data = self.doc.embfile_get(name)
        with open(out_path, "wb") as f:
            f.write(data)

    def delete_attachment(self, name: str) -> bool:
        try:
            self.doc.embfile_del(name)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ compare
    def compare_text(self, other_path: str) -> dict:
        import difflib
        other = fitz.open(other_path)
        if other.needs_pass:
            other.close()
            raise PermissionError("PDF pembanding terkunci password.")
        a_pages = self.page_count
        b_pages = other.page_count
        diffs = []
        total_add = total_del = 0
        for pno in range(max(a_pages, b_pages)):
            ta = self.text(pno) if pno < a_pages else ""
            tb = other[pno].get_text("text") if pno < b_pages else ""
            if ta == tb:
                continue
            al = [ln.strip() for ln in ta.splitlines() if ln.strip()]
            bl = [ln.strip() for ln in tb.splitlines() if ln.strip()]
            sm = difflib.SequenceMatcher(None, al, bl)
            rows = []
            add = dele = 0
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "equal":
                    continue
                if tag in ("replace", "delete"):
                    for ln in al[i1:i2]:
                        rows.append({"op": "del", "text": ln})
                        dele += 1
                if tag in ("replace", "insert"):
                    for ln in bl[j1:j2]:
                        rows.append({"op": "add", "text": ln})
                        add += 1
            if rows:
                diffs.append({"page": pno, "rows": rows,
                              "added": add, "removed": dele})
                total_add += add
                total_del += dele
        other.close()
        return {"pages": diffs, "added": total_add, "removed": total_del,
                "same_pages": a_pages == b_pages}

    # ------------------------------------------------------------- page import
    def insert_pages_from(self, path: str, pages, at: int) -> int:
        src = fitz.open(path)
        if src.needs_pass:
            src.close()
            raise PermissionError("PDF sumber terkunci password.")
        idx = sorted(set(p for p in pages if 0 <= p < src.page_count))
        if not idx:
            src.close()
            raise ValueError("Tidak ada halaman yang dipilih.")
        at = max(0, min(int(at), self.page_count))
        for n, p in enumerate(idx):
            self.doc.insert_pdf(src, from_page=p, to_page=p, start_at=at + n)
        src.close()
        return len(idx)

    def duplicate_page(self, pno: int) -> None:
        self.doc.copy_page(pno, pno + 1)

    # ------------------------------------------------------------------- links
    def links(self, pno: int) -> list[dict]:
        out = []
        try:
            for l in self.doc[pno].get_links() or []:
                out.append({
                    "kind": l.get("kind"),
                    "uri": l.get("uri") or "",
                    "page": l.get("page", -1),
                    "rect": tuple(l.get("from")) if l.get("from") else None,
                })
        except Exception:
            pass
        return out

    def _keep_encryption_kwargs(self) -> dict:
        """Preserve encryption safely (PyMuPDF PDF_ENCRYPT_KEEP + garbage corrupts AES-256)."""
        if self.doc is not None and self.password and self.info()["encrypted"]:
            return {
                "encryption": fitz.PDF_ENCRYPT_AES_256,
                "user_pw": self.password,
                "owner_pw": self.password,
                "permissions": int(self.doc.permissions),
            }
        return {"encryption": fitz.PDF_ENCRYPT_KEEP}

    # ------------------------------------------------------------------- save
    def save_as(self, out_path: str, *, compress: bool = False,
                encryption: int | None = None, owner_pw: str = "",
                user_pw: str = "", permissions: int = -1) -> None:
        doc = self.require()
        out_path = os.path.abspath(out_path)
        same = self.path and os.path.abspath(self.path) == out_path
        target = out_path
        tmp = None
        if same:
            out_dir = os.path.dirname(out_path) or self.tmpdir
            try:
                fd, tmp = tempfile.mkstemp(prefix=".pdfstudio_", suffix=".pdf", dir=out_dir)
            except OSError:
                fd, tmp = tempfile.mkstemp(prefix=".pdfstudio_", suffix=".pdf", dir=self.tmpdir)
            os.close(fd)
            target = tmp
        kwargs = {}
        if encryption is not None:
            kwargs.update(encryption=encryption, owner_pw=owner_pw or "pdfstudio",
                          user_pw=user_pw, permissions=permissions)
        else:
            kwargs.update(self._keep_encryption_kwargs())
        if compress:
            kwargs.update(garbage=4, deflate=True, deflate_images=True,
                          deflate_fonts=True, clean=True)
        else:
            kwargs.update(garbage=3, deflate=True)
        try:
            try:
                doc.save(target, **kwargs)
            except Exception:
                # very old / weird docs: retry with minimal args
                kwargs.pop("encryption", None)
                doc.save(target, **kwargs)
            if tmp:
                doc.close()
                try:
                    os.replace(tmp, out_path)
                except OSError:
                    shutil.move(tmp, out_path)
                tmp = None
                self._reopen(out_path)
            else:
                self._reopen(out_path)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def snapshot_to(self, path: str) -> None:
        """Write the current state to *path* without touching the open doc."""
        doc = self.require()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        try:
            doc.save(tmp, garbage=3, deflate=True, **self._keep_encryption_kwargs())
        except Exception:
            doc.save(tmp, garbage=3, deflate=True)
        os.replace(tmp, path)

    def _reopen(self, path: str) -> None:
        pw = self.password
        keep_undo, keep_redo = self._undo, self._redo
        doc = fitz.open(path)
        if doc.needs_pass and pw:
            doc.authenticate(pw)
        self.doc = doc
        self.path = os.path.abspath(path)
        self._undo, self._redo = keep_undo, keep_redo

    def protect(self, out_path: str, user_pw: str, owner_pw: str = "",
                allow_print: bool = True, allow_copy: bool = True,
                allow_modify: bool = False) -> None:
        if self.path and os.path.abspath(out_path) == os.path.abspath(self.path):
            raise ValueError("Simpan ke nama file lain agar dokumen asli tetap aman.")
        perms = 0
        if allow_print:
            perms |= fitz.PDF_PERM_PRINT
        if allow_copy:
            perms |= fitz.PDF_PERM_COPY
        if allow_modify:
            perms |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ANNOTATE
        self.doc.save(out_path, encryption=fitz.PDF_ENCRYPT_AES_256,
                      owner_pw=owner_pw or user_pw or "pdfstudio",
                      user_pw=user_pw, permissions=perms,
                      garbage=3, deflate=True)

    def compress_to(self, out_path: str) -> None:
        if self.path and os.path.abspath(out_path) == os.path.abspath(self.path):
            raise ValueError("Pilih nama file baru untuk versi terkompresi.")
        try:
            self.doc.save(out_path, garbage=4, deflate=True, deflate_images=True,
                          deflate_fonts=True, clean=True,
                          **self._keep_encryption_kwargs())
        except Exception:
            self.doc.save(out_path, garbage=4, deflate=True, deflate_images=True,
                          deflate_fonts=True, clean=True)

    def set_metadata(self, meta: dict) -> None:
        self.doc.set_metadata(meta)

    @property
    def metadata(self) -> dict:
        return dict(self.doc.metadata or {}) if self.doc else {}

    def _next_signature_field_name(self) -> str:
        existing: set[str] = set()
        if self.doc is not None:
            for page in self.doc:
                for w in page.widgets() or []:
                    if w.field_name:
                        existing.add(w.field_name)
        idx = 1
        while f"Signature{idx}" in existing:
            idx += 1
        return f"Signature{idx}"

    def has_signatures(self) -> bool:
        if self.doc is None:
            return False
        for page in self.doc:
            for w in page.widgets() or []:
                if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    return True
        return False

    def verify_signatures(self) -> list[dict]:
        """Inspect embedded digital signatures and check document integrity."""
        if self.doc is None or not self.has_signatures():
            return []
        import logging
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext

        src_path = self.path
        tmp = None
        if not src_path or not os.path.exists(src_path):
            tmp = self.temp_pdf()
            src_path = tmp
        results: list[dict] = []
        loggers = [logging.getLogger("pyhanko"), logging.getLogger("pyhanko_certvalidator")]
        prev_levels = [lg.level for lg in loggers]
        for lg in loggers:
            lg.setLevel(logging.CRITICAL)
        try:
            with open(src_path, "rb") as fh:
                reader = PdfFileReader(fh, strict=False)
                if self.password and reader.security_handler:
                    try:
                        reader.decrypt(self.password)
                    except Exception:
                        pass
                for sig in reader.embedded_signatures:
                    entry = {
                        "field_name": sig.field_name or "Signature",
                        "signer": "",
                        "issuer": "",
                        "reason": str(sig.sig_object.get("/Reason", "") or ""),
                        "location": str(sig.sig_object.get("/Location", "") or ""),
                        "signing_time": "",
                        "intact": False,
                        "valid": False,
                        "trusted": False,
                        "summary": "",
                    }
                    try:
                        cert = sig.signer_cert
                        if cert is not None:
                            entry["signer"] = cert.subject.human_friendly
                            entry["issuer"] = cert.issuer.human_friendly
                    except Exception:
                        pass
                    try:
                        vc = ValidationContext(allow_fetching=False)
                        status = validate_pdf_signature(sig, signer_validation_context=vc)
                        entry["intact"] = bool(getattr(status, "intact", False))
                        entry["valid"] = bool(getattr(status, "valid", False))
                        entry["trusted"] = bool(getattr(status, "trusted", False))
                        st = getattr(status, "signer_reported_dt", None)
                        if st is not None:
                            entry["signing_time"] = st.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
                    except Exception as exc:
                        entry["summary"] = str(exc)
                    if not entry["summary"]:
                        if entry["intact"] and entry["valid"] and entry["trusted"]:
                            entry["summary"] = "Valid & terpercaya — dokumen utuh."
                        elif entry["intact"] and entry["valid"]:
                            entry["summary"] = "Integritas valid (sertifikat self-signed / penerbit tidak dikenal)."
                        elif entry["intact"]:
                            entry["summary"] = "Dokumen utuh, tetapi tanda tangan tidak dapat divalidasi."
                        else:
                            entry["summary"] = "Peringatan: dokumen telah diubah setelah ditandatangani atau tanda tangan rusak."
                    results.append(entry)
        except Exception:
            return results
        finally:
            for lg, lvl in zip(loggers, prev_levels):
                lg.setLevel(lvl)
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return results

    def digital_sign(self, out_path: str, pno: int, rect, pfx_path: str,
                     passphrase: str, reason: str = "Digitally signed",
                     location: str = "") -> None:
        from pyhanko.sign import signers, fields
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign.fields import SigSeedSubFilter

        w_page, h_page = self.page_size(pno)
        r = _rect(*rect)
        box = (r.x0, h_page - r.y1, r.x1, h_page - r.y0)
        field_name = self._next_signature_field_name()
        # Preserve original bytes when adding incremental signatures to an already-signed PDF.
        use_original = bool(
            self.path and os.path.exists(self.path)
            and os.path.abspath(self.path) != os.path.abspath(out_path)
            and self.has_signatures() and not self._undo
        )
        tmp = None if use_original else self.temp_pdf()
        src_path = self.path if use_original else tmp
        try:
            with open(src_path, "rb") as inf:
                writer = IncrementalPdfFileWriter(inf, strict=False)
                fields.append_signature_field(
                    writer,
                    fields.SigFieldSpec(sig_field_name=field_name, on_page=pno, box=box),
                )
                signer = signers.SimpleSigner.load_pkcs12(
                    pfx_file=pfx_path,
                    passphrase=passphrase.encode("utf-8") if passphrase else None,
                )
                meta = signers.PdfSignatureMetadata(
                    field_name=field_name, reason=reason, location=location or None,
                    subfilter=SigSeedSubFilter.PADES,
                )
                pdf_signer = signers.PdfSigner(meta, signer=signer)
                with open(out_path, "wb") as outf:
                    pdf_signer.sign_pdf(writer, output=outf)
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def temp_pdf(self) -> str:
        fd, p = tempfile.mkstemp(suffix=".pdf", dir=self.tmpdir)
        os.close(fd)
        self.doc.save(p, garbage=0, deflate=False)
        return p

    # ------------------------------------------------------------------- undo
    def _clear_hist(self):
        for p, _i, _l in self._undo + self._redo:
            try:
                os.unlink(p)
            except Exception:
                pass
        self._undo, self._redo = [], []

    def snapshot(self, label: str = "Edit", page: int = 0) -> None:
        if self.doc is None or self._restoring:
            return
        try:
            p = self.temp_pdf()
        except Exception:
            return
        self._undo.append((p, page, label))
        self._redo.clear()
        while len(self._undo) > 20:
            old, _i, _l = self._undo.pop(0)
            try:
                os.unlink(old)
            except Exception:
                pass

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _load_from(self, path: str, page_hint: int) -> int:
        self._restoring = True
        try:
            doc = fitz.open(path)
            if doc.needs_pass and self.password:
                doc.authenticate(self.password)
            old = self.doc
            self.doc = doc
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            return min(max(0, page_hint), self.page_count - 1)
        finally:
            self._restoring = False

    def undo(self) -> tuple[str, int] | None:
        if not self._undo:
            return None
        path, page, label = self._undo.pop()
        try:
            cur = self.temp_pdf()
            self._redo.append((cur, page, label))
        except Exception:
            pass
        page = self._load_from(path, page)
        try:
            os.unlink(path)
        except Exception:
            pass
        return label, page

    def redo(self) -> tuple[str, int] | None:
        if not self._redo:
            return None
        path, page, label = self._redo.pop()
        try:
            cur = self.temp_pdf()
            self._undo.append((cur, page, label))
        except Exception:
            pass
        page = self._load_from(path, page)
        try:
            os.unlink(path)
        except Exception:
            pass
        return label, page

    # ------------------------------------------------------------------- misc
    def layers(self) -> list[dict]:
        """Return Optional Content Groups (OCG layers) with their visibility."""
        if not self.doc:
            return []
        try:
            ocgs = self.doc.get_ocgs() or {}
        except Exception:
            return []
        out = []
        overrides = getattr(self, "_layer_overrides", {})
        for xref, info in ocgs.items():
            ix = int(xref)
            out.append({
                "xref": ix,
                "name": (info.get("name") or f"Layer {xref}").strip(),
                "on": overrides[ix] if ix in overrides else bool(info.get("on", True)),
            })
        return out

    def set_layer_visible(self, xref: int, on: bool) -> bool:
        """Toggle visibility of an OCG layer and re-apply OCG state."""
        if not self.doc:
            return False
        try:
            ocgs = self.doc.get_ocgs() or {}
            if xref not in ocgs:
                return False
            if not hasattr(self, "_layer_overrides"):
                self._layer_overrides = {}
            self._layer_overrides[int(xref)] = bool(on)
            target_name = (ocgs[xref].get("name") or "").strip()
            ui_cfgs = self.doc.layer_ui_configs() or []
            matched = False
            for cfg in ui_cfgs:
                if (cfg.get("text") or "").strip() == target_name:
                    self.doc.set_layer_ui_config(int(cfg["number"]), 0 if on else 2)
                    matched = True
                    break
            if not matched and ui_cfgs:
                idx = list(ocgs.keys()).index(xref)
                if idx < len(ui_cfgs):
                    self.doc.set_layer_ui_config(int(ui_cfgs[idx]["number"]), 0 if on else 2)
                    matched = True
            if not matched:
                on_list = [int(x) for x in ocgs if self._layer_overrides.get(int(x), bool(ocgs[x].get("on", True)))]
                off_list = [int(x) for x in ocgs if int(x) not in on_list]
                self.doc.set_layer(-1, basestate="ON" if on_list else "OFF",
                                   on=on_list or None, off=off_list or None)
            return True
        except Exception:
            return False

    def all_fonts(self) -> list[dict]:
        """List unique fonts used across the document."""
        if not self.doc:
            return []
        seen: set[tuple[str, str, str]] = set()
        out = []
        for pno in range(self.page_count):
            try:
                for f in self.doc[pno].get_fonts(full=True) or []:
                    # (xref, ext, type, basefont, name, encoding, referencer)
                    ext = str(f[1] or "")
                    ftype = str(f[2] or "")
                    base = str(f[3] or f[4] or "Unknown")
                    key = (base, ftype, ext)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "name": base,
                        "type": ftype,
                        "ext": ext,
                        "embedded": bool(ext and ext != "n/a"),
                    })
            except Exception:
                continue
        return out

    def all_widgets(self) -> list[dict]:
        """List all form fields across all pages."""
        if not self.doc:
            return []
        out = []
        for pno in range(self.page_count):
            for w in self.widgets(pno):
                item = dict(w)
                item["page"] = pno
                out.append(item)
        return out

    def document_details(self) -> dict:
        """Detailed document properties for the multi-tab Properties dialog."""
        meta = self.metadata
        info = self.info()
        perms = int(getattr(self.doc, "permissions", -1) or -1) if self.doc else -1
        return {
            **info,
            "metadata": meta,
            "version": meta.get("format") or "PDF",
            "creator": meta.get("creator") or "",
            "producer": meta.get("producer") or "",
            "encryption": meta.get("encryption") or ("Terenkripsi" if info["encrypted"] else "Tidak ada"),
            "can_print": bool(perms & fitz.PDF_PERM_PRINT) if perms >= 0 else True,
            "can_copy": bool(perms & fitz.PDF_PERM_COPY) if perms >= 0 else True,
            "can_modify": bool(perms & fitz.PDF_PERM_MODIFY) if perms >= 0 else True,
            "can_annotate": bool(perms & fitz.PDF_PERM_ANNOTATE) if perms >= 0 else True,
            "fonts": self.all_fonts(),
            "layers_count": len(self.layers()),
            "fields_count": len(self.all_widgets()),
            "attachments_count": len(self.attachments()) if hasattr(self, "attachments") else 0,
        }

    def info(self) -> dict:
        meta = self.metadata
        size = self.page_size(0) if self.page_count else (0, 0)
        return {
            "path": self.path or "",
            "pages": self.page_count,
            "size": size,
            "title": meta.get("title") or "",
            "author": meta.get("author") or "",
            "subject": meta.get("subject") or "",
            "keywords": meta.get("keywords") or "",
            "encrypted": bool(self.doc.is_encrypted or self.doc.needs_pass or meta.get("encryption")) if self.doc else False,
            "filesize": os.path.getsize(self.path) if self.path and os.path.exists(self.path) else 0,
        }


def strip_password(src: str, out_path: str, password: str = "") -> None:
    """Write an unencrypted copy of a PDF (requires the correct password)."""
    d = fitz.open(src)
    try:
        if d.needs_pass and not d.authenticate(password):
            raise PermissionError("Password salah.")
        d.save(out_path, encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
    finally:
        d.close()


def make_self_signed_pfx(out_path: str, name: str, password: str,
                          valid_days: int = 365) -> None:
    """Create a self-signed signing certificate (for testing PAdES signatures)."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    import datetime as _dt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, name or "PDF Studio User"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PDF Studio Self-Signed"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "ID"),
    ])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - _dt.timedelta(minutes=5))
            .not_valid_after(now + _dt.timedelta(days=valid_days))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    blob = pkcs12.serialize_key_and_certificates(
        name=(name or "PDF Studio").encode(), key=key, cert=cert, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()) if password
        else serialization.NoEncryption())
    with open(out_path, "wb") as f:
        f.write(blob)


def create_pdf_from_images(image_paths: list[str], out_path: str) -> int:
    """Combine one or more image files into a multi-page PDF."""
    if not image_paths:
        raise ValueError("Tidak ada file gambar yang dipilih.")
    out = fitz.open()
    added = 0
    try:
        for img_path in image_paths:
            if not os.path.exists(img_path):
                continue
            with fitz.open(img_path) as img_doc:
                pdf_bytes = img_doc.convert_to_pdf()
            with fitz.open("pdf", pdf_bytes) as page_pdf:
                out.insert_pdf(page_pdf)
                added += page_pdf.page_count
        if not added:
            raise ValueError("Tidak ada gambar valid yang bisa dikonversi.")
        out.save(out_path, garbage=3, deflate=True)
        return added
    finally:
        out.close()

