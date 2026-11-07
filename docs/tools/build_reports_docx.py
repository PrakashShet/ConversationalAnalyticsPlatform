"""Build the forecasting report series as Word documents.

    python docs/tools/build_reports_docx.py

Pipeline: for each Markdown report, every ```mermaid block is rendered to PNG
by ``mermaid_render`` and replaced with a numbered, captioned figure; the result
is handed to pandoc, which turns the LaTeX between ``$…$`` into **native Word
equations** (OMML) rather than pictures, so they stay selectable and editable.

Figures are drawn at their final print size — see ``FIGURES`` below. A diagram
squeezed from its natural 20 inches into a 7-inch column has 3pt text and is
useless on paper, so wide chains are re-laid out vertically and genuinely wide
diagrams are drawn for a landscape page.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import docx_postprocess as post  # noqa: E402
import mermaid_render as mr  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "reports" / "forecasting"
OUT = SRC / "docx"
FIGDIR = OUT / "figures"

PORTRAIT_IN = 6.8          # Letter, 0.9in margins
LANDSCAPE_IN = 8.9      # Letter landscape less 1in margins
DPI = 200

# Per-figure layout. Chosen by measuring the rendered size against the column
# it has to fit: `rankdir` flips a chain that is wide on screen to tall on the
# page, `compact` tightens spacing for dense graphs, `wide` means the figure is
# drawn for a landscape page.
#   key: "<report stem>-<1-based block index>"
FIGURES: dict[str, dict] = {
    "01-architecture-1": dict(width_in=LANDSCAPE_IN, fontsize=8.0, wide=True,
                              caption="Forecasting in the request pipeline"),
    "01-architecture-2": dict(rankdir="LR", fontsize=10, compact=True,
                              width_in=LANDSCAPE_IN, wide=True,
                              caption="Module structure of the forecasting subsystem"),
    "01-architecture-3": dict(rankdir="TB", fontsize=10,
                              caption="Data flow and object lifecycle"),
    "01-architecture-4": dict(fontsize=10,
                              caption="Concurrency: where forecasts are computed"),
    "01-architecture-5": dict(fontsize=10,
                              caption="Failure containment in the predictive layer"),
    "02-method-reference-1": dict(fontsize=10, compact=True,
                                  caption="Method selection by series characteristics"),
    "03-relevance-gate-1": dict(fontsize=10,
                                caption="The detection procedure"),
    "03-relevance-gate-2": dict(rankdir="TB", fontsize=10,
                                caption="Frequency inference"),
    "04-parameter-selection-1": dict(fontsize=10, compact=True,
                                     caption="Method eligibility rules"),
    "04-parameter-selection-2": dict(width_in=PORTRAIT_IN, fontsize=8.0,
                                     caption="Recomputation after a parameter change"),
    "05-backtesting-1": dict(rankdir="TB", fontsize=10,
                             caption="Holdout construction"),
    "05-backtesting-2": dict(fontsize=10,
                             caption="Automatic method selection"),
}

MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)


def _render_figures(stem: str, text: str) -> tuple[str, set[int]]:
    """Replace each mermaid block with an image reference.

    Returns the rewritten Markdown and the 0-based indices of figures that
    need a landscape page.
    """
    wide_indices: set[int] = set()
    counter = 0

    def repl(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        key = f"{stem}-{counter}"
        cfg = dict(FIGURES.get(key, {}))
        caption = cfg.pop("caption", "")
        wide = cfg.pop("wide", False)
        cfg.setdefault("width_in", PORTRAIT_IN)
        cfg.setdefault("fontsize", 10)

        png = FIGDIR / f"{key}.png"
        mr.render(match.group(1), png, dpi=DPI, **cfg)

        from PIL import Image
        natural_in = Image.open(png).size[0] / DPI
        limit = LANDSCAPE_IN if wide else PORTRAIT_IN
        shown = min(natural_in, limit)

        if wide:
            wide_indices.add(counter - 1)
        label = f"**Figure {counter}.** {caption}" if caption else ""
        # pandoc honours the {width=...} attribute on an image.
        img = f'![]({png.as_posix()}){{width={shown:.2f}in}}'
        return f"\n{img}\n\n{label}\n"

    return MERMAID.sub(repl, text), wide_indices


def _preprocess(md: Path) -> tuple[str, set[int]]:
    text = md.read_text(encoding="utf-8")
    text, wide = _render_figures(md.stem, text)

    # The series cross-links point at .md siblings; in Word they should name the
    # document instead of pretending to be a working hyperlink.
    text = re.sub(r"\[([^\]]+)\]\((\d\d-[a-z-]+)\.md(#[^)]*)?\)", r"*\1*", text)
    text = re.sub(r"\[([^\]]+)\]\((?:\.\./)+[^)]+\)", r"*\1*", text)

    # Drop the in-document series footer table: a printed report gets a proper
    # cover and the reader has the whole folder anyway.
    text = re.sub(r"\n## Report series\n.*?(?=\n### References|\Z)", "\n", text, flags=re.S)
    return text, wide


def _build_reference_docx(path: Path) -> None:
    """A pandoc reference document, restyled for a technical report."""
    subprocess.run(["pandoc", "-o", str(path), "--print-default-data-file",
                    "reference.docx"], check=True, stdout=subprocess.DEVNULL)
    import zipfile
    tmp = path.parent / "_ref"
    if tmp.exists():
        shutil.rmtree(tmp)
    with zipfile.ZipFile(path) as z:
        z.extractall(tmp)

    styles = tmp / "word" / "styles.xml"
    xml = styles.read_text(encoding="utf-8")
    # Serif body for readability in print; keep headings on the sans face.
    xml = xml.replace('w:ascii="Calibri" w:hAnsi="Calibri"',
                      'w:ascii="Georgia" w:hAnsi="Georgia"')
    styles.write_text(xml, encoding="utf-8")

    path.unlink()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(tmp.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(tmp).as_posix())
    shutil.rmtree(tmp)


TITLES = {
    "01-architecture": "Forecasting Architecture",
    "02-method-reference": "Method Reference",
    "03-relevance-gate": "The Relevance Gate",
    "04-parameter-selection": "Parameter Selection",
    "05-backtesting": "Backtesting and Accuracy",
    "README": "Forecasting — Technical Report Series",
}


def build() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    FIGDIR.mkdir(parents=True, exist_ok=True)
    reference = OUT / "_reference.docx"
    _build_reference_docx(reference)

    built: list[Path] = []
    for md in sorted(SRC.glob("*.md")):
        stem = md.stem
        processed, wide = _preprocess(md)
        title = TITLES.get(stem, stem)

        meta = (
            "---\n"
            f'title: "{title}"\n'
            'subtitle: "AI-Powered Conversational Analytics Platform"\n'
            'author: "Technical report series on the predictive-analytics subsystem"\n'
            "---\n\n"
        )
        staged = OUT / f"_{stem}.md"
        staged.write_text(meta + processed, encoding="utf-8")

        target = OUT / f"{stem}.docx"
        subprocess.run(
            ["pandoc", str(staged),
             "-f", "markdown+tex_math_dollars+pipe_tables+grid_tables",
             "-t", "docx", "-o", str(target),
             "--reference-doc", str(reference),
             "--toc", "--toc-depth=2",
             "-V", "papersize=letter",
             "--resource-path", str(SRC)],
            check=True,
        )
        staged.unlink()
        report = post.process(target, landscape_indices=wide,
                              usable_inches=PORTRAIT_IN)
        built.append(target)
        print(f"  built {target.relative_to(ROOT)}  "
              f"(tables fixed: {report['tables']}, landscape figures: {report['landscape']})")

    reference.unlink(missing_ok=True)
    return built


if __name__ == "__main__":
    print(f"Rendering figures into {FIGDIR.relative_to(ROOT)} …")
    files = build()
    print(f"\n{len(files)} documents written to {OUT.relative_to(ROOT)}")
