"""Génère des fichiers Word (.docx) et PDF à partir de texte Markdown."""
import io
import re
import unicodedata

INLINE_RE = re.compile(r"(\*\*.+?\*\*|\*.+?\*|`.+?`)")


# ---------- analyse du Markdown ----------
def parse_blocks(md: str) -> list[tuple]:
    """Retourne une liste de blocs : ("h", niveau, texte), ("p", texte), ("ul", [..]),
    ("ol", [..]), ("table", [[cellules]]), ("hr",)."""
    blocks: list[tuple] = []
    lines = md.replace("\r", "").split("\n")
    para: list[str] = []

    def flush():
        if para:
            blocks.append(("p", "\n".join(para)))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("#"):
            flush()
            level = len(s) - len(s.lstrip("#"))
            blocks.append(("h", min(level, 4), s[level:].strip()))
        elif re.fullmatch(r"[-*_]{3,}", s):
            flush()
            blocks.append(("hr",))
        elif re.match(r"^[-*•]\s+", s):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*[-*•]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*•]\s+", "", lines[i]).strip())
                i += 1
            blocks.append(("ul", items))
            continue
        elif re.match(r"^\d+[.)]\s+", s):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]).strip())
                i += 1
            blocks.append(("ol", items))
            continue
        elif s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(("table", rows))
            continue
        else:
            para.append(s)
        i += 1
    flush()
    return blocks


def slug(md: str) -> str:
    """Nom de fichier tiré du premier titre du document."""
    m = re.search(r"^#+\s*(.+)$", md, re.MULTILINE) or re.search(r"\S.*", md)
    title = m.group(1) if m and m.groups() else (m.group(0) if m else "document")
    title = re.sub(r"[*_`]", "", title)
    ascii_ = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return (re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:50]) or "document"


# ---------- Word ----------
def _docx_runs(par, text: str):
    for part in INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            par.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            par.add_run(part[1:-1]).font.name = "Consolas"
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            par.add_run(part[1:-1]).italic = True
        else:
            par.add_run(part)


def _docx_lines(par, text: str):
    for n, line in enumerate(text.split("\n")):
        if n:
            par.add_run().add_break()
        _docx_runs(par, line)


def make_docx(md: str, path):
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Cm(2.2)
        sec.top_margin = sec.bottom_margin = Cm(2)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    for name, size in (("Heading 1", 20), ("Heading 2", 15), ("Heading 3", 13), ("Heading 4", 11)):
        st = doc.styles[name]
        st.font.name = "Calibri"
        st.font.size = Pt(size)
        st.font.color.rgb = RGBColor(0x1F, 0x3A, 0x6E)

    for b in parse_blocks(md):
        kind = b[0]
        if kind == "h":
            h = doc.add_heading(level=b[1])
            _docx_runs(h, b[2])
        elif kind == "p":
            _docx_lines(doc.add_paragraph(), b[1])
        elif kind in ("ul", "ol"):
            style = "List Bullet" if kind == "ul" else "List Number"
            for item in b[1]:
                _docx_runs(doc.add_paragraph(style=style), item)
        elif kind == "table":
            rows = b[1]
            ncols = max(len(r) for r in rows)
            t = doc.add_table(rows=len(rows), cols=ncols)
            t.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci in range(ncols):
                    cell = t.cell(ri, ci)
                    par = cell.paragraphs[0]
                    _docx_runs(par, row[ci] if ci < len(row) else "")
                    if ri == 0:
                        for r in par.runs:
                            r.bold = True
                        tcPr = cell._tc.get_or_add_tcPr()
                        shd = OxmlElement("w:shd")
                        shd.set(qn("w:val"), "clear")
                        shd.set(qn("w:fill"), "DCE6F5")
                        tcPr.append(shd)
            doc.add_paragraph()
        elif kind == "hr":
            par = doc.add_paragraph()
            pPr = par._p.get_or_add_pPr()
            borders = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "999999")):
                bottom.set(qn(k), v)
            borders.append(bottom)
            pPr.append(borders)
    doc.save(path)


# ---------- PDF ----------
_PDF_MAP = str.maketrans(
    {" ": " ", " ": " ", "‑": "-", "→": "->", "•": "-", "✓": "v", "✔": "v"}
)


def _pdf_safe(s: str) -> str:
    # Polices PDF standard = jeu cp1252 (accents français, €, guillemets OK ; pas d'emojis)
    return s.translate(_PDF_MAP).encode("cp1252", "ignore").decode("cp1252")


def _pdf_inline(text: str) -> str:
    out = []
    for part in INLINE_RE.split(text):
        if not part:
            continue
        esc = _pdf_safe(part).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append("<b>" + _pdf_safe(part[2:-2]).replace("&", "&amp;").replace("<", "&lt;") + "</b>")
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append("<font name='Courier'>" + _pdf_safe(part[1:-1]).replace("&", "&amp;").replace("<", "&lt;") + "</font>")
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append("<i>" + _pdf_safe(part[1:-1]).replace("&", "&amp;").replace("<", "&lt;") + "</i>")
        else:
            out.append(esc)
    return "".join(out).replace("\n", "<br/>")


def make_pdf(md: str, path):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    navy = colors.HexColor("#1F3A6E")
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=15, spaceAfter=7, alignment=TA_LEFT)
    heads = {
        1: ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=25, textColor=navy, spaceBefore=4, spaceAfter=10),
        2: ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=14.5, leading=19, textColor=navy, spaceBefore=12, spaceAfter=6),
        3: ParagraphStyle("h3", parent=body, fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=navy, spaceBefore=8, spaceAfter=4),
        4: ParagraphStyle("h4", parent=body, fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=3),
    }
    cell = ParagraphStyle("cell", parent=body, fontSize=9.5, leading=12, spaceAfter=0)
    cell_b = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")

    story = []
    for b in parse_blocks(md):
        kind = b[0]
        if kind == "h":
            story.append(Paragraph(_pdf_inline(b[2]), heads[b[1]]))
        elif kind == "p":
            story.append(Paragraph(_pdf_inline(b[1]), body))
        elif kind in ("ul", "ol"):
            items = [ListItem(Paragraph(_pdf_inline(t), body), leftIndent=14) for t in b[1]]
            story.append(
                ListFlowable(items, bulletType="bullet" if kind == "ul" else "1", start="-" if kind == "ul" else 1, leftIndent=16)
            )
            story.append(Spacer(1, 4))
        elif kind == "table":
            rows = b[1]
            ncols = max(len(r) for r in rows)
            data = [
                [Paragraph(_pdf_inline(r[c] if c < len(r) else ""), cell_b if ri == 0 else cell) for c in range(ncols)]
                for ri, r in enumerate(rows)
            ]
            t = Table(data, repeatRows=1, colWidths=[(A4[0] - 4.4 * cm) / ncols] * ncols)
            t.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F5")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story += [t, Spacer(1, 10)]
        elif kind == "hr":
            story.append(HRFlowable(width="100%", color=colors.HexColor("#999999"), spaceBefore=4, spaceAfter=8))

    SimpleDocTemplate(
        path, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
    ).build(story or [Paragraph("(document vide)", body)])


def render(fmt: str, md: str) -> tuple[str, bytes]:
    """Crée le document en mémoire (fmt = 'docx' ou 'pdf'). Retourne (nom de fichier, octets)."""
    buf = io.BytesIO()
    (make_docx if fmt == "docx" else make_pdf)(md, buf)
    return f"{slug(md)}.{fmt}", buf.getvalue()
