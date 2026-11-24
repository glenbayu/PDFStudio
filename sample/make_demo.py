"""Create a demo PDF used by the smoke test and by new users."""
from __future__ import annotations

import os
import sys

import pymupdf as fitz


def build(path: str) -> str:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    page.insert_text((60, 90), "PDF Studio", fontsize=30, color=(0.9, 0.28, 0.3))
    page.insert_text((60, 118), "Contoh dokumen untuk mencoba editor", fontsize=13,
                     color=(0.25, 0.25, 0.25))

    page.insert_text((60, 175), "1. Coba sorot teks ini dengan alat Sorot.", fontsize=12)
    page.insert_text((60, 200), "2. Klik di sini lalu tambahkan catatan tempel.", fontsize=12)
    page.insert_text((60, 225), "3. Pakai alat Teks untuk menulis di bawah ini.", fontsize=12)
    page.insert_text((60, 250), "4. Tanda tangan di kotak di bawah.", fontsize=12)

    page.draw_rect(fitz.Rect(60, 285, 300, 365), color=(0.6, 0.6, 0.6), width=1)
    page.insert_text((66, 302), "Tanda tangan:", fontsize=9, color=(0.45, 0.45, 0.45))

    page.insert_text((60, 410), "Isi formulir:", fontsize=12)
    page.draw_rect(fitz.Rect(60, 425, 330, 450), color=(0.55, 0.6, 0.7), width=0.8,
                   fill=(0.95, 0.97, 1.0))
    w = fitz.Widget()
    w.field_name = "nama"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.rect = fitz.Rect(60, 425, 330, 450)
    w.field_value = ""
    w.text_fontsize = 11
    page.add_widget(w)

    w2 = fitz.Widget()
    w2.field_name = "setuju"
    w2.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    w2.rect = fitz.Rect(60, 465, 76, 481)
    w2.field_value = False
    page.add_widget(w2)
    page.draw_rect(fitz.Rect(60, 465, 76, 481), color=(0.55, 0.6, 0.7), width=0.8)
    page.insert_text((84, 478), "Saya setuju dengan ketentuan", fontsize=11)

    # page 2
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((60, 90), "Halaman 2", fontsize=24)
    p2.insert_text((60, 130), "Gunakan tombol gabung / pisah untuk mengelola halaman.",
                   fontsize=12)
    p2.insert_text((60, 160), "Ctrl+Z untuk undo, Ctrl+S untuk menyimpan.", fontsize=12)

    # page 3, landscape-ish content
    p3 = doc.new_page(width=842, height=595)
    p3.insert_text((60, 90), "Halaman 3 (landscape)", fontsize=22)
    p3.draw_circle(fitz.Point(200, 300), 70, color=(0.2, 0.5, 0.9), width=3)
    p3.insert_text((330, 300), "Contoh grafik vektor", fontsize=14)

    doc.set_metadata({"title": "PDF Studio Demo", "author": "PDF Studio",
                      "subject": "Contoh dokumen", "keywords": "pdf, demo, editor"})
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("sample", "demo.pdf")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    print(build(out))
