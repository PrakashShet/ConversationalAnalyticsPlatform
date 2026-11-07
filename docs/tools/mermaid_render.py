"""Render the Mermaid diagrams used in the docs to PNG, without a browser.

Mermaid's own CLI needs Node plus a headless Chromium. That is a heavy and
network-dependent dependency for a docs build, so this module re-draws the
*subset of Mermaid actually used in this repository* with tools that are already
present: Graphviz for graphs/flowcharts/state diagrams, and matplotlib for
sequence diagrams.

It is deliberately **not** a general Mermaid implementation. It supports:

* ``graph TB|TD|LR`` and ``flowchart TB|TD|LR`` — boxes, stadiums, cylinders,
  diamonds, hexagons, subgraphs, edge labels, dotted and bidirectional edges,
  ``A & B --> C`` fan-out, and ``style`` directives;
* ``stateDiagram-v2`` — states, transitions, composite states, notes;
* ``sequenceDiagram`` — participants, sync/async arrows, self-calls, notes,
  ``rect`` highlight bands and ``alt``/``else`` blocks.

Anything outside that raises, loudly, rather than silently producing a wrong
picture.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

# --- palette (matches the light theme used across the docs) -----------------

INK = "#0f172a"
MUTED = "#64748b"
LINE = "#94a3b8"
SURFACE = "#ffffff"
BAND = "#f8fafc"
ACCENT = "#6366f1"
GOOD = "#059669"
GOOD_BG = "#d9ffe0"
STOP_BG = "#f1f5f9"
FONT = "Helvetica"

# Fill colours for the subgraph tints used in the reports.
SUBGRAPH_TINTS = ["#eef2ff", "#ecfdf5", "#fff7ed", "#f1f5f9", "#fef2f2", "#f0fdfa"]


class UnsupportedDiagram(RuntimeError):
    """Raised for Mermaid syntax this renderer does not implement."""


# --- shared helpers ---------------------------------------------------------

_LABEL_BREAK = re.compile(r"<br\s*/?>", re.I)


def _clean(label: str) -> str:
    """Mermaid label -> plain text with real newlines."""
    label = label.strip().strip('"')
    label = _LABEL_BREAK.sub("\n", label)
    label = label.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return label


def _wrap(text: str, width: int = 26) -> str:
    """Wrap on whitespace only.

    Identifiers are the whole point of these labels, so ``detect_time_series()``
    must never come out as ``detect_time_serie`` / ``s()``. A long token is
    allowed to overrun the nominal width instead.
    """
    out = []
    for line in text.split("\n"):
        out.extend(
            textwrap.wrap(line, width, break_long_words=False,
                          break_on_hyphens=False) or [""]
        )
    return "\n".join(out)


# --- graph / flowchart / state -> Graphviz ----------------------------------

# Node declarations, longest delimiters first so [( and {{ win over [ and {.
_NODE_PATTERNS = [
    (re.compile(r'^(\w+)\[\("(.*?)"\)\]$', re.S), "cylinder"),
    (re.compile(r"^(\w+)\[\((.*?)\)\]$", re.S), "cylinder"),
    (re.compile(r'^(\w+)\{\{"(.*?)"\}\}$', re.S), "hexagon"),
    (re.compile(r'^(\w+)\(\["(.*?)"\]\)$', re.S), "stadium"),
    (re.compile(r"^(\w+)\(\[(.*?)\]\)$", re.S), "stadium"),
    (re.compile(r'^(\w+)\{"(.*?)"\}$', re.S), "diamond"),
    (re.compile(r"^(\w+)\{(.*?)\}$", re.S), "diamond"),
    (re.compile(r'^(\w+)\["(.*?)"\]$', re.S), "box"),
    (re.compile(r"^(\w+)\[(.*?)\]$", re.S), "box"),
]

_SHAPE_ATTRS = {
    "box": dict(shape="box", style="filled,rounded", penwidth="1.2"),
    "stadium": dict(shape="box", style="filled,rounded", penwidth="1.6"),
    "cylinder": dict(shape="cylinder", style="filled", penwidth="1.2"),
    "diamond": dict(shape="diamond", style="filled", penwidth="1.2"),
    "hexagon": dict(shape="hexagon", style="filled", penwidth="1.2"),
}

# One edge statement, possibly with a |label| and multiple endpoints per side.
_EDGE = re.compile(
    r"^(?P<src>[\w&\s]+?)\s*"
    r"(?P<arrow><-->|-\.->|-\.-|-->|---)"
    r"\s*(?:\|(?P<label>[^|]*)\|)?\s*"
    r"(?P<dst>[\w&\s]+?)$"
)
_STYLE = re.compile(r"^style\s+(\w+)\s+(.*)$")
_SUBGRAPH = re.compile(r'^subgraph\s+(\w+)\s*\["?(.*?)"?\]\s*$')
_SUBGRAPH_PLAIN = re.compile(r"^subgraph\s+(.+?)\s*$")


def _parse_style(spec: str) -> dict:
    out = {}
    for part in spec.split(","):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        key, value = key.strip(), value.strip()
        if key == "fill":
            out["fillcolor"] = value
        elif key == "stroke":
            out["color"] = value
    return out


def _graph_to_dot(body: str, kind: str, rankdir: str | None = None,
                  fontsize: float = 11.0, compact: bool = False) -> str:
    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%%")]

    header = lines[0]
    direction = "TB"
    m = re.match(r"^(?:graph|flowchart)\s+(TB|TD|LR|RL|BT)\b", header)
    if m:
        direction = "TB" if m.group(1) == "TD" else m.group(1)
    if rankdir:                       # print override: a chain that is wide on
        direction = rankdir           # screen is better tall on a page
    lines = lines[1:]

    nodes: dict[str, tuple[str, str]] = {}      # id -> (label, shape)
    order: list[str] = []
    edges: list[tuple[str, str, str, str]] = []  # src, dst, label, arrow
    styles: dict[str, dict] = {}
    clusters: list[tuple[str, str, list[str]]] = []
    stack: list[tuple[str, str, list[str]]] = []

    def note(node_id: str, label: str = "", shape: str = "box") -> None:
        if node_id not in nodes:
            nodes[node_id] = (label or node_id, shape)
            order.append(node_id)
        elif label:
            nodes[node_id] = (label, shape)
        if stack and node_id not in stack[-1][2]:
            stack[-1][2].append(node_id)

    def declare(token: str) -> str:
        token = token.strip()
        for pattern, shape in _NODE_PATTERNS:
            m = pattern.match(token)
            if m:
                note(m.group(1), _clean(m.group(2)), shape)
                return m.group(1)
        if not re.fullmatch(r"\w+", token):
            raise UnsupportedDiagram(f"cannot parse node token: {token!r}")
        note(token)
        return token

    for raw in lines:
        if raw == "end":
            if stack:
                clusters.append(stack.pop())
            continue
        m = _SUBGRAPH.match(raw) or _SUBGRAPH_PLAIN.match(raw)
        if raw.startswith("subgraph") and m:
            gid = m.group(1)
            title = _clean(m.group(2)) if m.lastindex and m.lastindex >= 2 else gid
            stack.append((gid, title, []))
            continue
        m = _STYLE.match(raw)
        if m:
            styles[m.group(1)] = _parse_style(m.group(2))
            continue

        # Chained edges: A --> B --> C
        segments = re.split(r"(<-->|-\.->|-\.-|-->|---)", raw)
        if len(segments) >= 3:
            parts, i = [segments[0]], 1
            while i < len(segments) - 1:
                parts.append((segments[i], segments[i + 1]))
                i += 2
            prev_group = [declare(t) for t in parts[0].split("&")]
            for arrow, tail in parts[1:]:
                label = ""
                lm = re.match(r"^\s*\|([^|]*)\|\s*(.*)$", tail)
                if lm:
                    label, tail = _clean(lm.group(1)), lm.group(2)
                next_group = [declare(t) for t in tail.split("&") if t.strip()]
                for a in prev_group:
                    for b in next_group:
                        edges.append((a, b, label, arrow))
                prev_group = next_group
            continue

        declare(raw)

    while stack:
        clusters.append(stack.pop())

    # --- emit DOT
    out = [
        f"digraph G {{",
        f'  rankdir={direction}; bgcolor="{SURFACE}"; compound=true;',
        f'  node [fontname="{FONT}" fontsize={fontsize} fontcolor="{INK}" '
        f'color="{LINE}" fillcolor="{BAND}" '
        f'margin="{"0.08,0.05" if compact else "0.16,0.10"}"];',
        f'  edge [fontname="{FONT}" fontsize={fontsize - 2} fontcolor="{MUTED}" '
        f'color="{LINE}" penwidth=1.1 arrowsize=0.7];',
        ("  nodesep=0.16; ranksep=0.24;" if compact
         else "  nodesep=0.32; ranksep=0.42;"),
    ]

    clustered = {n for _, _, members in clusters for n in members}
    for idx, (gid, title, members) in enumerate(clusters):
        tint = SUBGRAPH_TINTS[idx % len(SUBGRAPH_TINTS)]
        out.append(f"  subgraph cluster_{gid} {{")
        out.append(f'    label="{_wrap(title, 24 if compact else 34)}"; labeljust="l";')
        out.append(
            f'    fontname="{FONT}"; fontsize={fontsize - 1}; fontcolor="{MUTED}";'
            f' style="filled,rounded"; color="{LINE}"; fillcolor="{tint}";'
        )
        for n in members:
            out.append(f"    {_dot_node(n, nodes, styles, 17 if compact else 24)}")
        out.append("  }")

    for n in order:
        if n not in clustered:
            out.append(f"  {_dot_node(n, nodes, styles, 17 if compact else 24)}")

    for src, dst, label, arrow in edges:
        attrs = []
        if label:
            attrs.append(f'label="{_wrap(label, 22)}"')
        if arrow in ("-.->", "-.-"):
            attrs.append('style=dashed')
        if arrow == "<-->":
            attrs.append("dir=both")
        if arrow == "---":
            attrs.append("arrowhead=none")
        joined = (" [" + ", ".join(attrs) + "]") if attrs else ""
        out.append(f"  {src} -> {dst}{joined};")

    out.append("}")
    return "\n".join(out)


def _dot_node(node_id: str, nodes: dict, styles: dict, wrap: int = 24) -> str:
    label, shape = nodes[node_id]
    attrs = dict(_SHAPE_ATTRS.get(shape, _SHAPE_ATTRS["box"]))
    attrs["label"] = _wrap(label, wrap)
    if shape == "stadium":
        attrs["fillcolor"] = "#eef2ff"
        attrs["color"] = ACCENT
    attrs.update(styles.get(node_id, {}))
    rendered = ", ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f"{node_id} [{rendered}];"


# --- stateDiagram-v2 -> Graphviz --------------------------------------------

def _state_to_dot(body: str) -> str:
    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines[1:] if ln and not ln.startswith("%%")]

    out = [
        "digraph S {",
        f'  rankdir=TB; bgcolor="{SURFACE}"; compound=true;',
        f'  node [shape=box style="filled,rounded" fontname="{FONT}" fontsize=11 '
        f'fontcolor="{INK}" color="{LINE}" fillcolor="{BAND}" margin="0.16,0.10"];',
        f'  edge [fontname="{FONT}" fontsize={fontsize - 2} fontcolor="{MUTED}" '
        f'color="{LINE}" penwidth=1.1 arrowsize=0.7];',
        "  nodesep=0.3; ranksep=0.4;",
    ]
    seen_start = 0
    depth = 0
    note_buffer: list[str] = []
    in_note = False
    note_target = ""

    def nid(token: str) -> str:
        nonlocal seen_start
        if token == "[*]":
            seen_start += 1
            name = f"__start{seen_start}"
            out.append(
                f'  {name} [shape=circle width=0.16 label="" '
                f'style=filled fillcolor="{INK}" color="{INK}"];'
            )
            return name
        return token

    for raw in lines:
        if in_note:
            if raw in ("end note", "endnote"):
                in_note = False
                text = _wrap(" ".join(note_buffer), 30)
                out.append(
                    f'  note_{note_target} [shape=note fillcolor="#fffbeb" '
                    f'color="#f59e0b" fontsize=9 label="{text}"];'
                )
                out.append(
                    f"  {note_target} -> note_{note_target} "
                    f'[style=dotted arrowhead=none color="#f59e0b"];'
                )
                note_buffer = []
            else:
                note_buffer.append(raw)
            continue

        m = re.match(r"^note\s+(?:right|left)\s+of\s+(\w+)$", raw)
        if m:
            in_note, note_target = True, m.group(1)
            continue

        m = re.match(r"^state\s+(\w+)\s*\{$", raw)
        if m:
            depth += 1
            out.append(f"  subgraph cluster_{m.group(1)} {{")
            out.append(
                f'    label="{m.group(1)}"; labeljust="l"; fontname="{FONT}"; '
                f'fontsize=10; fontcolor="{MUTED}"; style="filled,rounded"; '
                f'color="{LINE}"; fillcolor="#eef2ff";'
            )
            continue
        if raw == "}" and depth:
            depth -= 1
            out.append("  }")
            continue

        m = re.match(r"^(\S+)\s*-->\s*(\S+?)\s*(?::\s*(.*))?$", raw)
        if m:
            a, b, label = nid(m.group(1)), nid(m.group(2)), m.group(3) or ""
            attrs = f' [label="{_wrap(label, 22)}"]' if label else ""
            out.append(f"  {a} -> {b}{attrs};")
            continue

    out.append("}")
    return "\n".join(out)


# --- sequenceDiagram -> matplotlib ------------------------------------------

def _render_sequence(body: str, out_path: Path, width_in: float = 7.0,
                     fontsize: float = 8.0, dpi: int = 200) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines[1:] if ln and not ln.startswith("%%")]

    actors: list[str] = []
    labels: dict[str, str] = {}
    events: list[dict] = []
    band_stack: list[dict] = []
    bands: list[dict] = []

    def actor(name: str) -> str:
        name = name.strip()
        if name not in actors:
            actors.append(name)
            labels.setdefault(name, name)
        return name

    for raw in lines:
        if raw == "autonumber":
            continue
        m = re.match(r"^participant\s+(\w+)\s+as\s+(.*)$", raw)
        if m:
            actor(m.group(1))
            labels[m.group(1)] = _clean(m.group(2))
            continue
        m = re.match(r"^participant\s+(\w+)$", raw)
        if m:
            actor(m.group(1))
            continue
        m = re.match(r"^rect\s+(.*)$", raw)
        if m:
            band_stack.append({"start": len(events), "kind": "rect"})
            continue
        m = re.match(r"^(alt|opt|loop|par)\s+(.*)$", raw)
        if m:
            band_stack.append(
                {"start": len(events), "kind": "alt", "label": _clean(m.group(2))}
            )
            continue
        if re.match(r"^else\b", raw):
            events.append({"type": "divider", "text": _clean(raw[4:].strip())})
            continue
        if raw == "end":
            if band_stack:
                band = band_stack.pop()
                band["stop"] = len(events)
                bands.append(band)
            continue
        m = re.match(r"^(?:note|Note)\s+over\s+([\w,\s]+?)\s*:\s*(.*)$", raw)
        if m:
            targets = [actor(a) for a in m.group(1).split(",")]
            events.append({"type": "note", "actors": targets, "text": _clean(m.group(2))})
            continue
        m = re.match(r"^(\w+)\s*(-->>|->>|-->|->)\s*(\w+)\s*:\s*(.*)$", raw)
        if m:
            a, arrow, b, text = actor(m.group(1)), m.group(2), actor(m.group(3)), m.group(4)
            events.append(
                {"type": "msg", "from": a, "to": b,
                 "dashed": arrow.startswith("--"), "text": _clean(text)}
            )
            continue

    # Design at final print size: the figure is exactly as wide as the space
    # it will occupy, and fonts are in real points, so nothing is scaled down
    # in the document and 8pt on the page is 8pt here.
    n_actors = max(len(actors), 1)
    col = width_in / n_actors
    row = fontsize / 72.0 * 2.9
    width = width_in
    height = 0.95 + row * max(len(events), 1)

    fig, ax = plt.subplots(figsize=(width, height))
    ax.set_xlim(0, n_actors * col)
    ax.set_ylim(0, height)
    ax.axis("off")
    fig.patch.set_facecolor(SURFACE)

    xs = {a: col * (i + 0.5) for i, a in enumerate(actors)}
    top = height - 0.42
    bottom = 0.22

    for band in bands:
        y0 = top - 0.30 - row * band["stop"] - 0.16
        y1 = top - 0.30 - row * band["start"] + 0.30
        ax.add_patch(Rectangle(
            (0.12, y0), n_actors * col - 0.24, y1 - y0,
            facecolor="#eef2ff" if band["kind"] == "rect" else "#fff7ed",
            edgecolor="#c7d2fe" if band["kind"] == "rect" else "#fed7aa",
            linewidth=0.9, zorder=0, alpha=0.75,
        ))
        if band.get("label"):
            ax.text(0.20, y1 - 0.10, band["label"], fontsize=fontsize - 0.8,
                    color=MUTED, va="top", ha="left", style="italic", zorder=1)

    for a in actors:
        x = xs[a]
        ax.plot([x, x], [bottom, top - 0.22], color=LINE, lw=0.9,
                ls=(0, (3, 3)), zorder=1)
        ax.add_patch(FancyBboxPatch(
            (x - col * 0.45, top - 0.17), col * 0.90, 0.36,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            facecolor="#eef2ff", edgecolor=ACCENT, linewidth=1.1, zorder=3,
        ))
        ax.text(x, top + 0.01, _wrap(labels[a], max(9, int(col * 13))),
                ha="center", va="center", fontsize=fontsize, color=INK,
                zorder=4, linespacing=1.1)

    y = top - 0.42
    for ev in events:
        if ev["type"] == "msg":
            x0, x1 = xs[ev["from"]], xs[ev["to"]]
            if x0 == x1:                                    # self-call
                ax.add_patch(FancyArrowPatch(
                    (x0, y + 0.06), (x0, y - 0.14),
                    connectionstyle="arc3,rad=-1.9", arrowstyle="-|>",
                    mutation_scale=9, color=INK, lw=1.0,
                    linestyle="dashed" if ev["dashed"] else "solid", zorder=4,
                ))
                ax.text(x0 + 0.34, y, _wrap(ev["text"], 30), fontsize=fontsize - 0.4,
                        color=INK, va="center", ha="left", zorder=5, linespacing=1.15)
            else:
                ax.add_patch(FancyArrowPatch(
                    (x0, y), (x1, y), arrowstyle="-|>", mutation_scale=9,
                    color=INK if not ev["dashed"] else MUTED, lw=1.0,
                    linestyle="dashed" if ev["dashed"] else "solid", zorder=4,
                ))
                ax.text((x0 + x1) / 2, y + 0.055, _wrap(ev["text"], 40),
                        fontsize=fontsize - 0.4, color=INK, ha="center",
                        va="bottom", zorder=5, linespacing=1.15)
        elif ev["type"] == "note":
            targets = [xs[a] for a in ev["actors"] if a in xs]
            lo, hi = (min(targets), max(targets)) if targets else (0, col)
            text = _wrap(ev["text"], 64)
            longest = max(len(l) for l in text.split("\n"))
            # Width from the text itself: a note over one actor used to overflow
            # a box sized only from the actor span.
            box_w = max(hi - lo + 1.0, longest * fontsize / 72.0 * 0.60 + 0.28)
            box_h = 0.11 + text.count("\n") * fontsize / 72.0 * 1.45
            cx = (lo + hi) / 2
            cx = min(max(cx, box_w / 2 + 0.06), width - box_w / 2 - 0.06)
            ax.add_patch(FancyBboxPatch(
                (cx - box_w / 2, y - box_h / 2), box_w, box_h,
                boxstyle="round,pad=0.03,rounding_size=0.04",
                facecolor="#fffbeb", edgecolor="#f59e0b", linewidth=0.8, zorder=4,
            ))
            ax.text(cx, y, text, fontsize=fontsize - 0.6, color="#92400e",
                    ha="center", va="center", zorder=5, linespacing=1.15)
        elif ev["type"] == "divider":
            ax.plot([0.2, n_actors * col - 0.2], [y, y], color="#fdba74",
                    lw=0.8, ls=(0, (4, 3)), zorder=2)
            if ev["text"]:
                ax.text(0.3, y + 0.03, ev["text"], fontsize=fontsize - 0.8,
                        color="#b45309",
                        va="bottom", ha="left", zorder=3, style="italic")
        y -= row

    fig.tight_layout(pad=0.2)
    fig.savefig(out_path, dpi=dpi, facecolor=SURFACE,
                bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    return out_path


# --- public entry point -----------------------------------------------------

def render(block: str, out_path: Path, *, rankdir: str | None = None,
           width_in: float = 7.0, fontsize: float = 8.0, dpi: int = 200,
           compact: bool = False) -> Path:
    """Render one Mermaid ``block`` to ``out_path`` (PNG). Returns the path.

    Figures are drawn at their **final print size**: ``width_in`` is the width
    the image will occupy in the document and ``fontsize`` is in real points,
    so text is not shrunk by a later rescale. ``rankdir`` overrides the
    diagram's own direction — a chain that reads well left-to-right on screen
    is usually better top-to-bottom on a page.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    head = block.strip().splitlines()[0].strip()

    if head.startswith(("graph", "flowchart")):
        dot = _graph_to_dot(block, "graph", rankdir=rankdir, fontsize=fontsize,
                            compact=compact)
    elif head.startswith("stateDiagram"):
        dot = _state_to_dot(block)
    elif head.startswith("sequenceDiagram"):
        return _render_sequence(block, out_path, width_in=width_in,
                                fontsize=fontsize, dpi=dpi)
    else:
        raise UnsupportedDiagram(f"unsupported diagram type: {head!r}")

    proc = subprocess.run(
        ["dot", "-Tpng", f"-Gdpi={dpi}", "-o", str(out_path)],
        input=dot.encode("utf-8"), capture_output=True,
    )
    if proc.returncode != 0:
        raise UnsupportedDiagram(
            f"graphviz failed: {proc.stderr.decode('utf-8', 'replace')[:400]}\n"
            f"--- dot ---\n{dot}"
        )
    return out_path
