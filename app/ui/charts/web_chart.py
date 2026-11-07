"""Interactive ECharts chart via QWebEngineView."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.data.models import ChartSpec
from app.paths import resource_path

_VENDOR = resource_path("resources", "vendor", "echarts.min.js")
_HTML_SHELL = resource_path("ui", "charts", "chart_shell.html")


class _ChartBridge(QObject):
    category_clicked = Signal(str)

    @Slot(str)
    def onCategoryClick(self, name: str) -> None:
        self.category_clicked.emit(name)


# Forecast styling — a distinct amber that stands apart from the blue history line.
_FORECAST_COLOR = "#f59e0b"
_FORECAST_BAND_COLOR = "rgba(245, 158, 11, 0.16)"
_FORECAST_ZONE_COLOR = "rgba(245, 158, 11, 0.06)"


def _line_series_and_axis(spec: ChartSpec, x_labels: list) -> tuple[list, list, list]:
    """Build (axis, series, legend_names) for a line chart.

    When ``spec.options['forecast']`` is present, append a dashed forecast mean
    (connected to the last actual point) and a shaded confidence band, extending
    the category axis with the future period labels.
    """
    series = [
        {
            "name": s.get("name", "Series"),
            "type": "line",
            "smooth": True,
            "data": list(s.get("data", [])),
        }
        for s in spec.series
    ]
    legend_data = [s["name"] for s in series]
    axis = list(x_labels)

    fc = (spec.options or {}).get("forecast")
    if not fc or not fc.get("x") or not fc.get("yhat"):
        return axis, series, legend_data

    fx = list(fc["x"])
    yhat = [float(v) for v in fc["yhat"]]
    lower, upper = fc.get("lower"), fc.get("upper")
    axis = list(x_labels) + fx
    n_hist = len(x_labels)

    # Confidence band (drawn first, underneath): transparent base + translucent fill.
    band: list = []
    if lower and upper and len(lower) == len(upper) == len(yhat):
        base = [None] * n_hist + [float(v) for v in lower]
        thick = [None] * n_hist + [float(u) - float(l) for l, u in zip(lower, upper)]
        pct = int(round(float(fc.get("confidence", 0.8)) * 100))
        band = [
            {
                "name": "_ci_base", "type": "line", "stack": "ci", "data": base,
                "lineStyle": {"opacity": 0}, "areaStyle": {"opacity": 0},
                "showSymbol": False, "silent": True, "tooltip": {"show": False},
            },
            {
                "name": f"{pct}% interval", "type": "line", "stack": "ci", "data": thick,
                "lineStyle": {"opacity": 0}, "areaStyle": {"color": _FORECAST_BAND_COLOR},
                "showSymbol": False, "silent": True,
            },
        ]
        legend_data.append(f"{pct}% interval")

    # Dashed forecast mean in a distinct amber, connected to the last actual point,
    # with the forecast region lightly shaded so it reads clearly as a projection.
    last_actual = series[0]["data"][-1] if series and series[0]["data"] else None
    connector = [None] * (n_hist - 1) + ([last_actual] if last_actual is not None else [None])
    fc_name = ("Forecast · " + str(fc.get("method", ""))).strip(" ·") or "Forecast"
    forecast_series = {
        "name": fc_name,
        "type": "line",
        "smooth": True,
        "data": connector + yhat,
        "lineStyle": {"type": "dashed", "width": 2, "color": _FORECAST_COLOR},
        "itemStyle": {"color": _FORECAST_COLOR},
        "showSymbol": False,
    }
    if fx:
        forecast_series["markArea"] = {
            "silent": True,
            "itemStyle": {"color": _FORECAST_ZONE_COLOR},
            "data": [[{"xAxis": fx[0]}, {"xAxis": fx[-1]}]],
        }
    legend_data.append(fc_name)

    return axis, band + series + [forecast_series], legend_data


def build_echarts_option(spec: ChartSpec) -> dict:
    """Convert ChartSpec to an ECharts option object."""
    title = {"text": spec.title, "left": "center", "textStyle": {"fontSize": 14}}
    tooltip = {"trigger": "axis" if spec.kind in ("bar", "line") else "item"}
    legend = {"top": 28}
    x_labels = spec.x or []

    if spec.kind == "line":
        axis, series, legend_data = _line_series_and_axis(spec, x_labels)
        return {
            "title": title,
            "tooltip": tooltip,
            "legend": {"top": 28, "data": legend_data},
            "grid": {"left": 48, "right": 24, "bottom": 48, "top": 64},
            "xAxis": {"type": "category", "data": axis},
            "yAxis": {"type": "value"},
            "dataZoom": [{"type": "inside"}, {"type": "slider", "height": 18, "bottom": 8}],
            "series": series,
        }

    if spec.kind == "donut":
        data = spec.series[0].get("data", []) if spec.series else []
        pie_data = [
            {"name": str(x_labels[i]) if i < len(x_labels) else str(i), "value": v}
            for i, v in enumerate(data)
        ]
        return {
            "title": title,
            "tooltip": tooltip,
            "legend": {"orient": "vertical", "right": 10, "top": 48},
            "series": [{
                "name": spec.title,
                "type": "pie",
                "radius": ["42%", "68%"],
                "data": pie_data,
                "label": {"formatter": "{b}: {d}%"},
            }],
        }

    # bar (default)
    series = []
    for s in spec.series:
        series.append({
            "name": s.get("name", "Value"),
            "type": "bar",
            "data": s.get("data", []),
            "itemStyle": {"borderRadius": [4, 4, 0, 0]},
        })
    highlight = spec.options.get("highlight_index")
    if highlight is not None and series:
        data = series[0]["data"]
        series[0]["data"] = [
            {"value": v, "itemStyle": {"color": "#6366f1"}}
            if i == highlight
            else v
            for i, v in enumerate(data)
        ]
    return {
        "title": title,
        "tooltip": tooltip,
        "legend": legend,
        "grid": {"left": 48, "right": 24, "bottom": 48, "top": 64},
        "xAxis": {"type": "category", "data": x_labels, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value"},
        "series": series,
    }


class WebChartWidget(QWidget):
    """Renders an interactive ECharts chart; emits category_clicked on bar/pie click."""

    category_clicked = Signal(str)

    def __init__(self, spec: ChartSpec, parent=None) -> None:
        super().__init__(parent)
        self._bridge = _ChartBridge()
        self._bridge.category_clicked.connect(self.category_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = QWebEngineView()
        self._view.setMinimumHeight(320)
        layout.addWidget(self._view)

        channel = QWebChannel(self._view.page())
        channel.registerObject("bridge", self._bridge)
        self._view.page().setWebChannel(channel)

        option = build_echarts_option(spec)
        html = _HTML_SHELL.read_text(encoding="utf-8")
        html = html.replace("__OPTION__", json.dumps(option))
        base = QUrl.fromLocalFile(str(_VENDOR.parent.resolve()) + "/")
        self._view.setHtml(html, base)
