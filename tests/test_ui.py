"""Offscreen UI smoke test: builds the window, exercises tools, grabs a screenshot."""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep autosave snapshots out of the real profile while testing.
if "PDFSTUDIO_RECOVERY_DIR" not in os.environ:
    os.environ["PDFSTUDIO_RECOVERY_DIR"] = tempfile.mkdtemp(prefix="pdfrec_ui_")
# The offscreen plugin needs a font dir on Windows, otherwise every glyph is a box.
if os.name == "nt" and "QT_QPA_FONTDIR" not in os.environ:
    os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from sample.make_demo import build
from ui.main_window import MainWindow

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shot.png")


def main():
    tmp = tempfile.mkdtemp(prefix="pdfui_")
    demo = os.path.join(tmp, "demo.pdf")
    build(demo)

    app = QApplication([])
    win = MainWindow()
    win.resize(1500, 940)
    win.show()
    app.processEvents()

    win.open_file(demo)
    app.processEvents()
    assert win.doc.page_count == 3
    assert win.view.doc is not None
    print("[ok] window + document loaded")

    # render check
    img = win.view.page_pixmap()
    assert img is not None and img.width() > 400, img
    print("[ok] page rendered", img.width(), "x", img.height())

    # tools + gestures
    win._set_tool("highlight")
    win._on_view_action("gesture", {"tool": "highlight", "rect": (55, 165, 420, 183)})
    win._set_tool("ink")
    win._on_view_action("ink", {"strokes": [[(300, 340), (350, 355), (400, 330)]]})
    win._set_tool("rect")
    win._on_view_action("gesture", {"tool": "rect", "rect": (320, 120, 420, 170)})
    print("[ok] highlight, ink, rectangle")

    # note + text need dialogs -> direct engine calls through mutation helper
    win._mutate("note", lambda: win.doc.add_note(win.pno, (430, 200), "Catatan uji", (1, 0.8, 0.2)))
    win._mutate("text", lambda: win.doc.add_text(
        win.pno, (60, 540, 400, 570), "Teks tambahan dari UI test", 15,
        "Helvetica", (0.1, 0.2, 0.7), bold=True))
    print("[ok] note + text via controller")

    # form fill
    win._mutate("form", lambda: win.doc.set_widget(0, "nama", "Glend"))
    win._mutate("form", lambda: win.doc.set_widget(0, "setuju", True))

    # search
    win.search_edit.setText("halaman")
    win.run_search()
    assert win._search_hits, "search found nothing"
    assert [h[0] for h in win.view._search_hits] == [h[0] for h in win._search_hits]
    print("[ok] search hits:", len(win._search_hits))
    win._search_step(1)

    # page navigation / rotation
    win.go_page(1)
    assert win.pno == 1
    win.rotate_page(90)
    win.go_page(0)
    print("[ok] page nav + rotate")

    # continuous scroll: wheel scrolls the page strip, active page follows
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    win.fit_page()
    app.processEvents()
    view = win.view
    assert len(view._layout) == win.doc.page_count, len(view._layout)

    def wheel(dy):
        ev = QWheelEvent(QPointF(view.rect().center()),
                         QPointF(view.mapToGlobal(view.rect().center())),
                         QPoint(0, 0), QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(view, ev)
        app.processEvents()

    bar = win.scroll.verticalScrollBar()
    assert bar.maximum() > 0, "strip should be scrollable"
    assert bar.value() == 0
    wheel(-120)
    assert bar.value() > 0, "wheel must scroll the strip"
    for _ in range(30):
        wheel(-120)
    assert bar.value() == bar.maximum()
    assert win.pno == win.doc.page_count - 1, win.pno
    for _ in range(30):
        wheel(120)
    assert bar.value() == 0
    assert win.pno == 0, win.pno
    print("[ok] continuous scroll + active page follows")

    # deferred renderer fills the cache after a few event-loop turns
    for _ in range(20):
        app.processEvents()
    assert len(view._cache) >= 2, len(view._cache)

    # autosave writes a recovery snapshot for dirty documents
    from core import recovery
    win.dirty = True
    win._autosave_tick()
    assert any(m["original"] == win.doc.path for m in recovery.list_snapshots())
    recovery.discard_snapshot(win.doc.path)
    assert not any(m["original"] == win.doc.path for m in recovery.list_snapshots())
    print("[ok] deferred render cache + autosave snapshot")

    # zoom
    win.fit_width()
    app.processEvents()
    z1 = win.view.zoom
    win.actual_size()
    assert abs(win.view.zoom - 1.0) < 1e-6
    win.fit_page()
    app.processEvents()
    print(f"[ok] zoom fit width={z1:.2f} fit page={win.view.zoom:.2f}")

    # thumbnails
    win._sync_page(2)
    app.processEvents()
    print("[ok] thumbnails:", win.thumbs.list.count())

    # undo
    win.undo()
    win.undo()
    print("[ok] undo worked")

    # ---- v1.1 gestures: arrow + stamp
    win.go_page(0)
    win._set_tool("arrow")
    win._on_view_action("gesture", {"tool": "arrow", "rect": (60, 250, 200, 300),
                                    "p1": (60, 250), "p2": (200, 300)})
    assert win.doc.annotations(0)[-1]["kind"] == "arrow"
    win._stamp_values = {"text": "DRAFT", "fontsize": 20,
                         "color": (0.7, 0.1, 0.1)}
    win._set_tool("stamp")
    win._on_view_action("gesture", {"tool": "stamp",
                                    "rect": (300, 470, 430, 510)})
    assert any((a.get("content") or "") == "DRAFT"
               for a in win.doc.annotations(0))
    print("[ok] v1.1 arrow + stamp gestures")

    # ---- side panels
    win._refresh_comments()
    total = sum(len(win.doc.annotations(p)) for p in range(win.doc.page_count))
    assert win.comment_list.count() == total, (win.comment_list.count(), total)
    win.doc.snapshot("outline", 0)
    win.doc.set_outline([{"level": 1, "title": "Bab 1", "page": 0},
                         {"level": 2, "title": "Sub", "page": 2}])
    win._refresh_outline()
    assert win.outline_tree.topLevelItemCount() == 1
    assert win.outline_tree.topLevelItem(0).childCount() == 1
    print("[ok] comments + outline panels")

    # ---- watermark / page numbers / header & footer
    win._mutate("watermark", lambda: win.doc.watermark("UJI COBA", size=30))
    win._mutate("nomor", lambda: win.doc.page_numbers())
    win._mutate("header", lambda: win.doc.header_footer(footer="{page}/{total}"))
    assert "UJI COBA" in win.doc.text(0)
    assert "Halaman 1 dari 3" in win.doc.text(0)
    print("[ok] watermark, page numbers, header/footer")

    # ---- flattened (baked) highlight cleanup
    import pymupdf as fitz
    pg = win.doc.doc[0]
    pg.draw_rect(fitz.Rect(60, 620, 420, 636), color=None,
                 fill=(0.98, 0.93, 0.72))
    pg.insert_text((70, 632), "Latar kuning bawaan", fontsize=10)
    win.view.invalidate()
    assert win.doc.highlight_bands(0)
    from PySide6.QtWidgets import QMessageBox
    old_q = QMessageBox.question
    QMessageBox.question = lambda *a, **k: QMessageBox.Yes
    try:
        win.remove_flattened_highlight()
    finally:
        QMessageBox.question = old_q
    assert not win.doc.highlight_bands(0), "latar kuning harus ikut hilang"
    print("[ok] flattened highlight cleanup")

    # ---- contextual toolbar follows the active tool
    win._set_tool("text")
    assert win.context_bar.isVisible() and win.ctx_size.isVisible()
    assert win.ctx_font.isVisible() and not win.ctx_width.isVisible()
    win._set_tool("highlight")
    assert not win.ctx_size.isVisible() and not win.ctx_width.isVisible()
    win._set_tool("rect")
    assert win.ctx_width.isVisible()
    win._set_tool("select")
    assert not win.context_bar.isVisible()
    assert win.dock_comments.isVisible() and win.dock_outline.isVisible()
    print("[ok] contextual toolbar states")

    # ---- read mode + theme
    win.toggle_read_mode(True)
    assert win.view.read_mode
    assert not win.tool_rail.isVisible()
    win.toggle_read_mode(False)
    assert win.menuBar().isVisible()
    win.set_theme("light")
    assert "#f7f8fa" in win.styleSheet()
    win.set_theme("dark")
    assert "#1b1c1f" in win.styleSheet()
    print("[ok] read mode + theme switch")

    # ---- command palette builds from real actions
    from ui.palette import CommandPalette
    pal = CommandPalette(win, [{"title": "Simpan", "shortcut": "Ctrl+S", "run": None}])
    assert pal.list.count() == 1
    pal.close()

    # screenshot (page 1, fit width)
    win.go_page(0)
    win.fit_page()
    app.processEvents()
    app.processEvents()
    pm = win.grab()
    pm.save(OUT, "PNG")
    print("[ok] screenshot:", OUT, pm.width(), "x", pm.height())

    win.dirty = False
    win.doc.close()
    win.close()
    print("\nSEMUA TES UI LULUS")


if __name__ == "__main__":
    main()
