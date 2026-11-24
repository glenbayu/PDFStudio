"""Export PDF documents to plain text (.txt) and native Word (.docx, OOXML)."""
from __future__ import annotations

import os
import re
import zipfile
from xml.sax.saxutils import escape

import pymupdf as fitz

from core.pdfdoc import _page_paragraphs, _span_bold, _span_italic, span_color

_XML_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_xml(text: str) -> str:
    return escape(_XML_ILLEGAL_RE.sub("", text or ""))


def _rgb_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, int(round(c * 255)))) for c in rgb[:3])
    return f"{r:02X}{g:02X}{b:02X}"


def export_text(pdf_doc, out_path: str, pages: list[int] | None = None,
                progress=None) -> int:
    """Export selected (or all) pages of *pdf_doc* to a UTF-8 .txt file."""
    doc = pdf_doc.require()
    targets = list(range(doc.page_count)) if pages is None else [
        p for p in pages if 0 <= p < doc.page_count
    ]
    chunks: list[str] = []
    total = len(targets)
    for idx, pno in enumerate(targets):
        if progress and not progress(idx, total, pno):
            break
        txt = (doc[pno].get_text("text") or "").strip()
        if total > 1:
            chunks.append(f"=== Halaman {pno + 1} ===\n{txt}")
        else:
            chunks.append(txt)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(chunks) + "\n")
    return len(chunks)


_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpeg" ContentType="image/jpeg"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

_ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""


def _drawing_xml(rid: str, docpr_id: int, cx_emu: int, cy_emu: int, name: str) -> str:
    return (
        "<w:p><w:r><w:drawing>"
        '<wp:inline distT="0" distB="0" distL="0" distR="0"'
        ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{cx_emu}" cy="{cy_emu}"/>'
        f'<wp:docPr id="{docpr_id}" name="{_clean_xml(name)}"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:nvPicPr>"
        f'<pic:cNvPr id="{docpr_id}" name="{_clean_xml(name)}"/>'
        "<pic:cNvPicPr/>"
        "</pic:nvPicPr>"
        "<pic:blipFill>"
        f'<a:blip r:embed="{rid}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        "<a:stretch><a:fillRect/></a:stretch>"
        "</pic:blipFill>"
        "<pic:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx_emu}" cy="{cy_emu}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr>"
        "</pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def _group_to_docx_p(group: list[dict], page_w: float) -> str:
    rects = [ln["rect"] for ln in group]
    x0 = min(r[0] for r in rects)
    x1 = max(r[2] for r in rects)
    indent = max(0.0, float(rects[0][0]) - x0) if len(group) >= 2 else 0.0

    jc = "left"
    if len(group) >= 2 and (x1 - x0) >= 160.0:
        body = rects[:-1]
        if sum(1 for r in body if abs(r[2] - x1) <= 6.0) >= max(1, len(body) - 1):
            jc = "both"
    elif len(group) == 1 and page_w > 0:
        mid = (x0 + x1) / 2.0
        if abs(mid - page_w / 2.0) <= 22.0 and (x1 - x0) < page_w * 0.72:
            jc = "center"
        elif x0 > page_w * 0.52 and (page_w - x1) <= 105.0:
            jc = "right"

    ppr_parts = [f'<w:jc w:val="{jc}"/>', '<w:spacing w:after="120"/>']
    if indent > 2.0:
        ppr_parts.append(f'<w:ind w:firstLine="{int(round(indent * 20))}"/>')
    ppr = "<w:pPr>" + "".join(ppr_parts) + "</w:pPr>"

    runs_xml: list[str] = []
    for li, ln in enumerate(group):
        if li > 0:
            prev_t = group[li - 1]["text"].rstrip()
            cur_t = ln["text"].lstrip()
            if not (prev_t.endswith("-") or cur_t[:1] in ".,;:)]}"):
                runs_xml.append('<w:r><w:t xml:space="preserve"> </w:t></w:r>')
        for sp in ln["spans"]:
            t = sp.get("text") or ""
            if not t:
                continue
            sz_half = max(12, int(round(float(sp.get("size") or 10.0) * 2)))
            bold = _span_bold(sp)
            italic = _span_italic(sp)
            col = _rgb_hex(span_color(sp))
            rpr = [f'<w:sz w:val="{sz_half}"/>', f'<w:szCs w:val="{sz_half}"/>']
            if bold:
                rpr.append("<w:b/>")
            if italic:
                rpr.append("<w:i/>")
            if col != "000000":
                rpr.append(f'<w:color w:val="{col}"/>')
            runs_xml.append(
                "<w:r><w:rPr>" + "".join(rpr) + "</w:rPr>"
                f'<w:t xml:space="preserve">{_clean_xml(t)}</w:t></w:r>'
            )
    return "<w:p>" + ppr + "".join(runs_xml) + "</w:p>"


def export_docx(pdf_doc, out_path: str, pages: list[int] | None = None,
                include_images: bool = True, progress=None) -> int:
    """Export selected (or all) pages of *pdf_doc* into a valid Word .docx file."""
    doc = pdf_doc.require()
    targets = list(range(doc.page_count)) if pages is None else [
        p for p in pages if 0 <= p < doc.page_count
    ]
    body_items: list[str] = []
    media_files: list[tuple[str, bytes]] = []
    rels_xml: list[str] = []
    img_counter = 0
    total = len(targets)

    for idx, pno in enumerate(targets):
        if progress and not progress(idx, total, pno):
            break
        page = doc[pno]
        if idx > 0:
            body_items.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        page_w = float(page.rect.width)
        data = page.get_text("dict")
        groups = _page_paragraphs(data)

        # Interleave paragraphs & images in vertical reading order
        elements: list[tuple[float, str]] = []
        for g in groups:
            y0 = min(ln["rect"][1] for ln in g)
            elements.append((y0, _group_to_docx_p(g, page_w)))

        if include_images:
            seen_rects: set[tuple[int, int, int, int]] = set()
            for info in page.get_image_info(xrefs=True) or []:
                xref = info.get("xref") or 0
                bbox = info.get("bbox")
                if not xref or not bbox:
                    continue
                r = fitz.Rect(bbox)
                if r.width < 12 or r.height < 12:
                    continue
                rkey = (int(r.x0), int(r.y0), int(r.x1), int(r.y1))
                if rkey in seen_rects:
                    continue
                seen_rects.add(rkey)
                try:
                    extracted = doc.extract_image(xref)
                    raw = extracted.get("image")
                    ext = (extracted.get("ext") or "png").lower()
                    if not raw:
                        continue
                    if ext not in ("png", "jpg", "jpeg"):
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n - pix.alpha > 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        raw = pix.tobytes("png")
                        ext = "png"
                except Exception:
                    continue
                img_counter += 1
                rid = f"rIdImg{img_counter}"
                fname = f"image{img_counter}.{ext}"
                media_files.append((f"word/media/{fname}", raw))
                rels_xml.append(
                    f'<Relationship Id="{rid}" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                    f'Target="media/{fname}"/>'
                )
                # Cap width at ~6.2 inches (446 pt) so images fit Word margins
                w_pt = min(float(r.width), 446.0)
                scale = w_pt / max(1.0, float(r.width))
                h_pt = min(float(r.height) * scale, 620.0)
                cx_emu = max(91440, int(round(w_pt * 12700)))
                cy_emu = max(91440, int(round(h_pt * 12700)))
                elements.append((float(r.y0), _drawing_xml(rid, img_counter, cx_emu, cy_emu, fname)))

        elements.sort(key=lambda e: e[0])
        for _y, xml_frag in elements:
            body_items.append(xml_frag)

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:body>"
        + "".join(body_items)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>"
    )
    doc_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels_xml)
        + "</Relationships>"
    )

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", _ROOT_RELS_XML)
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("word/_rels/document.xml.rels", doc_rels_xml)
        for mpath, mbytes in media_files:
            zf.writestr(mpath, mbytes)
    return len(targets)
