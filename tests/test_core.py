"""Headless functional tests for the PDF engine."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pdfdoc import PdfDoc, make_self_signed_pfx, strip_password
from sample.make_demo import build


def main():
    tmp = tempfile.mkdtemp(prefix="pdftest_")
    demo = os.path.join(tmp, "demo.pdf")
    build(demo)
    src_size = os.path.getsize(demo)
    print(f"[ok] demo built: {src_size/1024:.1f} KB")

    doc = PdfDoc()
    doc.open(demo)
    assert doc.page_count == 3, doc.page_count
    print("[ok] opened, pages =", doc.page_count)

    # rendering
    pix = doc.render(0, 1.5)
    assert pix.width > 500 and pix.height > 500
    print(f"[ok] render {pix.width}x{pix.height}")

    # annotation markup
    n = doc.annot_text_markup(0, (55, 165, 400, 182), "highlight", (1, 0.85, 0.1))
    assert n >= 1, n
    doc.add_note(0, (420, 195), "Catatan uji")
    doc.add_ink(0, [[(320, 200), (340, 215), (360, 205)]], (0.9, 0.2, 0.2), 2)
    assert doc.add_text(0, (60, 380, 300, 400), "Teks baru dari tes", 12, "Times",
                        (0, 0, 0.8), bold=True)
    doc.add_shape(0, (350, 380, 450, 430), "rect", (0.2, 0.6, 0.3), 2)
    print("[ok] markup, note, ink, text, shape")

    # form fill
    widgets = doc.widgets(0)
    names = [w["name"] for w in widgets]
    assert "nama" in names and "setuju" in names, names
    for w in widgets:
        if w["name"] == "nama":
            assert doc.set_widget(0, "nama", "Glend")
        if w["name"] == "setuju":
            assert doc.set_widget(0, "setuju", True)
    print("[ok] form widgets:", names)

    # image insert
    icon = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "app.png")
    os.makedirs(os.path.dirname(icon), exist_ok=True)
    from PySide6.QtGui import QGuiApplication
    from ui import theme
    app = QGuiApplication.instance() or QGuiApplication([])
    theme.app_pixmap(256).save(icon, "PNG")
    assert doc.insert_image(0, (330, 160, 400, 230), icon)
    print("[ok] image insert")

    # text edit / sample colour
    bg = doc.sample_color(0, (60, 168, 400, 184))
    print("[ok] bg sample", tuple(round(c, 2) for c in bg))
    doc.replace_text(1, (55, 120, 520, 140), "Baris ini diganti oleh mesin edit teks.",
                     12, "Helvetica", (0, 0, 0), bg)
    assert "diganti oleh mesin" in doc.text(1)
    print("[ok] text replace")

    # inline baseline edit (paragraph detect + reflow, same font path)
    info = doc.text_at(0, (200, 170))
    assert info and info.get("baseline") is not None, "text_at gagal"
    long_text = info["text"] + " Ditambah lagi supaya baris ikut ditata ulang."
    doc.replace_text(0, info["rect"], long_text, info["size"], info["font"],
                     info["color"], info["bg"], bold=info["bold"],
                     italic=info["italic"], baseline=info["baseline"],
                     single=info["single"], font_name=info["font_name"],
                     line_gap=info["line_gap"])
    assert "Ditambah lagi" in doc.text(0).replace("\n", " ")
    print("[ok] inline baseline edit + reflow")

    # save as
    out = os.path.join(tmp, "edited.pdf")
    doc.save_as(out)
    assert os.path.exists(out) and doc.path == os.path.abspath(out)
    print(f"[ok] saved as {os.path.basename(out)} ({os.path.getsize(out)/1024:.1f} KB)")

    # undo / redo
    doc.snapshot("uji", 0)
    doc.add_text(0, (60, 430, 300, 450), "akan di-undo", 11)
    assert "akan di-undo" in doc.text(0)
    res = doc.undo()
    assert res is not None
    assert "akan di-undo" not in doc.text(0)
    doc.redo()
    assert "akan di-undo" in doc.text(0)
    doc.undo()
    print("[ok] undo/redo")

    # page ops
    doc.rotate_page(0, 90)
    doc.insert_blank(1)
    assert doc.page_count == 4
    doc.move_page(3, 1)
    doc.delete_page(1)
    assert doc.page_count == 3
    print("[ok] rotate / insert / move / delete")

    # extract + merge + compress
    part = os.path.join(tmp, "part.pdf")
    doc.extract([0, 2], part)
    assert os.path.getsize(part) > 1000
    n = doc.merge(part)
    assert n == 2 and doc.page_count == 5, (n, doc.page_count)
    comp = os.path.join(tmp, "comp.pdf")
    doc.compress_to(comp)
    print(f"[ok] extract/merge/compress  ({os.path.getsize(comp)/1024:.1f} KB)")

    # protect + strip
    prot = os.path.join(tmp, "prot.pdf")
    doc.protect(prot, "rahasia123", "owner456", allow_print=True, allow_copy=False)
    check = PdfDoc()
    try:
        check.open(prot)
        raise AssertionError("seharusnya butuh password")
    except PermissionError:
        pass
    check.open(prot, "rahasia123")
    assert check.page_count == 5
    check.close()
    unlocked = os.path.join(tmp, "unlocked.pdf")
    strip_password(prot, unlocked, "rahasia123")
    fresh = PdfDoc()
    fresh.open(unlocked)
    assert fresh.page_count == 5
    fresh.close()
    print("[ok] password protect / unlock")

    # digital signature
    pfx = os.path.join(tmp, "cert.pfx")
    make_self_signed_pfx(pfx, "Glend Test", "certpass")
    signed = os.path.join(tmp, "signed.pdf")
    doc.digital_sign(signed, 0, (330, 160, 470, 230), pfx, "certpass",
                     "Persetujuan uji", "Jakarta")
    assert os.path.getsize(signed) > 1000
    print(f"[ok] PAdES sign ({os.path.getsize(signed)/1024:.1f} KB)")

    # verify signature
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        with open(signed, "rb") as f:
            reader = PdfFileReader(f, strict=False)
            sigs = reader.embedded_signatures
            assert len(sigs) == 1
            print("[ok] embedded signature fields:", len(sigs),
                  "| subfilter:", sigs[0].sig_object.get("/SubFilter"))
    except Exception as exc:
        raise AssertionError(f"verifikasi gagal: {exc}")

    # ------------------------------------------------- v1.1 engine features
    v = PdfDoc()
    v.open(demo)

    def find(xref, pno=0):
        return next((a for a in v.annotations(pno) if a["xref"] == xref), None)

    line_x = v.add_line(0, (60, 62), (210, 92), (0.1, 0.1, 0.9), 2, arrow=True)
    assert line_x and find(line_x)["kind"] == "arrow", find(line_x)
    plain_x = v.add_line(0, (60, 100), (210, 100), (0.1, 0.6, 0.2), 1.5)
    assert plain_x and find(plain_x)["kind"] == "line"
    callout_x = v.add_callout(0, (250, 120, 420, 168), "Cek bagian ini", (240, 250))
    assert callout_x and "Cek bagian" in find(callout_x)["content"]
    stamp_x = v.add_stamp_text(0, (300, 62, 470, 104), "APPROVED")
    assert stamp_x and find(stamp_x)["kind"] == "freetext"
    poly_x = v.add_polyline(0, [(60, 300), (120, 340), (180, 300)],
                            (0.8, 0.2, 0.1), 2, closed=True)
    assert poly_x and find(poly_x)["kind"] == "polygon"
    assert v.update_annotation(0, stamp_x, rect=(300, 64, 480, 106), opacity=0.9,
                               width=2.5)
    assert v.update_annotation(0, line_x, color=(0.9, 0.1, 0.1), content="panah uji")
    assert find(line_x)["width"] >= 1.5
    assert v.delete_annotation(0, plain_x) and find(plain_x) is None
    print("[ok] v1.1 annotations: line/arrow/callout/stamp/polygon + update/delete")

    # watermark / numbering / furniture
    assert v.watermark("RAHASIA", size=40) == v.page_count
    assert "RAHASIA" in v.text(0), "watermark harus teks asli"
    assert v.page_numbers(position="bottom-center", start=1) == v.page_count
    assert "Halaman 1 dari 3" in v.text(0), v.text(0)[:200]
    assert v.header_footer(footer="{page}/{total}", header="{title}") == v.page_count
    assert "1/3" in v.text(0)
    print("[ok] v1.1 watermark (selectable text), page numbers, header/footer")

    # search & replace
    res = v.search_replace("Coba", "Uji coba")
    assert res and sum(n for _p, n in res) >= 1, res
    assert "Uji coba" in v.text(0)
    res = v.search_replace("SOROT", "sorotan", match_case=True)
    assert res == [], res
    res = v.search_replace(r"Uji\s+coba", "Coba", regex=True)
    assert res and "Coba" in v.text(0)
    print("[ok] v1.1 search & replace (case, regex) with original fonts")

    # outline
    v.set_outline([{"level": 1, "title": "Awal", "page": 0},
                   {"level": 2, "title": "Tengah", "page": 1},
                   {"level": 1, "title": "Akhir", "page": 2}])
    toc = v.outline()
    assert [e["title"] for e in toc] == ["Awal", "Tengah", "Akhir"], toc
    assert toc[1]["level"] == 2 and toc[2]["page"] == 2
    print("[ok] v1.1 outline/bookmarks")

    # attachments
    att = os.path.join(tmp, "lampiran.txt")
    with open(att, "w", encoding="utf-8") as f:
        f.write("isi lampiran")
    v.add_attachment(att, "catatan uji")
    items = v.attachments()
    assert items and items[0]["size"] == len("isi lampiran"), items
    extracted = os.path.join(tmp, "lampiran_keluar.txt")
    v.extract_attachment(items[0]["name"], extracted)
    with open(extracted, encoding="utf-8") as f:
        assert f.read() == "isi lampiran"
    assert v.delete_attachment(items[0]["name"]) and v.attachments() == []
    print("[ok] v1.1 attachments add/extract/delete")

    # pages: duplicate + insert from
    before = v.page_count
    v.duplicate_page(0)
    assert v.page_count == before + 1
    v.insert_pages_from(demo, [0, 1], 1)
    assert v.page_count == before + 3
    print("[ok] v1.1 duplicate page + insert pages from another PDF")

    # compare
    same_path = build(os.path.join(tmp, "same.pdf"))
    same = PdfDoc()
    same.open(same_path)
    result_same = same.compare_text(demo)
    assert result_same["added"] == 0 and result_same["removed"] == 0
    same.close()
    other = os.path.join(tmp, "other.pdf")
    build(other)
    diff = v.compare_text(other)
    assert diff["pages"] and diff["removed"] >= 1, diff["pages"][:2]
    print("[ok] v1.1 compare:", diff["removed"], "baris beda")

    # links + sanitize
    assert isinstance(v.links(0), list)
    report = v.sanitize(metadata=True, javascript=True, embedded=True,
                        hidden=True, attached=True)
    assert report["metadata"] and report["javascript"]
    print("[ok] v1.1 links + sanitize")

    # watermark must survive save/reload as selectable text
    vout = os.path.join(tmp, "v11.pdf")
    v.save_as(vout)
    v.close()
    again = PdfDoc()
    again.open(vout)
    assert "RAHASIA" in again.text(0), "watermark hilang setelah simpan"
    again.close()
    print("[ok] v1.1 watermark persists as real text")

    # autosave snapshot + OCR capability probe
    from core import recovery
    meta = recovery.write_snapshot(doc, page=1, zoom=1.1)
    assert meta and os.path.exists(meta["snapshot"])
    assert any(m["snapshot"] == meta["snapshot"] for m in recovery.list_snapshots())
    recovery.discard_snapshot(doc.path)
    assert not any(m["snapshot"] == meta["snapshot"] for m in recovery.list_snapshots())
    assert isinstance(doc.pages_without_text(), list)
    assert doc.ocr_available() in (True, False)
    if not doc.ocr_available():
        try:
            doc.ocr_page(0)
            raise AssertionError("OCR seharusnya melempar error tanpa Tesseract")
        except RuntimeError:
            pass
    print("[ok] autosave snapshot + OCR probe")

    # flattened (baked) yellow highlight cleanup keeps the text underneath
    import pymupdf as fitz
    pg = doc.doc[0]
    base = len(doc.highlight_bands(0))
    pg.draw_rect(fitz.Rect(60, 640, 400, 656), color=None,
                 fill=(0.98, 0.93, 0.72))
    pg.insert_text((70, 652), "Baris latar kuning", fontsize=10)
    doc.doc.reload_page(pg)
    assert len(doc.highlight_bands(0)) == base + 1, doc.highlight_bands(0)
    assert doc.remove_highlight_bands(0) >= 1
    assert doc.highlight_bands(0) == [], doc.highlight_bands(0)
    # saturated yellow (a logo, not a highlight) must be left alone
    pg = doc.doc[0]
    pg.draw_rect(fitz.Rect(60, 680, 90, 710), color=None, fill=(1.0, 0.8, 0.0))
    doc.doc.reload_page(pg)
    assert doc.highlight_bands(0) == [], "kuning pekat bukan latar stabilo"
    saved = os.path.join(tmp, "bands.pdf")
    doc.save_as(saved)
    check = PdfDoc()
    check.open(saved)
    assert check.highlight_bands(0) == []
    assert "Baris latar kuning" in check.text(0)
    check.close()
    print("[ok] flattened yellow highlight cleanup")

    # OCR: an image-only page gets a real (invisible) text layer. Uses
    # Tesseract or the built-in Windows engine, whichever is present.
    if doc.ocr_available():
        src = fitz.open()
        ip = src.new_page(width=595, height=842)
        ip.insert_text((70, 140), "INVOICE", fontsize=52, fontname="helv")
        png = os.path.join(tmp, "scan.png")
        ip.get_pixmap(dpi=200, alpha=False).save(png)
        src.close()
        scan_pdf = fitz.open()
        sp = scan_pdf.new_page(width=595, height=842)
        sp.insert_image(sp.rect, filename=png)
        scan_path = os.path.join(tmp, "scan.pdf")
        scan_pdf.save(scan_path)
        scan_pdf.close()
        sdoc = PdfDoc()
        sdoc.open(scan_path)
        assert sdoc.needs_ocr(0), "halaman gambar harus terdeteksi hasil scan"
        words = sdoc.ocr_page(0)
        assert words > 0, "OCR tidak menghasilkan kata"
        assert "INVOICE" in sdoc.text(0).upper(), sdoc.text(0)[:120]
        sdoc.close()
        print(f"[ok] OCR fallback ({doc.ocr_engine_name()}): {words} kata")
    else:
        print("[skip] OCR tidak tersedia di mesin ini")

    doc.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print("\nSEMUA TES CORE LULUS")


if __name__ == "__main__":
    main()
