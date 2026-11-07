"""Line chart widget using QtCharts."""

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.data.models import ChartSpec


class LineChartWidget(QWidget):
    def __init__(self, spec: ChartSpec, parent=None) -> None:
        super().__init__(parent)
        self._build(spec)

    def _build(self, spec: ChartSpec) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        chart = QChart()
        chart.setTitle(spec.title)
        chart.legend().setVisible(len(spec.series) > 1)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)

        x_labels = spec.x or []
        for s in spec.series:
            line = QLineSeries()
            line.setName(s.get("name", "Series"))
            data = s.get("data", [])
            for i, val in enumerate(data):
                line.append(i, float(val))
            chart.addSeries(line)

        axis_x = QValueAxis()
        axis_x.setLabelFormat("%d")
        axis_x.setTitleText(spec.options.get("x_label", ""))
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)

        axis_y = QValueAxis()
        axis_y.setTitleText(spec.options.get("y_label", ""))
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)

        for s in chart.series():
            s.attachAxis(axis_x)
            s.attachAxis(axis_y)

        if x_labels:
            chart.setTitle(f"{spec.title} ({', '.join(x_labels[:5])}…)" if len(x_labels) > 5 else spec.title)

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(340)
        layout.addWidget(view)
