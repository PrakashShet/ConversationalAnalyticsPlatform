"""Schema introspection and context.md generation."""

from pathlib import Path

DEFAULT_CONTEXT_PATH = Path("data/context.md")


def build_context_md(tables: list[dict]) -> str:
    """Render database schema as markdown for LLM context."""
    lines = [
        "# Database schema",
        f"Tables: {len(tables)}",
        "",
    ]
    for table in tables:
        name = table.get("table", table.get("name", "unknown"))
        lines.append(f"## {name}")
        lines.append("| column | type | notes |")
        lines.append("|---|---|---|")
        for col in table.get("columns", []):
            col_name = col.get("name", "")
            col_type = col.get("type", "TEXT")
            notes = ""
            if col.get("pk"):
                notes = "PRIMARY KEY"
            fk = col.get("fk")
            if fk:
                notes = f"FK→{fk}" if not notes else f"{notes}; FK→{fk}"
            lines.append(f"| {col_name} | {col_type} | {notes} |")
        lines.append("")
    return "\n".join(lines)


def save_context(md: str, path: Path | None = None) -> Path:
    """Write context markdown to disk."""
    target = path or DEFAULT_CONTEXT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    return target
