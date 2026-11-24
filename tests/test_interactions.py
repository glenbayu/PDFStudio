"""Interaction + dialog tests using real Qt event delivery."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "PDFSTUDIO_RECOVERY_DIR" not in os.environ:
    os.environ["PDFSTUDIO_RECOVERY_DIR"] = tempfile.mkdtemp(prefix="pdfrec_int_")
if os.name == "nt" and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    os.environ.setdefault(
        "QT_QPA_FONTDIR",
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from sample.make_demo import build
from ui.main_window import MainWindow
from ui.dialogs import (AboutDialog, DigitalSignDialog, FormFieldDialog,
                        MetadataDialog, NoteDialog, PageRangeDialog,
                        PasswordPrompt, ProtectDialog, RecoveryDialog,
                        SignatureDialog, TextDialog, TextPrompt)


def main():
    tmp = tempfile.mkdtemp(prefix="pdfint_")
    demo = os.path.join(tmp, "demo.pdf")
    build(demo)

    app = QApplication([])
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    win.open_file(demo)
    win.fit_page()
    app.processEvents()

    v = win.view
    z = v.zoom

    def pt(x, y):
        box = v._page_box(0)
        return QPoint(int(x * v.zoom + box["x"]) + 1,
                      int(y * v.zoom + box["y"]) + 1)

    # --- drag highlight with real mouse events
    n_before = len(list(win.doc.page(0).annots() or []))
    win._set_tool("highlight")
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(55, 170))
    QTest.mouseMove(v, pt(250, 175))
    QTest.mouseMove(v, pt(410, 183))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(410, 183))
    app.processEvents()
    n_after = len(list(win.doc.page(0).annots() or []))
    assert n_after > n_before, (n_before, n_after)
    print("[ok] mouse drag created highlight annotations:", n_after - n_before)

    # --- select text + copy
    win._set_tool("select")
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(55, 166))
    QTest.mouseMove(v, pt(300, 170))
    QTest.mouseMove(v, pt(500, 186))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(500, 186))
    app.processEvents()
    sel = v.selection_text()
    assert sel.strip(), "selection kosong"
    win.copy_selection()
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == sel
    print("[ok] text selection + clipboard:", repr(sel[:40]))

    # --- inline text edit: click on the page, type, Enter
    win._set_tool("edit_text")
    words = win.doc.words(0)
    target = max(words, key=lambda w: len(w[4]))
    cx = (target[0] + target[2]) / 2
    cy = (target[1] + target[3]) / 2
    assert win.doc.text_at(0, (cx, cy)), "no text under click"
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(cx, cy))
    app.processEvents()
    assert v.inline_active(), "inline editor tidak terbuka"
    ed = v._editor
    assert ed.toPlainText().strip()
    ed.selectAll()
    QTest.keyClicks(ed, "Teks Baru")
    QTest.keyClick(ed, Qt.Key_Return)
    app.processEvents()
    assert not v.inline_active(), "editor masih terbuka setelah Enter"
    assert "Teks Baru" in win.doc.page(0).get_text(), "teks tidak berubah"
    print("[ok] inline edit: klik -> ketik -> Enter")

    # --- Esc cancels without touching the document
    new_words = [w for w in win.doc.words(0) if w[4] in ("Teks", "Baru")]
    assert new_words
    nx = (new_words[0][0] + new_words[-1][2]) / 2
    ny = (new_words[0][1] + new_words[-1][3]) / 2
    before = win.doc.page(0).get_text()
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(nx, ny))
    app.processEvents()
    assert v.inline_active()
    v._editor.selectAll()
    QTest.keyClicks(v._editor, "JANGAN DISIMPAN")
    QTest.keyClick(v._editor, Qt.Key_Escape)
    app.processEvents()
    assert not v.inline_active()
    assert win.doc.page(0).get_text() == before
    print("[ok] inline edit: Esc membatalkan")

    # --- Shift+Enter keeps a newline inside the paragraph
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(nx, ny))
    app.processEvents()
    assert v.inline_active()
    ed = v._editor
    ed.selectAll()
    QTest.keyClicks(ed, "Baris satu")
    QTest.keyClick(ed, Qt.Key_Return, Qt.ShiftModifier)
    QTest.keyClicks(ed, "Baris dua")
    QTest.keyClick(ed, Qt.Key_Return)
    app.processEvents()
    got = win.doc.page(0).get_text()
    assert "Baris satu" in got and "Baris dua" in got
    print("[ok] inline edit: Shift+Enter baris baru")

    # --- dragging inside the same paragraph opens the inline editor too
    hits = win.doc.page(0).search_for("Baris satu")
    assert hits, "teks hasil edit tidak ditemukan"
    hr = hits[0]
    QTest.qWait(400)  # stay clear of Qt's double-click detection
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier,
                    pt(hr.x0 + 1, (hr.y0 + hr.y1) / 2))
    QTest.mouseMove(v, pt(hr.x1 - 1, (hr.y0 + hr.y1) / 2))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier,
                       pt(hr.x1 - 1, (hr.y0 + hr.y1) / 2))
    app.processEvents()
    assert v.inline_active(), "drag dalam paragraf harus buka editor inline"
    QTest.keyClick(v._editor, Qt.Key_Escape)
    app.processEvents()
    print("[ok] inline edit: drag dalam paragraf")

    # --- ink gesture
    n_before = len(list(win.doc.page(0).annots() or []))
    win._set_tool("ink")
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(300, 330))
    for x in range(310, 380, 10):
        QTest.mouseMove(v, pt(x, 330 + (x % 20)))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(380, 340))
    app.processEvents()
    assert len(list(win.doc.page(0).annots() or [])) == n_before + 1
    print("[ok] freehand ink annotation")

    # --- shape
    win._set_tool("rect")
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(330, 120))
    QTest.mouseMove(v, pt(420, 175))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(420, 175))
    app.processEvents()
    print("[ok] rectangle annotation")

    # --- undo through controller
    win.undo()
    app.processEvents()
    print("[ok] undo after gestures")

    # --- line / arrow gesture
    before = len(win.doc.annotations(0))
    win._set_tool("arrow")
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(60, 260))
    QTest.mouseMove(v, pt(150, 285))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(200, 300))
    app.processEvents()
    ann = win.doc.annotations(0)
    assert len(ann) == before + 1, (before, len(ann))
    assert ann[-1]["kind"] == "arrow", ann[-1]["kind"]
    print("[ok] arrow gesture")

    # --- callout (text prompt is stubbed)
    from ui.dialogs import TextPrompt as _TextPrompt
    _old_prompt = _TextPrompt.get
    _TextPrompt.get = staticmethod(lambda *a, **k: ("Catatan callout uji", True))
    try:
        win._set_tool("callout")
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(260, 300))
        QTest.mouseMove(v, pt(360, 340))
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(380, 350))
        app.processEvents()
    finally:
        _TextPrompt.get = _old_prompt
    callouts = [a for a in win.doc.annotations(0)
                if "Catatan callout" in (a.get("content") or "")]
    assert callouts, "callout tidak dibuat"
    print("[ok] callout annotation")

    # --- stamp (dialog values preloaded)
    win._stamp_values = {"text": "LULUS", "fontsize": 18,
                         "color": (0.1, 0.5, 0.2)}
    win._set_tool("stamp")
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(430, 470))
    app.processEvents()
    assert any((a.get("content") or "") == "LULUS"
               for a in win.doc.annotations(0)), "stempel tidak dibuat"
    print("[ok] stamp annotation")

    # --- select, move, resize and delete an annotation
    win._set_tool("rect")
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(120, 480))
    QTest.mouseMove(v, pt(200, 520))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(220, 540))
    app.processEvents()
    rect_annot = win.doc.annotations(0)[-1]
    xref = rect_annot["xref"]
    win._set_tool("select")
    v.setFocus()
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, pt(170, 510))
    app.processEvents()
    picked = v.selected_annot()
    assert picked and picked["xref"] == xref, picked
    assert win.annot_label.text().startswith(("rect", "Kotak", "arrow", "freetext")) or \
        "halaman" in win.annot_label.text()
    print("[ok] annotation select + inspector label")

    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(170, 510))
    QTest.mouseMove(v, pt(190, 525))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(205, 535))
    app.processEvents()
    moved = next(a for a in win.doc.annotations(0) if a["xref"] == xref)
    assert moved["rect"][0] > rect_annot["rect"][0] + 10, (rect_annot["rect"], moved["rect"])
    print("[ok] annotation drag move")

    r = moved["rect"]
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier,
                     pt((r[0] + r[2]) / 2, (r[1] + r[3]) / 2))
    app.processEvents()
    assert v.selected_annot() is not None
    QTest.qWait(400)  # stay clear of Qt's double-click detection
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pt(r[2], r[3]))
    QTest.mouseMove(v, pt(r[2] + 30, r[3] + 18))
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pt(r[2] + 30, r[3] + 18))
    app.processEvents()
    bigger = next(a for a in win.doc.annotations(0) if a["xref"] == xref)
    assert bigger["rect"][2] > r[2] + 20, (r, bigger["rect"])
    print("[ok] annotation resize via handle")

    win._refresh_comments()
    total = sum(len(win.doc.annotations(p)) for p in range(win.doc.page_count))
    assert win.comment_list.count() == total, (win.comment_list.count(), total)

    QTest.keyClick(v, Qt.Key_Delete)
    app.processEvents()
    assert all(a["xref"] != xref for a in win.doc.annotations(0)), "anotasi belum terhapus"
    print("[ok] delete annotation via Delete key + comments panel")

    # --- read mode
    win.toggle_read_mode(True)
    app.processEvents()
    assert v.read_mode and not win.tool_rail.isVisible()
    assert not win.dock_props.isVisible() and not win.menuBar().isVisible()
    win.toggle_read_mode(False)
    app.processEvents()
    assert not v.read_mode and win.menuBar().isVisible()
    print("[ok] read mode hides chrome")

    # --- themes
    win.set_theme("light")
    assert "#f7f8fa" in win.styleSheet()
    win.set_theme("dark")
    assert "#1b1c1f" in win.styleSheet()
    print("[ok] dark/light theme switch")

    # --- command palette
    from ui.palette import CommandPalette
    pal = CommandPalette(win, [
        {"title": "Simpan dokumen", "shortcut": "Ctrl+S", "run": None},
        {"title": "Watermark halaman", "shortcut": "", "run": None},
    ])
    pal._filter("simpan")
    assert pal.list.count() == 1, pal.list.count()
    pal._filter("")
    assert pal.list.count() == 2
    pal.close()
    print("[ok] command palette filter")

    # --- dialogs instantiate & values
    d = TextDialog(win, "Tambah Teks", "Halo", 14, "Times", "#ff0000", bold=True)
    vals = d.values()
    assert vals["text"] == "Halo" and vals["font"] == "Times" and vals["bold"]
    d.close()

    d = NoteDialog(win, "tes")
    assert d.values()["text"] == "tes"
    d.close()

    d = ProtectDialog(win)
    d.user_pw.setText("abcdef")
    d.user_pw2.setText("abcdef")
    assert d.values()["user_pw"] == "abcdef"
    d.close()

    d = MetadataDialog(win, win.doc.metadata)
    assert d.values()["title"] == "PDF Studio Demo"
    d.close()

    d = PageRangeDialog(win, win.doc.page_count)
    d.edit.setText("1,3")
    assert d.pages(win.doc.page_count) == [0, 2]
    d.close()

    d = FormFieldDialog(win, {"label": "Nama", "type": "Text", "value": "x"})
    assert d.value() == "x"
    d.close()

    d = DigitalSignDialog(win)
    d.pfx.setText("dummy.pfx")
    assert d.values()["pfx"] == "dummy.pfx"
    d.close()

    d = PasswordPrompt(win, "x.pdf")
    assert d.pw.text() == ""
    d.close()

    d = SignatureDialog(win)
    d.pad.strokes = [[__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(10, 10),
                      __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(80, 40)]]
    img = d.result_image()
    assert not img.isNull() and img.width() > 50
    d.close()
    print("[ok] all dialogs construct, values(), signature image")

    d = AboutDialog(win)
    d.close()
    d = RecoveryDialog(win, [{"name": "x.pdf", "page": 0, "saved_at": 0,
                              "original": "x.pdf", "snapshot": "x.pdf"}])
    assert d.list.count() == 1
    assert d.selected_entries()[0]["page"] == 0
    d.close()
    print("[ok] dialog suite")

    # --- v1.1 dialogs
    from ui.tools_dialogs import (AnnotPropsDialog, AttachmentsDialog, BatchDialog,
                                  CompareDialog, HeaderFooterDialog,
                                  InsertPagesDialog, PageNumberDialog,
                                  SearchReplaceDialog, ShortcutsDialog,
                                  StampDialog, WatermarkDialog, parse_pages)
    assert parse_pages("1-2,4", 5) == [0, 1, 3]
    assert parse_pages("9", 3) == []

    d = WatermarkDialog(win, 3)
    assert d.values()["pages"] == [0, 1, 2]
    d.close()

    d = PageNumberDialog(win, 3)
    assert d.values()["position"] == "bottom-center"
    d.close()

    d = HeaderFooterDialog(win, 3)
    assert d.values()["footer"] == "{page} / {total}"
    d.close()

    d = StampDialog(win)
    assert d.values()["text"]
    d.close()

    d = AnnotPropsDialog(win, {"kind": "rect", "rect": (10, 10, 60, 40),
                               "width": 2, "opacity": 0.5, "stroke": (1, 0, 0)})
    assert d.values()["rect"][2] > 10 and d.values()["opacity"] == 0.5
    d.close()

    d = CompareDialog(win, {"pages": [{"page": 0, "added": 1, "removed": 0,
                                       "rows": [{"op": "add", "text": "baru"}]}],
                            "added": 1, "removed": 0}, "a.pdf", "b.pdf")
    assert d.tree.topLevelItemCount() == 1
    d.close()

    d = BatchDialog(win, tmp)
    assert d.values()["out"]
    d.close()

    d = AttachmentsDialog(win, win.doc)
    d.close()

    d = InsertPagesDialog(win, tmp, 3)
    assert d.values()["at"] == 3
    d.close()

    d = SearchReplaceDialog(win, win.doc, 0)
    d.find_edit.setText("Coba")
    d.run_search()
    assert d.results.count() >= 1
    d.close()

    d = ShortcutsDialog(win)
    d.close()
    print("[ok] v1.1 dialog suite")

    # --- page ops via controller
    win.go_page(2)
    assert win.pno == 2
    win.rotate_page(90)
    assert win.doc.page(2).rotation == 90
    win.insert_page()
    assert win.doc.page_count == 4
    print("[ok] page ops")

    win.dirty = False
    win.doc.close()
    win.close()


if __name__ == "__main__":
    main()
