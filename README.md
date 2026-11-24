# PDF Studio

PDF editor desktop untuk Windows: buka, edit teks, anotasi, isi formulir, kelola halaman,
kunci password, dan tanda tangan — tanpa langganan.

Dibangun dengan **Python + PySide6 (Qt) + PyMuPDF + pyHanko**.

![ikon](assets/app.ico)

## Fitur

| Kategori | Fitur |
|---|---|
| Melihat | Gulir kontinu antar halaman (seperti Acrobat), render bertahap anti-ngadat, zoom (Ctrl+scroll), fit width/page, thumbnail halaman, navigasi cepat, mode baca (F11), tema gelap/terang |
| Anotasi | Sorot, garis bawah, coret, squiggly, catatan tempel, tinta bebas, kotak, elips, garis, panah, callout, stempel teks, gambar |
| Kelola anotasi | Pilih dengan klik, pindahkan dengan drag, ubah ukuran lewat 8 handle, ubah warna/isi/opasitas, hapus (Delete), panel Komentar |
| Edit teks | Klik teks langsung di halaman → kursor muncul di situ, ketik, Enter simpan (Shift+Enter baris baru, Esc batal). Font asli PDF dipakai ulang |
| Cari & ganti | Cari seluruh dokumen, ganti massal per paragraf (case-sensitive / whole word / regex), font asli dipertahankan |
| Tanda tangan | Gambar tanda tangan di layar / impor PNG, lalu tempel di halaman |
| TTD digital | Tanda tangan PAdES dengan sertifikat `.pfx`/`.p12` (bisa buat self-signed untuk uji coba) |
| Formulir | Isi field AcroForm: teks, checkbox, radio, dropdown |
| Halaman | Putar, hapus, sisip halaman kosong, pindah urutan (drag di thumbnail), duplikat, sisip halaman dari PDF lain, ambil/pisah, gabung PDF |
| Tata letak dokumen | Watermark teks (tetap bisa diseleksi), nomor halaman, header & footer dengan placeholder `{page}`/`{total}`/`{title}`/`{date}` |
| Navigasi dokumen | Outline/bookmark (buat dari daftar halaman), panel outline, tautan halaman, lampiran (embed & ekstrak file) |
| Produktivitas | Command palette (Ctrl+K), proses banyak file sekaligus (batch), bandingkan teks dua PDF, sanitasi metadata/JavaScript/lampiran |
| Berkas | Simpan / Simpan Sebagai, kompres, ekspor PNG, properti dokumen, cetak (dialog printer) |
| Keamanan | Proteksi password AES-256 + izin cetak/salin/ubah, hapus password (dengan password lama) |
| Pemulihan | Autosave snapshot berkala + dialog pulihkan otomatis kalau aplikasi mati mendadak |
| Scan | OCR halaman hasil scan (bawaan Windows 10/11, atau Tesseract bila terpasang) menambah layer teks agar bisa dicari, disalin, dan diedit |
| Lain | Undo/redo (20 langkah), drag & drop, redaksi permanen, flatten anotasi |

## Cara pakai (versi terinstal)

1. Ekstrak `PDFStudio-Setup-1.2.zip`
2. Klik dua kali **`Install PDF Studio.cmd`**
3. Aplikasi terpasang di `%LOCALAPPDATA%\Programs\PDFStudio` dan shortcut dibuat di Desktop + Start Menu.
4. Uninstall lewat *Settings → Apps → PDF Studio*, atau jalankan `uninstall.ps1` di folder instalasi.

Windows SmartScreen mungkin memperingatkan karena exe tidak ditandatangani secara komersial:
klik **More info → Run anyway**.

## Cara pakai (portable)

Jalankan langsung `dist\PDFStudio\PDFStudio.exe` — tidak perlu instalasi.

## Edit teks langsung di halaman

1. Pilih alat **Edit Teks** (ikon huruf T dengan kursor).
2. **Klik teks yang mau diubah** — kotak edit langsung muncul menimpa paragraf itu,
   tanpa dialog popup dan tanpa perlu menyeleksi teks dulu.
3. Ketik penggantinya. **Enter** = simpan, **Shift+Enter** = baris baru, **Esc** = batal.
4. Klik di luar kotak juga otomatis menyimpan.
5. Kalau kamu men-drag di dalam satu paragraf (kebiasaan versi lama), editor di halaman
   tetap yang terbuka. Drag mulai dari area kosong untuk mengganti blok lewat dialog.

Paragraf multi-baris ikut ditata ulang. Kalau teks baru lebih panjang, baris akan
turun dan bisa menutupi konten di bawahnya — koreksi pendek lebih aman.

## Shortcut

| Tombol | Aksi |
|---|---|
| Ctrl+O / Ctrl+S / Ctrl+Shift+S | Buka / Simpan / Simpan Sebagai |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| Ctrl+F / Ctrl+H | Cari / Cari & ganti |
| Ctrl+K | Command palette |
| Ctrl+P | Cetak |
| Ctrl++ / Ctrl+- | Zoom |
| Ctrl+0 / Ctrl+1 / Ctrl+2 | Fit page / ukuran asli / fit width |
| Ctrl+[ / Ctrl+] | Putar halaman kiri / kanan |
| Alt+Up / Alt+Down | Pindah urutan halaman |
| PgUp / PgDn, Ctrl+Home/End | Navigasi halaman |
| Ctrl+C, Ctrl+A | Salin teks terpilih, pilih semua teks |
| Ctrl+drag, Space | Geser halaman |
| Scroll roda mouse | Geser dokumen (gulir kontinu) |
| Delete | Hapus anotasi terpilih |
| F1 / F11 | Daftar shortcut / mode baca |
| Esc | Batalkan gesture / tutup editor teks |

## Tips v1.2

- **Pindah/ubah anotasi**: pakai alat **Pilih**, klik anotasi, lalu drag badan untuk
  memindahkan atau tarik salah satu dari 8 handle untuk mengubah ukuran.
  Klik kanan untuk menu properti/hapus.
- **Watermark & nomor halaman** ditulis sebagai teks asli, jadi tetap bisa
  dicari/diseleksi dan ikut tersimpan saat PDF dibuka di aplikasi lain.
- **Header/footer** mendukung placeholder `{page}`, `{total}`, `{title}`, `{date}`.
- **Bandingkan PDF** menampilkan baris teks yang ditambah/dihapus per halaman.
- **Lampiran** bisa disisipkan dan diekstrak lagi tanpa mengubah tampilan halaman.
- **Mode baca (F11)** menyembunyikan menu, panel, dan tool rail untuk fokus membaca.
- **Gulir kontinu**: scroll roda mouse menggeser dokumen seperti Acrobat; halaman
  aktif mengikuti posisi tengah layar.
- **Render bertahap**: halaman aktif digambar langsung, tetangganya menyusul di
  sela event loop supaya UI tidak membeku.
- **Autosave**: snapshot otomatis tiap 45 detik; kalau aplikasi mati mendadak,
  dialog pemulihan muncul saat dibuka lagi.
- **OCR scan**: Dokumen → OCR Halaman Scan… memakai OCR bawaan Windows 10/11,
  jadi tidak wajib install Tesseract. Kalau Tesseract terpasang, itu yang dipakai.
  Cukup klik alat **Edit Teks** di halaman scan → PDF Studio menawarkan OCR untuk
  halaman itu, lalu klik teksnya lagi untuk mengedit (tulisan baru ditulis di
  atas area scan, jadi tampilannya tidak identik dengan font asli).
- **Stabilo yang menempel di halaman**: kalau blok kuning tetap ada setelah
  anotasi dihapus, itu bagian dari isi halaman (di-*flatten* oleh aplikasi lain).
  Pakai Dokumen → **Hapus Latar Stabilo (Flatten)…** — warna latar diubah jadi
  putih, teks di atasnya tetap utuh. Stabilo dari file mana pun bisa dihapus;
  untuk anotasi, klik kanan → Hapus anotasi / Hapus semua anotasi di halaman.
- **Command palette (Ctrl+K)** mencari semua perintah berdasarkan nama.

## Build dari source

```powershell
# butuh Python 3.10–3.13 (64-bit)
powershell -ExecutionPolicy Bypass -File build.ps1
```

Hasil:
- `dist\PDFStudio\PDFStudio.exe` (portable, folder)
- `dist\PDFStudio-Setup-1.2.zip` (installer)

Build manual:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe packaging\make_icon.py assets\app.ico
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean packaging\PDFStudio.spec
```

## Struktur project

```
app.py                 entry point
core/pdfdoc.py         mesin PDF (PyMuPDF): anotasi, teks, watermark, outline, lampiran
ui/main_window.py      window, menu, toolbar, tool rail, panel, controller
ui/viewer.py           kanvas halaman: render, seleksi teks, gesture, anotasi
ui/dialogs.py          dialog inti (teks, tanda tangan, password, sertifikat, tentang)
ui/tools_dialogs.py    dialog v1.1 (watermark, nomor halaman, stempel, bandingkan, batch)
ui/palette.py          command palette (Ctrl+K)
ui/thumbnails.py       panel thumbnail + drag urutan + menu konteks
ui/theme.py            ikon vektor + tema gelap/terang
tests/                 tes headless (core, UI, interaksi mouse, installer)
packaging/             spec PyInstaller, versi, generator ikon
installer/             skrip install/uninstall
```

## Tes

```powershell
.\.venv\Scripts\python.exe tests\test_core.py
.\.venv\Scripts\python.exe tests\test_ui.py
.\.venv\Scripts\python.exe tests\test_interactions.py
```

## Batasan yang perlu diketahui

- **Edit teks** menghapus teks lama di area paragraf lalu menulis ulang. Font yang
  tertanam di PDF dipakai ulang (per-karakter fallback bila subset font tidak lengkap),
  jadi hasilnya biasanya menyatu dengan halaman. Teks yang jauh lebih panjang akan
  mengalir ke bawah dan bisa menimpa konten di bawahnya; ini bukan typesetting ulang
  seluruh dokumen.
- PDF hasil scan (gambar) tidak punya teks untuk diedit. Pakai **Dokumen → OCR
  Halaman Scan…** (butuh Tesseract + data bahasa terpasang) untuk menambah layer
  teks, setelah itu teks bisa dicari/disalin/diedit.
- Tanda tangan visual = gambar yang ditempel (bukan kriptografis). Untuk validasi
  kriptografis pakai **TTD Digital** dengan sertifikat.
- Sertifikat self-signed hanya untuk uji coba; tanda tangan tersertifikasi legal butuh
  sertifikat dari PSrE (mis. Peruri, Privy, dsb.).
- PDF dengan DRM/IRM atau password owner yang tidak diketahui tidak bisa dibuka/diubah.

## Lisensi & catatan hukum

- Kode aplikasi ini: bebas kamu pakai dan modifikasi untuk keperluan pribadi.
- **PyMuPDF** berlisensi **AGPL-3.0** (atau lisensi komersial Artifex). Jika kamu
  mendistribusikan aplikasi ini ke publik, kamu wajib merilis source-nya di bawah AGPL
  atau membeli lisensi komersial PyMuPDF.
- **PySide6/Qt** berlisensi LGPL-3.0; **pyHanko** MIT; **cryptography** Apache-2.0/BSD.
- Teks lisensi AGPL lengkap ada di `LICENSE`; daftar komponen pihak ketiga ada di
  `THIRD-PARTY.md`.
- Gunakan hanya pada dokumen yang kamu berhak modifikasi. Aplikasi ini tidak membobol
  proteksi lisensi perangkat lunak lain dan bukan salinan Adobe Acrobat.
