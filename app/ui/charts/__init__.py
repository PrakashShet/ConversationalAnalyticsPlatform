"""Chart widget factory — prefers interactive ECharts, falls back to QtCharts."""

from PySide6.QtWidgets import QWidget

from app.data.models import ChartSpec


def build_chart(spec: ChartSpec) -> QWidget:
    """Build a chart widget from a ChartSpec."""
    try:
        from app.ui.charts.web_chart import WebChartWidget
        return WebChartWidget(spec)
    except ImportError as exc:
        from loguru import logger
        logger.warning(
            "QtWebEngine unavailable ({}); using static charts. "
            "Install PySide6-Addons for interactive charts.", exc
        )

    if spec.kind == "bar":
        from app.ui.charts.bar_chart import BarChartWidget
        return BarChartWidget(spec)
    if spec.kind == "line":
        from app.ui.charts.line_chart import LineChartWidget
        return LineChartWidget(spec)
    if spec.kind == "donut":
        from app.ui.charts.donut_chart import DonutChartWidget
        return DonutChartWidget(spec)
    raise NotImplementedError(f"Chart kind '{spec.kind}' not implemented")
