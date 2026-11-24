"""Regression & feature tests for Phase 1-3 desktop standards upgrades."""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if "PDFSTUDIO_RECOVERY_DIR" not in os.environ:
    os.environ["PDFSTUDIO_RECOVERY_DIR"] = tempfile.mkdtemp(prefix="pdfrec_std_")
if "PDFSTUDIO_SIGNATURES_DIR" not in os.environ:
    os.environ["PDFSTUDIO_SIGNATURES_DIR"] = tempfile.mkdtemp(prefix="pdfsig_std_")
if os.name == "nt" and "QT_QPA_FONTDIR" not in os.environ:
    os.environ["QT_QPA_FONTDIR"] = os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf as fitz
from PySide6.QtCore import QPoint, QThread, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app as app_mod
from core.exporter import export_docx, export_text
from core.pdfdoc import PdfDoc, create_pdf_from_images, make_self_signed_pfx
from core import signatures as sigstore
from sample.make_demo import build
from ui import theme
from ui.dialogs import SignatureDialog, SignatureVerifyDialog
from ui.main_window import MainWindow
from ui.tools_dialogs import AddFormFieldDialog, CropDialog, PageImagesDialog
from ui.workers import run_in_background


def main():
    tmp = tempfile.mkdtemp(prefix="pdfstd_")
    pdf1 = os.path.join(tmp, "doc1.pdf")
    pdf2 = os.path.join(tmp, "doc2.pdf")
    build(pdf1)
    build(pdf2)

    # 1. Temp directory cleanup + atomic save in target directory
    d = PdfDoc()
    tdir = d.tmpdir
    assert os.path.isdir(tdir)
    d.open(pdf1)
    d.add_note(0, (120, 120), "atomic save check")
    d.save_as(pdf1)
    d.cleanup()
    assert not os.path.exists(tdir), "PdfDoc.cleanup() must remove owned tmpdir"
    print("[ok] atomic save + tmpdir cleanup")

    # 2. Multi-signature (Signature1 + Signature2) + verify_signatures()
    pfx = os.path.join(tmp, "cert.pfx")
    make_self_signed_pfx(pfx, "Glend Tester", "secret123")
    signed1 = os.path.join(tmp, "signed1.pdf")
    signed2 = os.path.join(tmp, "signed2.pdf")
    d = PdfDoc()
    d.open(pdf1)
    d.digital_sign(signed1, 0, (60, 620, 220, 680), pfx, "secret123", "First sign", "Jakarta")
    d.cleanup()

    d = PdfDoc()
    d.open(signed1)
    d.digital_sign(signed2, 0, (260, 620, 420, 680), pfx, "secret123", "Second sign", "Bandung")
    d.cleanup()

    d = PdfDoc()
    d.open(signed2)
    sigs = d.verify_signatures()
    assert len(sigs) == 2, f"expected 2 signatures, got {len(sigs)}"
    assert {s["field_name"] for s in sigs} == {"Signature1", "Signature2"}
    assert all(s["intact"] and s["valid"] for s in sigs), sigs
    d.cleanup()
    print("[ok] multi-signature (Signature1 & Signature2) + verify_signatures()")

    # 3. Create PDF from images
    img1 = os.path.join(tmp, "page1.png")
    img2 = os.path.join(tmp, "page2.png")
    for p, col in ((img1, "#ffffff"), (img2, "#eef2ff")):
        qi = QImage(300, 400, QImage.Format_RGB888)
        qi.fill(QColor(col))
        assert qi.save(p, "PNG")
    from_imgs = os.path.join(tmp, "from_imgs.pdf")
    count = create_pdf_from_images([img1, img2], from_imgs)
    assert count == 2 and os.path.exists(from_imgs)
    with fitz.open(from_imgs) as fd:
        assert fd.page_count == 2
    print("[ok] create_pdf_from_images (2 pages)")

    # 4. Persistent signature library
    sig_img = QImage(160, 60, QImage.Format_ARGB32)
    sig_img.fill(Qt.transparent)
    saved_sig = sigstore.save_signature_image(sig_img, "Paraf Resmi")
    assert os.path.exists(saved_sig)
    entries = sigstore.list_signatures()
    assert any(e["path"] == saved_sig for e in entries)
    assert sigstore.delete_signature(saved_sig)
    assert not os.path.exists(saved_sig)
    print("[ok] persistent signature library save/list/delete")

    # ---- Qt UI tests
    app = QApplication([])
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    app.processEvents()

    # 5. Multi-Tab workspace + Welcome Recent Files
    win.open_file(pdf1)
    win.open_file(pdf2)
    app.processEvents()
    assert len(win._tabs) == 2 and win.doc_tabs.count() == 2
    win.go_page(2)
    assert win.pno == 2
    # Re-opening pdf1 activates tab 0 instead of duplicating
    win.open_file(pdf1)
    app.processEvents()
    assert len(win._tabs) == 2 and win._active_tab == 0 and win.pno == 0
    # Switch back to tab 1 -> page 2 preserved
    win._activate_tab(1)
    app.processEvents()
    assert win.pno == 2
    # Close both tabs -> returns to Welcome screen with recent list
    assert win.close_tab(1)
    assert len(win._tabs) == 1
    assert win.close_tab(0)
    assert len(win._tabs) == 0
    assert win.scroll.widget() is win.welcome
    assert win.welcome.recent_list.count() >= 2
    print("[ok] multi-tab open/switch/dedup/close + welcome recent list")

    # 6. Signature verification banner & dialog
    win.open_file(signed2)
    app.processEvents()
    assert win.sig_banner.isVisible(), "signature banner must appear for signed PDF"
    vdlg = SignatureVerifyDialog(win, win._tabs[win._active_tab].sig_entries)
    vdlg.close()
    print("[ok] digital signature verification banner + dialog")

    # 7. Layout modes (continuous / single / two_page) & color modes (normal / night / sepia)
    win.set_layout_mode("single")
    app.processEvents()
    assert len(win.view._layout) == 1
    win.set_layout_mode("two_page")
    app.processEvents()
    assert len(win.view._layout) == 3
    # Pages 0 and 1 should sit on the same row (same y, different x)
    b0, b1 = win.view._layout[0], win.view._layout[1]
    assert abs(b0["y"] - b1["y"]) < 2.0 and b1["x"] > b0["x"], (b0, b1)
    win.set_layout_mode("continuous")
    app.processEvents()

    normal_img = win.view.page_pixmap(0)
    normal_px = normal_img.pixelColor(10, 10)
    win.set_color_mode("night")
    app.processEvents()
    night_img = win.view.page_pixmap(0)
    night_px = night_img.pixelColor(10, 10)
    assert abs(normal_px.red() - night_px.red()) > 100, (normal_px, night_px)
    win.set_color_mode("sepia")
    app.processEvents()
    sepia_img = win.view.page_pixmap(0)
    assert sepia_img is not None
    win.set_color_mode("normal")
    print("[ok] layout modes (single/two_page/continuous) + color modes (night/sepia)")

    # 8. Clickable hyperlinks (internal jump + external URI)
    link_pdf = os.path.join(tmp, "links.pdf")
    build(link_pdf)
    with fitz.open(link_pdf) as ld:
        ld[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(60, 60, 200, 90), "page": 2})
        ld[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(220, 60, 380, 90), "uri": "https://example.com"})
        ld.save(link_pdf + ".tmp")
    os.replace(link_pdf + ".tmp", link_pdf)

    win.open_file(link_pdf)
    win.fit_page()
    app.processEvents()
    v = win.view
    # Test internal link click -> jumps to page 2
    box0 = v._page_box(0)
    p_goto = QPoint(int(box0["x"] + 110 * v.zoom), int(box0["y"] + 75 * v.zoom))
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, p_goto)
    app.processEvents()
    assert win.pno == 2, f"expected jump to page 2, got {win.pno}"
    # Test external link detection
    ext_lk = v._link_at((280, 75), 0)
    assert ext_lk is not None and ext_lk.get("uri") == "https://example.com"
    print("[ok] clickable hyperlinks (internal jump + external URI)")

    # 9. Light theme icon re-tinting & viewer sync
    win.set_theme("light")
    assert theme.current_ink() == theme.LIGHT_INK
    assert win.view._theme_name == "light"
    win.set_theme("dark")
    assert theme.current_ink() == theme.INK
    assert win.view._theme_name == "dark"
    print("[ok] light/dark theme icon & canvas sync")

    # 10. External file watcher reload banner
    win._on_external_file_changed(link_pdf)
    assert win.reload_banner.isVisible()
    win._dismiss_reload_banner()
    assert not win.reload_banner.isVisible()
    print("[ok] external file watcher banner")

    # 11. Single-instance IPC opens file in new tab (real cross-process named pipe)
    import subprocess
    import time
    srv_name = f"PDFStudio_TestIPC_{os.getpid()}"
    srv = app_mod._start_ipc_server(win, srv_name)
    assert srv is not None
    child_code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from PySide6.QtCore import QCoreApplication; "
        "import app as m; "
        "a = QCoreApplication([]); "
        "ok = m._send_to_running_instance([sys.argv[2]], sys.argv[3]); "
        "sys.exit(0 if ok else 1)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", child_code,
         os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
         from_imgs, srv_name])
    deadline = time.time() + 10.0
    while proc.poll() is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert proc.wait(timeout=5) == 0, "IPC child process failed"
    for _ in range(25):
        app.processEvents()
        time.sleep(0.01)
    assert any(tb.doc.path and os.path.abspath(tb.doc.path) == os.path.abspath(from_imgs)
               for tb in win._tabs), "IPC did not open file in tab"
    srv.close()
    print("[ok] single-instance IPC opens file in running window (cross-process)")

    # 12. Background QThread worker runs off GUI thread
    gui_tid = app.thread()
    worker_tid = {}

    def bg_job(worker):
        worker_tid["tid"] = QThread.currentThread()
        worker.report(1, 2, "Langkah 1")
        worker.report(2, 2, "Selesai")
        return 42

    ok, val = run_in_background(win, "Tes Worker", "Mulai…", bg_job, maximum=2)
    assert ok and val == 42
    assert worker_tid["tid"] is not gui_tid, "worker must run off the GUI thread"
    print("[ok] background QThread worker + progress")

    # 13. SignatureDialog with saved signature library
    sdlg = SignatureDialog(win)
    sdlg.close()

    # 14. Regression: ellipse annot, encrypted save+info, sanitize(attachments=True), unicode replace
    reg_pdf = os.path.join(tmp, "reg.pdf")
    reg_enc = os.path.join(tmp, "reg_enc.pdf")
    build(reg_pdf)
    rd = PdfDoc()
    rd.open(reg_pdf)
    rd.add_shape(0, (300, 200, 400, 250), "ellipse", (0.2, 0.5, 0.8), 2.0)
    assert any(a["kind"] == "ellipse" for a in rd.annotations(0))
    rd.sanitize(metadata=True, javascript=True, embedded=True, hidden=True, attachments=True)
    rd.protect(reg_enc, "pw123", "pw123", allow_print=True, allow_copy=True, allow_modify=True)
    rd.cleanup()

    rd = PdfDoc()
    rd.open(reg_enc, "pw123")
    assert rd.info()["encrypted"] is True
    rd.add_note(0, (100, 100), "encrypted note")
    rd.save_as(reg_enc)
    rd.cleanup()
    rd = PdfDoc()
    rd.open(reg_enc, "pw123")
    assert rd.info()["encrypted"] is True
    assert any("encrypted note" in (a.get("content") or "") for a in rd.annotations(0))
    rd.cleanup()
    print("[ok] regressions: ellipse annot, AES-256 save+info, sanitize(attachments=True)")

    # 15. Feature 1: Export to Word (.docx) & Plain Text (.txt)
    import zipfile
    import xml.etree.ElementTree as ET
    exp_pdf = os.path.join(tmp, "export_src.pdf")
    build(exp_pdf)
    ed = PdfDoc()
    ed.open(exp_pdf)
    ed.insert_image(0, (360, 500, 480, 600), img1)
    out_txt = os.path.join(tmp, "out.txt")
    out_docx = os.path.join(tmp, "out.docx")
    assert export_text(ed, out_txt) == 3
    assert "PDF Studio" in open(out_txt, encoding="utf-8").read()
    assert export_docx(ed, out_docx) == 3
    with zipfile.ZipFile(out_docx, "r") as zf:
        names = set(zf.namelist())
        assert "word/document.xml" in names
        assert any(n.startswith("word/media/image") for n in names), names
        xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        all_t = "".join(root.itertext())
        assert "PDF Studio" in all_t
    ed.cleanup()
    print("[ok] export to Word (.docx with embedded image) & Text (.txt)")

    # 16. Feature 2: Search results sidebar + Case-Sensitive + Whole-Word
    win.open_file(pdf1)
    app.processEvents()
    win.search_case_btn.setChecked(True)
    win.search_word_btn.setChecked(True)
    win.search_edit.setText("Sorot")
    win.run_search()
    assert win.search_list.count() >= 1
    win.search_edit.setText("SOROT")
    win.run_search()
    assert win.search_list.count() == 0, "Case-sensitive search must not match SOROT"
    win.search_case_btn.setChecked(False)
    win.search_word_btn.setChecked(False)
    win.search_edit.setText("halaman")
    win.run_search()
    assert win.search_list.count() >= 2
    win._on_search_item_clicked(win.search_list.item(win.search_list.count() - 1))
    print("[ok] search sidebar + case-sensitive (Aa) + whole-word (Kata)")

    # 17. Feature 3: Crop margins (auto-crop, manual crop, reset crop) + CropDialog
    cdlg = CropDialog(win, win.doc.page_count, win.pno)
    assert cdlg.values()["mode"] == "auto"
    cdlg.close()
    w_orig, h_orig = win.doc.page_size(0)
    assert win.doc.auto_crop_pages([0], margin=10.0) == 1
    w_auto, h_auto = win.doc.page_size(0)
    assert w_auto < w_orig and h_auto < h_orig, ((w_orig, h_orig), (w_auto, h_auto))
    assert win.doc.reset_crop([0]) == 1
    assert abs(win.doc.page_size(0)[0] - w_orig) < 1.0
    assert win.doc.crop_pages([0], top=20, bottom=20, left=20, right=20) == 1
    assert abs(win.doc.page_size(0)[0] - (w_orig - 40)) < 1.0
    win.doc.reset_crop([0])
    print("[ok] page crop (auto-crop / manual / reset) + CropDialog")

    # 18. Feature 4: Mixed Bold/Italic preservation during inline edit + Ctrl+B/Ctrl+I
    mix_pdf = os.path.join(tmp, "mixed.pdf")
    md = fitz.open()
    mp = md.new_page(width=595, height=842)
    mp.insert_text((72, 120), "Teks biasa dengan ", fontsize=12, fontname="tiro")
    mp.insert_text((170, 120), "kata miring", fontsize=12, fontname="tiit")
    mp.insert_text((232, 120), " di tengah.", fontsize=12, fontname="tiro")
    md.save(mix_pdf)
    md.close()
    m = PdfDoc()
    m.open(mix_pdf)
    info_m = m.text_at(0, (120, 116))
    assert info_m is not None
    runs = info_m.get("rich_runs") or []
    assert any(it for _c, _b, it in runs) and any(not it for _c, _b, it in runs), runs
    # Replace preserving mixed italic + adding bold word
    new_runs = [("Teks ", False, False), ("tebal", True, False), (" dan ", False, False), ("miring", False, True)]
    m.replace_text(
        0, info_m["rect"], "Teks tebal dan miring", info_m["size"], info_m["font"],
        info_m["color"], info_m["bg"], bold=info_m["bold"], italic=info_m["italic"],
        baseline=info_m["baseline"], single=info_m["single"],
        font_name=info_m["font_name"], line_gap=info_m["line_gap"],
        rich_runs=new_runs, style_fonts=info_m.get("style_fonts"))
    spans_after = [s for b in m.page(0).get_text("dict")["blocks"] for ln in b.get("lines", []) for s in ln.get("spans", [])]
    has_bold = any(("bold" in (s.get("font") or "").lower() or (s.get("flags", 0) & 16)) and "tebal" in s.get("text", "") for s in spans_after)
    has_italic = any(("italic" in (s.get("font") or "").lower() or "oblique" in (s.get("font") or "").lower() or (s.get("flags", 0) & 2)) and "miring" in s.get("text", "") for s in spans_after)
    assert has_bold and has_italic, spans_after
    m.cleanup()
    print("[ok] mixed inline bold/italic preservation + rich_runs")

    # 19. Feature 5: Manage embedded page images + Form Field Builder
    img_pdf = os.path.join(tmp, "img_mgr.pdf")
    build(img_pdf)
    im = PdfDoc()
    im.open(img_pdf)
    im.insert_image(0, (340, 480, 460, 580), img1)
    imgs = im.page_images(0)
    assert len(imgs) == 1
    ext_img = os.path.join(tmp, "extracted.png")
    assert im.extract_page_image(imgs[0]["xref"], ext_img) and os.path.getsize(ext_img) > 100
    assert im.replace_page_image(0, imgs[0]["xref"], img2)
    pidlg = PageImagesDialog(win, im, 0, tmp)
    assert pidlg.list.count() == 1
    pidlg.close()
    assert im.delete_page_image(0, imgs[0]["xref"])
    assert len(im.page_images(0)) == 0

    fdlg = AddFormFieldDialog(win)
    assert fdlg.values()["kind"] == "text"
    fdlg.close()
    fn1 = im.add_form_field(0, (60, 620, 220, 646), "text", "email_user", default="a@b.com")
    fn2 = im.add_form_field(0, (240, 620, 260, 640), "checkbox", "setuju_baru")
    fn3 = im.add_form_field(0, (280, 620, 430, 646), "combobox", "jurusan", options=["SIIO", "ABO", "TIO"])
    im.save_as(img_pdf)
    im.cleanup()
    im = PdfDoc()
    im.open(img_pdf)
    wmap = {w["name"]: w for w in im.widgets(0)}
    assert fn1 in wmap and fn2 in wmap and fn3 in wmap, wmap.keys()
    assert wmap[fn1]["value"] == "a@b.com"
    assert im.set_widget(0, fn2, True)
    im.cleanup()
    print("[ok] embedded image manager (list/extract/replace/delete) + form field builder (text/checkbox/dropdown)")

    # Close cleanly
    for tab in win._tabs:
        tab.dirty = False
    win.dirty = False
    win.close()
    print("\nSEMUA TES DESKTOP STANDARDS LULUS")


if __name__ == "__main__":
    main()
