"""Donut chart widget using QtCharts."""

from PySide6.QtCharts import QChart, QChartView, QPieSeries
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.data.models import ChartSpec


class DonutChartWidget(QWidget):
    category_clicked = Signal(str)

    def __init__(self, spec: ChartSpec, parent=None) -> None:
        super().__init__(parent)
        self._build(spec)

    def _build(self, spec: ChartSpec) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        chart = QChart()
        chart.setTitle(spec.title)

        series = QPieSeries()
        series.setHoleSize(0.45)
        labels = spec.x or []
        data = spec.series[0].get("data", []) if spec.series else []
        for label, val in zip(labels, data):
            series.append(str(label), float(val))
        series.setLabelsVisible(True)
        series.clicked.connect(
            lambda pie_slice: self.category_clicked.emit(pie_slice.label())
        )

        chart.addSeries(series)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignRight)

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(340)
        layout.addWidget(view)
