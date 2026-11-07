"""Bar chart widget using QtCharts."""

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QValueAxis,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.data.models import ChartSpec

ACCENT = QColor("#6366f1")
DEFAULT = QColor("#94a3b8")
# Distinct colors so multiple series are visually separable.
SERIES_COLORS = ["#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#0ea5e9"]


class BarChartWidget(QWidget):
    category_clicked = Signal(str)

    def __init__(self, spec: ChartSpec, parent=None) -> None:
        super().__init__(parent)
        self._categories: list[str] = []
        self._build(spec)

    def _build(self, spec: ChartSpec) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        chart = QChart()
        chart.setTitle(spec.title)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)

        series = QBarSeries()
        highlight = spec.options.get("highlight_index")
        multi_series = len(spec.series) > 1

        for si, s in enumerate(spec.series):
            bar_set = QBarSet(s.get("name", "Value"))
            for i, val in enumerate(s.get("data", [])):
                try:
                    bar_set.append(float(val))
                except (TypeError, ValueError):
                    bar_set.append(0.0)
            # Color: distinct per series when multiple; highlight single-series bar.
            if multi_series:
                bar_set.setColor(QColor(SERIES_COLORS[si % len(SERIES_COLORS)]))
            elif highlight is not None:
                bar_set.setColor(DEFAULT)
            else:
                bar_set.setColor(ACCENT)
            series.append(bar_set)
            bar_set.clicked.connect(self._on_bar_clicked)

        chart.addSeries(series)
        first_data = spec.series[0]["data"] if spec.series else []
        categories = spec.x or [str(i) for i in range(len(first_data))]
        categories = [str(c) for c in categories]
        self._categories = list(categories)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        # Rotate labels when there are many categories so they don't truncate.
        if len(categories) > 4:
            axis_x.setLabelsAngle(-45)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.applyNiceNumbers()
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        chart.legend().setVisible(multi_series)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(340)
        layout.addWidget(view)

    def _on_bar_clicked(self, index: int) -> None:
        if 0 <= index < len(self._categories):
            self.category_clicked.emit(str(self._categories[index]))
