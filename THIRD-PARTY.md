# Komponen pihak ketiga

PDF Studio dibangun dengan komponen open source berikut:

| Komponen | Versi | Lisensi | Situs |
|---|---|---|---|
| Python | 3.12 | PSF License | https://www.python.org |
| PySide6 (Qt for Python) | 6.12 | LGPL-3.0 | https://www.qt.io/qt-for-python |
| PyMuPDF | 1.28 | AGPL-3.0 | https://pymupdf.readthedocs.io |
| pyHanko | 0.38 | MIT | https://pyhanko.readthedocs.io |
| cryptography | 50.x | Apache-2.0 / BSD-3-Clause | https://cryptography.io |
| Tesseract OCR (opsional) | 5.x | Apache-2.0 | https://github.com/tesseract-ocr/tesseract |

## Catatan AGPL

PyMuPDF dilisensikan di bawah GNU Affero General Public License v3.0
(AGPL-3.0). Karena PDF Studio memakai PyMuPDF, distribusi aplikasi ini juga
tunduk pada AGPL-3.0. Konsekuensinya:

- Kode sumber PDF Studio harus tersedia bagi siapa pun yang menerima binary.
- Jika PDF Studio dijalankan sebagai layanan jaringan, pengguna layanan juga
  berhak mendapatkan kode sumbernya.
- Salinan lisensi lengkap ada di berkas `LICENSE`.

Berkas sumber proyek ini disertakan di samping binary pada paket installer.
