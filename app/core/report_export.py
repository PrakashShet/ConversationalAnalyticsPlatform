"""Export an Analysis to a self-contained HTML report.

No external dependencies and no network needed to view: all CSS is inline.
If a chart is present, it renders with Chart.js from a CDN (graceful: a data
table is always included as a fallback).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from app.data.models import Analysis

_PALETTE = {
    "ink": "#0e1116",
    "paper": "#f4f1ea",
    "accent": "#cc3a1f",
    "muted": "#6b6759",
}


def _esc(text: object) -> str:
    return html.escape(str(text))


def _kpi_cards(analysis: Analysis) -> str:
    if not analysis.kpis:
        return ""
    cards = []
    for kpi in analysis.kpis:
        delta = f'<div class="kpi-delta {(_esc(kpi.trend or ""))}">{_esc(kpi.delta)}</div>' if kpi.delta else ""
        cards.append(
            f'<div class="kpi"><div class="kpi-label">{_esc(kpi.label)}</div>'
            f'<div class="kpi-value">{_esc(kpi.value)}</div>{delta}</div>'
        )
    return f'<div class="kpis">{"".join(cards)}</div>'


def _data_table(analysis: Analysis) -> str:
    chart = analysis.chart
    if not chart or not chart.series:
        return ""
    x_vals = chart.x or []
    rows = ""
    series = chart.series
    header_cells = "<th>Category</th>" + "".join(
        f"<th>{_esc(s.get('name', f'Series {i + 1}'))}</th>"
        for i, s in enumerate(series)
    )
    for r, x in enumerate(x_vals):
        cells = f"<td>{_esc(x)}</td>"
        for s in series:
            data = s.get("data", [])
            cells += f"<td>{_esc(data[r]) if r < len(data) else ''}</td>"
        rows += f"<tr>{cells}</tr>"
    return (
        f'<h2>Data</h2><table class="data"><thead><tr>{header_cells}</tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def _chart_block(analysis: Analysis) -> str:
    chart = analysis.chart
    if not chart or chart.kind in ("kpi_only", "table") or not chart.series:
        return ""
    kind_map = {"bar": "bar", "line": "line", "donut": "doughnut"}
    js_kind = kind_map.get(chart.kind, "bar")
    labels = chart.x or []
    datasets = [
        {"label": s.get("name", f"Series {i + 1}"), "data": s.get("data", [])}
        for i, s in enumerate(chart.series)
    ]
    config = {
        "type": js_kind,
        "data": {"labels": labels, "datasets": datasets},
        "options": {"responsive": True, "plugins": {"legend": {"position": "right"}}},
    }
    return (
        f'<h2>{_esc(chart.title or "Chart")}</h2>'
        '<canvas id="chart" height="120"></canvas>'
        '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'
        "<script>const _cfg=" + json.dumps(config) + ";"
        "if(window.Chart){new Chart(document.getElementById('chart'),_cfg);}"
        "</script>"
    )


def _insights(analysis: Analysis) -> str:
    if not analysis.insights:
        return ""
    items = "".join(f"<li>{_esc(i)}</li>" for i in analysis.insights)
    return f"<h2>Insights</h2><ul class='insights'>{items}</ul>"


def _forecast_block(analysis: Analysis) -> str:
    fc = getattr(analysis, "forecast", None)
    if not fc or not fc.points:
        return ""
    conf = int(round(fc.confidence * 100))
    metrics = fc.metrics or {}
    mape, mae = metrics.get("mape"), metrics.get("mae")
    acc = []
    if mape is not None and mape == mape:  # not NaN
        acc.append(f"backtest MAPE {mape:.1f}%")
    if mae is not None and mae == mae:
        acc.append(f"MAE {mae:,.0f}")
    meta = f"Method: <strong>{_esc(fc.method)}</strong>"
    if acc:
        meta += " · " + _esc(" · ".join(acc))
    meta += f" · {conf}% interval"

    has_band = fc.has_band
    header = "<th>Period</th><th>Forecast</th>"
    if has_band:
        header += f"<th>Lower ({conf}%)</th><th>Upper ({conf}%)</th>"
    body = ""
    for p in fc.points:
        cells = f"<td>{_esc(p.x)}</td><td>{_esc(round(p.yhat, 2))}</td>"
        if has_band:
            lo = _esc(round(p.lower, 2)) if p.lower is not None else ""
            hi = _esc(round(p.upper, 2)) if p.upper is not None else ""
            cells += f"<td>{lo}</td><td>{hi}</td>"
        body += f"<tr>{cells}</tr>"
    return (
        '<h2>Forecast</h2>'
        f'<p class="fc-meta">{meta}</p>'
        f'<table class="data"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
        '<p class="fc-disclaimer">Forecasts are model estimates with uncertainty, '
        'not guaranteed outcomes.</p>'
    )


def _predictive_block(analysis: Analysis) -> str:
    """Predictive-analytics narrative, mirroring the canvas section.

    Composed locally by ``forecast_narrative`` — the same text the app shows —
    so an exported report and the screen never disagree.
    """
    if analysis.forecast is None or analysis.ts_profile is None:
        if analysis.forecast_requested and analysis.forecast_note:
            return (
                "<h2>Predictive Analytics</h2>"
                f"<div class=\"summary\">No forecast for this result. "
                f"{_esc(analysis.forecast_note)}</div>"
            )
        return ""
    try:
        from app.core import forecast_narrative

        content = forecast_narrative.build(analysis.ts_profile, analysis.forecast)
    except Exception:  # noqa: BLE001 - narrative is optional in a report
        return ""
    if not content:
        return ""
    bullets = "".join(f"<li>{_esc(b)}</li>" for b in content.get("bullets", []))
    return (
        "<h2>Predictive Analytics</h2>"
        f"<div class=\"summary\">{_esc(content.get('summary', ''))}</div>"
        + (f"<ul class=\"insights\">{bullets}</ul>" if bullets else "")
        + f"<p class=\"fc-disclaimer\">{_esc(content.get('caveat', ''))}</p>"
    )


def build_report_html(analysis: Analysis) -> str:
    """Return a complete, standalone HTML document for one analysis."""
    created = analysis.created_at.strftime("%Y-%m-%d %H:%M UTC")
    meta = (
        f"{analysis.row_count:,} rows · {analysis.elapsed_ms} ms · {created}"
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(analysis.question)} — Conv-Analytics</title>
<style>
  :root {{ --ink:{_PALETTE['ink']}; --paper:{_PALETTE['paper']};
           --accent:{_PALETTE['accent']}; --muted:{_PALETTE['muted']}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
          font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
          line-height:1.5; }}
  .wrap {{ max-width:920px; margin:0 auto; padding:40px 28px 64px; }}
  h1 {{ font-size:1.6rem; margin:0 0 4px; }}
  .meta {{ color:var(--muted); font-size:.85rem; margin-bottom:28px; }}
  h2 {{ font-size:1.05rem; margin:32px 0 12px; border-bottom:2px solid var(--ink);
        padding-bottom:4px; }}
  .summary {{ background:#fff; border:1px solid #ddd6c8; border-radius:8px;
              padding:16px 18px; }}
  pre.sql {{ background:var(--ink); color:#e8e6df; padding:16px; border-radius:8px;
             overflow:auto; font-size:.85rem; }}
  .kpis {{ display:flex; flex-wrap:wrap; gap:14px; margin-top:8px; }}
  .kpi {{ flex:1 1 150px; background:#fff; border:1px solid #ddd6c8;
          border-radius:8px; padding:14px 16px; }}
  .kpi-label {{ color:var(--muted); font-size:.8rem; text-transform:uppercase;
                letter-spacing:.04em; }}
  .kpi-value {{ font-size:1.5rem; font-weight:600; margin-top:4px; }}
  .kpi-delta.up {{ color:#1a7f37; }} .kpi-delta.down {{ color:var(--accent); }}
  table.data {{ border-collapse:collapse; width:100%; font-size:.9rem; }}
  table.data th, table.data td {{ border:1px solid #ddd6c8; padding:8px 10px;
                                  text-align:left; }}
  table.data th {{ background:#ece7da; }}
  ul.insights li {{ margin-bottom:6px; }}
  .fc-meta {{ color:var(--muted); font-size:.9rem; margin:6px 0 0; }}
  .fc-disclaimer {{ color:var(--muted); font-size:.8rem; font-style:italic; margin-top:8px; }}
  footer {{ margin-top:48px; color:var(--muted); font-size:.78rem;
            border-top:1px solid #ddd6c8; padding-top:12px; }}
</style></head>
<body><div class="wrap">
  <h1>{_esc(analysis.question)}</h1>
  <div class="meta">{_esc(meta)}</div>
  <h2>Summary</h2>
  <div class="summary">{_esc(analysis.summary)}</div>
  {_kpi_cards(analysis)}
  {_chart_block(analysis)}
  {_forecast_block(analysis)}
  {_data_table(analysis)}
  {_insights(analysis)}
  {_predictive_block(analysis)}
  <h2>SQL</h2>
  <pre class="sql">{_esc(analysis.sql or '-- no SQL generated')}</pre>
  <footer>Generated by Conv-Analytics · narrative by Google Gemini · forecasts computed locally</footer>
</div></body></html>"""


def export_report(analysis: Analysis, path: str | Path) -> Path:
    """Write the HTML report to ``path`` and return the resolved path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report_html(analysis), encoding="utf-8")
    return out
