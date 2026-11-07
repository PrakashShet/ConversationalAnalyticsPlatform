"""Repair and improve a pandoc-generated .docx.

Two fixes, both things pandoc 2.9 will not do itself:

**Table widths.** Pandoc emits ``<w:tblGrid/>`` empty and ``<w:tblW w:w="0.0"
w:type="pct"/>`` for a pipe table that carries no explicit column widths. Word
is forgiving; LibreOffice is not, and renders every row as a single stacked
column. OOXML wants widths in two places — a ``<w:gridCol>`` per column *and* a
``<w:tcW>`` per cell — so both are written here, sized from the content.

**Landscape figure pages.** A diagram that is naturally 12 inches wide is
unreadable squeezed into a 6.8-inch column. Such figures are put on their own
landscape page by bracketing them with section breaks: in OOXML a ``<w:sectPr>``
inside a paragraph ends the section *at* that paragraph, so a portrait break
before the figure and a landscape break after it produce a single rotated page.

Operates on the unzipped XML as text. It deliberately does not re-indent or
re-serialise: whitespace between run elements is significant.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

TWIPS_PER_INCH = 1440

# Letter, from the reference document.
PAGE_W, PAGE_H = 12240, 15840


def _cell_texts(row_xml: str) -> list[str]:
    cells = re.findall(r"<w:tc>(.*?)</w:tc>", row_xml, re.S)
    return ["".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", c, re.S)) for c in cells]


def _column_widths(table_xml: str, total: int) -> list[int]:
    """Proportional widths from the longest cell in each column."""
    rows = re.findall(r"<w:tr[ >].*?</w:tr>", table_xml, re.S)
    if not rows:
        return []
    n = len(re.findall(r"<w:tc>", rows[0]))
    if n == 0:
        return []

    longest = [1] * n
    for row in rows:
        for i, text in enumerate(_cell_texts(row)[:n]):
            # Long prose wraps over several lines anyway, so damp its influence;
            # otherwise one discursive cell starves the rest of the row.
            longest[i] = max(longest[i], min(len(text), 40))

    # Mostly proportional, with a little equalisation so a narrow column keeps
    # a usable minimum. Numeric columns need far less room than they claim from
    # their header alone.
    equal = total / n
    measured = [total * w / sum(longest) for w in longest]
    floor = int(0.62 * TWIPS_PER_INCH)
    widths = [max(floor, int(0.82 * m + 0.18 * equal)) for m in measured]

    over = sum(widths) - total
    if over > 0:                               # trim the widest columns back
        for _ in range(over):
            i = max(range(n), key=lambda j: widths[j])
            if widths[i] <= floor:
                break
            widths[i] -= 1
    widths[-1] += total - sum(widths)          # absorb rounding
    return widths


def fix_tables(xml: str, usable_twips: int) -> tuple[str, int]:
    """Give every table a real grid and every cell an explicit width."""
    fixed = 0

    def repl(match: re.Match) -> str:
        nonlocal fixed
        table = match.group(0)
        widths = _column_widths(table, usable_twips)
        if not widths:
            return table
        fixed += 1

        grid = "<w:tblGrid>" + "".join(
            f'<w:gridCol w:w="{w}" />' for w in widths
        ) + "</w:tblGrid>"
        table = table.replace("<w:tblGrid />", grid, 1)
        table = re.sub(
            r'<w:tblW[^>]*/>',
            f'<w:tblW w:type="dxa" w:w="{sum(widths)}" />',
            table, count=1,
        )
        if "<w:tblW" not in table:
            table = table.replace(
                "<w:tblPr>", f'<w:tblPr><w:tblW w:type="dxa" w:w="{sum(widths)}" />', 1
            )

        # Per-cell widths, column index resets on every row.
        out, col = [], 0
        for piece in re.split(r"(<w:tc>|</w:tr>)", table):
            if piece == "<w:tc>":
                out.append(piece)
                col += 1
                continue
            if piece == "</w:tr>":
                col = 0
                out.append(piece)
                continue
            if col and out and out[-1] == "<w:tc>":
                w = widths[min(col, len(widths)) - 1]
                tcw = f'<w:tcW w:type="dxa" w:w="{w}" />'
                if piece.startswith("<w:tcPr>"):
                    piece = piece.replace("<w:tcPr>", f"<w:tcPr>{tcw}", 1)
                else:
                    piece = f"<w:tcPr>{tcw}</w:tcPr>" + piece
            out.append(piece)
        return "".join(out)

    return re.sub(r"<w:tbl>.*?</w:tbl>", repl, xml, flags=re.S), fixed


MARGIN = 1224          # 0.85in — usable 6.8in portrait, 9.3in landscape


def _sect_props(landscape: bool) -> str:
    """Section properties for one orientation.

    Pandoc 2.9 emits no ``<w:sectPr>`` at all — it leaves the consumer to apply
    defaults — so there is nothing to clone and these are written from scratch.
    """
    w, h = (PAGE_H, PAGE_W) if landscape else (PAGE_W, PAGE_H)
    orient = ' w:orient="landscape"' if landscape else ""
    return (
        "<w:sectPr>"
        f'<w:pgSz w:w="{w}" w:h="{h}"{orient} />'
        f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" '
        f'w:left="{MARGIN}" w:header="720" w:footer="720" w:gutter="0" />'
        '<w:cols w:space="720" />'
        '<w:docGrid w:linePitch="360" />'
        "</w:sectPr>"
    )


def landscape_figures(xml: str, indices: set[int]) -> tuple[str, int]:
    """Put the given (0-based) figures on their own landscape page.

    Figures are counted in document order, which matches the order the source
    Markdown declared them. A ``<w:sectPr>`` inside a paragraph terminates the
    section *at* that paragraph, so a portrait break before the figure and a
    landscape break after it isolate it on one rotated page.
    """
    portrait = _sect_props(landscape=False)
    landscape = _sect_props(landscape=True)

    # Ensure the document ends in a portrait section; without a final sectPr the
    # trailing content would inherit the landscape one we are about to insert.
    if "<w:sectPr" not in xml:
        xml = xml.replace("</w:body>", f"{portrait}</w:body>", 1)
    if not indices:
        return xml, 0

    p_break = f"<w:p><w:pPr>{portrait}</w:pPr></w:p>"
    l_break = f"<w:p><w:pPr>{landscape}</w:pPr></w:p>"

    # Walk paragraphs by position so the figure and its caption can be moved
    # into the landscape section together — a caption stranded on the following
    # portrait page is worse than no caption.
    para_re = re.compile(r"<w:p\b.*?</w:p>|<w:p\b[^>]*/>", re.S)
    seen = -1
    applied = 0
    cursor = 0
    while True:
        m = para_re.search(xml, cursor)
        if not m:
            break
        para = m.group(0)
        if "<w:drawing>" not in para:
            cursor = m.end()
            continue
        seen += 1
        if seen not in indices:
            cursor = m.end()
            continue

        end = m.end()
        nxt = para_re.search(xml, end)
        if nxt and "Figure" in "".join(
            re.findall(r"<w:t[^>]*>(.*?)</w:t>", nxt.group(0), re.S)
        ):
            end = nxt.end()

        block = xml[m.start():end]
        xml = xml[:m.start()] + p_break + block + l_break + xml[end:]
        cursor = m.start() + len(p_break) + len(block) + len(l_break)
        applied += 1
    return xml, applied


def process(path: Path, landscape_indices: set[int] | None = None,
            usable_inches: float = 6.8) -> dict:
    """Rewrite ``path`` in place. Returns a small report."""
    work = path.parent / f"_unpack_{path.stem}"
    if work.exists():
        shutil.rmtree(work)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        z.extractall(work)
    for link in work.rglob("*"):
        if link.is_symlink():
            link.unlink()

    doc = work / "word" / "document.xml"
    xml = doc.read_text(encoding="utf-8")

    xml, tables = fix_tables(xml, int(usable_inches * TWIPS_PER_INCH))
    xml, rotated = landscape_figures(xml, landscape_indices or set())
    doc.write_text(xml, encoding="utf-8")

    path.unlink()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:                     # preserve original entry order
            f = work / name
            if f.is_file():
                z.write(f, name)
    shutil.rmtree(work)
    return {"tables": tables, "landscape": rotated}
