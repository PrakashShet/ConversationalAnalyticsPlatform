"""Canvas panel — renders analysis results."""

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.data.models import Analysis, ChartSpec

# Column order in the method-comparison table: Method, MAPE, MAE, RMSE.
_METRIC_TOOLTIPS = (
    "",
    "Mean Absolute Percentage Error — average miss as a percentage of the "
    "actual value. Scale-free, so it compares across series.",
    "Mean Absolute Error — average miss in the measure's own units.",
    "Root Mean Square Error — like MAE but penalises large misses more "
    "heavily, so it is sensitive to occasional big errors.",
)

_METRIC_LEGEND = (
    "MAPE — mean absolute percentage error (average miss, as a % of actual). "
    "MAE — mean absolute error (average miss, in the measure's units). "
    "RMSE — root mean square error (as MAE, but punishes large misses)."
)

_METHOD_NOTES = {
    "auto": "Backtests every eligible method and keeps the lowest error.",
    "naive": "Repeats the last observed value. The baseline to beat.",
    "seasonal_naive": "Repeats the equivalent period from the last full cycle.",
    "moving_average": "Averages recent periods. Steady, ignores trend.",
    "linear_trend": "Fits a straight line through history and extends it.",
    "holt": "Exponential smoothing with a trend term. No seasonality.",
    "holt_winters": "Exponential smoothing with trend and seasonality.",
    "sarima": "Seasonal ARIMA. Most flexible, needs the most history.",
}

_METHOD_LABELS = {
    "auto": "Auto (best fit)",
    "naive": "Naive",
    "seasonal_naive": "Seasonal naive",
    "moving_average": "Moving average",
    "linear_trend": "Linear trend",
    "holt": "Holt (trend)",
    "holt_winters": "Holt-Winters (seasonal)",
    "sarima": "SARIMA",
}


class CanvasPanel(QWidget):
    """Right panel displaying analysis output."""

    refresh_requested = Signal(str)
    export_requested = Signal(object)
    drilldown_requested = Signal(str)
    suggestion_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasPanel")
        self._current_question = ""
        self._current_analysis: Analysis | None = None
        self._loading_timer: QTimer | None = None
        self._loading_dots = 0
        # Forecast (predictive) UI state — reset on every render().
        self._fc_profile = None
        self._fc_chart_spec: ChartSpec | None = None
        self._fc_chart_layout: QVBoxLayout | None = None
        self._fc_badge: QLabel | None = None
        self._fc_method: QComboBox | None = None
        self._fc_horizon: QSpinBox | None = None
        self._fc_conf: QComboBox | None = None
        self._fc_enabled: QCheckBox | None = None
        self._build_ui()
        self.show_empty_state(connected=False)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("CanvasScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._content = QWidget()
        self._content.setObjectName("CanvasInner")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(32, 28, 32, 32)
        self._layout.setSpacing(20)

        self._question_label = QLabel("")
        self._question_label.setObjectName("QuestionHeader")
        self._question_label.setWordWrap(True)
        self._layout.addWidget(self._question_label)

        self._loading_label = QLabel("")
        self._loading_label.setObjectName("LoadingLabel")
        self._loading_label.setWordWrap(True)
        self._loading_label.hide()
        self._layout.addWidget(self._loading_label)

        self._empty_label = QLabel("")
        self._empty_label.setObjectName("EmptyState")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._empty_label)

        self._result_container = QWidget()
        self._result_layout = QVBoxLayout(self._result_container)
        self._result_layout.setContentsMargins(0, 0, 0, 0)
        self._result_layout.setSpacing(12)
        self._layout.addWidget(self._result_container)
        self._result_container.hide()

        self._layout.addStretch()
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

    def show_empty_state(self, connected: bool) -> None:
        self._clear_result()
        self._result_container.hide()
        self._loading_label.hide()
        self._question_label.hide()
        self._empty_label.show()
        if connected:
            self._empty_label.setText("Ask a question below.")
        else:
            self._empty_label.setText(
                "Connect a database in the left panel."
            )

    def show_loading(self) -> None:
        self._empty_label.hide()
        self._result_container.hide()
        self._question_label.show()
        self._loading_label.show()
        self._loading_dots = 0
        if self._loading_timer is None:
            self._loading_timer = QTimer(self)
            self._loading_timer.timeout.connect(self._animate_loading)
        self._loading_timer.start(400)

    def _animate_loading(self) -> None:
        self._loading_dots = (self._loading_dots + 1) % 4
        self._loading_label.setText(
            f"Thinking{'.' * self._loading_dots}"
        )

    def show_stream_summary(self, text: str) -> None:
        """Display the plain-text summary live as it streams in, word by word."""
        if self._loading_timer:
            self._loading_timer.stop()
        self._empty_label.hide()
        self._loading_label.show()
        self._loading_label.setText(text + " ▌")

    def show_error(self, message: str) -> None:
        if self._loading_timer:
            self._loading_timer.stop()
        self._loading_label.hide()
        self._result_container.hide()
        self._empty_label.hide()
        self._question_label.show()
        error = QLabel(message)
        error.setObjectName("ErrorBanner")
        error.setWordWrap(True)
        self._layout.insertWidget(2, error)

    def render(self, analysis: Analysis) -> None:
        if self._loading_timer:
            self._loading_timer.stop()
        self._loading_label.hide()
        self._empty_label.hide()
        self._current_question = analysis.question
        self._current_analysis = analysis
        self._question_label.setText(analysis.question)
        self._question_label.show()
        self._clear_result()
        self._result_container.show()

        # Top action bar (meta on the left, buttons on the right).
        self._add_action_bar(analysis)

        # 1. KPIs — headline numbers first.
        if analysis.kpis:
            self._add_kpis(analysis.kpis)

        # Reset forecast UI state for this render.
        self._fc_profile = analysis.ts_profile if analysis.forecastable else None
        self._fc_chart_spec = None
        self._fc_chart_layout = None

        # Decide which chart carries the forecast overlay (a line chart). If the
        # result is forecastable but has no line chart, synthesize one from the
        # detected series so the prediction still has somewhere to render.
        forecast_chart = None
        synthetic = None
        if analysis.forecastable and analysis.forecast is not None:
            forecast_chart = next(
                (c for c in analysis.all_charts if c.kind == "line"), None
            )
            if forecast_chart is None and analysis.ts_profile is not None:
                synthetic = self._profile_chart(analysis.ts_profile)
                forecast_chart = synthetic

        # 2. Charts (interactive).
        for chart in analysis.all_charts:
            if chart.kind == "table":
                self._add_table(chart, analysis)
            elif chart is forecast_chart and synthetic is None:
                self._add_forecast_chart(chart, analysis)
            elif chart.kind not in ("kpi_only",):
                self._add_chart(chart)
        if synthetic is not None:
            self._add_forecast_chart(synthetic, analysis)

        # 2b. Forecast controls (only on relevant, forecastable results).
        if analysis.forecastable and analysis.forecast is not None and forecast_chart is not None:
            self._add_forecast_controls(analysis)

        # 3. Data description (summary).
        if analysis.summary:
            self._add_text_card("Data Description", analysis.summary)

        # 4. Descriptive analytics (insights).
        if analysis.insights:
            self._add_insights(analysis.insights)

        # 4b. Predictive analytics — narrative for the forecast, composed
        #     locally. Shown whenever a forecast exists; when one was asked for
        #     and could not be produced, the reason takes its place.
        if analysis.forecast is not None and analysis.ts_profile is not None:
            self._add_predictive_analytics(analysis)
        elif analysis.forecast_requested and analysis.forecast_note:
            self._add_forecast_note(analysis.forecast_note)

        # 5. Suggested follow-ups.
        if analysis.suggestions:
            self._add_suggestions(analysis.suggestions)

        # 6. SQL query (collapsible, collapsed by default).
        self._add_sql_card(analysis.sql)

        self._result_layout.addStretch()

    # -- section builders ----------------------------------------------------

    @property
    def current_analysis(self) -> Analysis | None:
        """The analysis on screen — live or replayed from history.

        MainWindow checks its ``source`` before running any follow-up derived
        from it (suggestion, drill-down, refresh).
        """
        return self._current_analysis

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("SectionTitle")
        return label

    def _add_action_bar(self, analysis: Analysis) -> None:
        bar = QHBoxLayout()
        meta = QLabel(
            f"{analysis.row_count:,} rows · {analysis.elapsed_ms} ms"
        )
        meta.setObjectName("ResultMeta")
        bar.addWidget(meta)
        bar.addStretch()
        if analysis.tokens:
            parts = []
            if analysis.planner_tokens:
                parts.append(f"plan {analysis.planner_tokens:,}")
            if analysis.analyst_tokens:
                parts.append(f"analyze {analysis.analyst_tokens:,}")
            detail = " · ".join(parts) if parts else ""
            label = f"🔢 {analysis.tokens:,} tokens"
            if detail:
                label += f" ({detail})"
            tokens = QLabel(label)
            tokens.setObjectName("TokenBadge")
            tokens.setToolTip("Gemini tokens: SQL planner + result analyst")
            bar.addWidget(tokens)
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.clicked.connect(self._on_refresh)
        bar.addWidget(refresh_btn)
        export_btn = QPushButton("⇩ Export HTML")
        export_btn.setObjectName("SecondaryButton")
        export_btn.clicked.connect(self._on_export)
        bar.addWidget(export_btn)
        self._result_layout.addLayout(bar)

    def _add_kpis(self, kpis) -> None:
        grid = QGridLayout()
        grid.setSpacing(12)
        cols = min(len(kpis), 4)
        for i, kpi in enumerate(kpis):
            tile = QFrame()
            tile.setObjectName("KpiTile")
            tl = QVBoxLayout(tile)
            tl.setSpacing(4)
            label = QLabel(kpi.label)
            label.setObjectName("KpiLabel")
            label.setWordWrap(True)
            value = QLabel(kpi.value)
            value.setObjectName("KpiValue")
            tl.addWidget(label)
            tl.addWidget(value)
            if kpi.delta:
                d = QLabel(kpi.delta)
                d.setObjectName(
                    "KpiDeltaUp" if kpi.trend == "up" else "KpiDeltaDown"
                )
                tl.addWidget(d)
            grid.addWidget(tile, i // cols, i % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        wrap = QWidget()
        wrap.setLayout(grid)
        self._result_layout.addWidget(wrap)

    def _add_chart(self, chart_spec) -> None:
        card = QFrame()
        card.setObjectName("ChartCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 16)
        cl.setSpacing(8)
        if chart_spec.title:
            cl.addWidget(self._section_title(chart_spec.title))

        from app.ui.charts import build_chart

        try:
            chart_widget = build_chart(chart_spec)
            if hasattr(chart_widget, "category_clicked"):
                chart_widget.category_clicked.connect(self.drilldown_requested.emit)
            cl.addWidget(chart_widget)
            self._result_layout.addWidget(card)
        except NotImplementedError:
            pass

    # -- forecast (predictive) UI -------------------------------------------

    @staticmethod
    def _profile_chart(profile) -> ChartSpec:
        """A line ChartSpec built from a detected series (forecast host fallback)."""
        return ChartSpec(
            kind="line",
            title=f"{profile.value_column} over time",
            x=list(profile.x),
            series=[{"name": profile.value_column, "data": list(profile.y)}],
            options={"x_column": profile.time_column, "y_column": profile.value_column},
        )

    def _add_forecast_chart(self, chart: ChartSpec, analysis: Analysis) -> None:
        """Render the forecast host chart inside a reusable holder for recompute."""
        card = QFrame()
        card.setObjectName("ChartCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 16)
        cl.setSpacing(8)
        if chart.title:
            cl.addWidget(self._section_title(chart.title))
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(holder)
        self._result_layout.addWidget(card)

        self._fc_chart_spec = chart
        self._fc_chart_layout = holder_layout
        self._render_forecast_overlay(analysis.forecast)

    def _render_forecast_overlay(self, result) -> None:
        """(Re)build the host chart widget with the forecast overlay applied."""
        if self._fc_chart_spec is None or self._fc_chart_layout is None:
            return
        spec = self._fc_chart_spec
        options = dict(spec.options or {})
        if result is not None:
            from app.core.forecasting import forecast_overlay

            options["forecast"] = forecast_overlay(result)
        else:
            options.pop("forecast", None)
        new_spec = ChartSpec(
            kind=spec.kind, title=spec.title, x=spec.x,
            series=spec.series, options=options,
        )
        self._clear_layout(self._fc_chart_layout)
        from app.ui.charts import build_chart

        try:
            widget = build_chart(new_spec)
            if hasattr(widget, "category_clicked"):
                widget.category_clicked.connect(self.drilldown_requested.emit)
            self._fc_chart_layout.addWidget(widget)
        except NotImplementedError:
            pass

    def _add_forecast_controls(self, analysis: Analysis) -> None:
        from app.core.forecasting import PERIOD_NOUN

        result = analysis.forecast
        profile = analysis.ts_profile
        card = QFrame()
        card.setObjectName("InsightsCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(10)
        cl.addWidget(self._section_title("Forecast"))

        row = QHBoxLayout()
        row.setSpacing(10)

        self._fc_enabled = QCheckBox("Show")
        self._fc_enabled.setChecked(True)
        self._fc_enabled.setToolTip("Hide the projection and keep only history.")
        self._fc_enabled.toggled.connect(self._on_forecast_changed)
        row.addWidget(self._fc_enabled)

        row.addWidget(QLabel("Method"))
        self._fc_method = QComboBox()
        self._fc_method.setToolTip(
            "Auto backtests every eligible method and keeps the most accurate."
        )
        for method in (analysis.available_methods or [result.method]):
            self._fc_method.addItem(_METHOD_LABELS.get(method, method), method)
            self._fc_method.setItemData(
                self._fc_method.count() - 1,
                _METHOD_NOTES.get(method, ""),
                Qt.ItemDataRole.ToolTipRole,
            )
        midx = self._fc_method.findData(result.method)
        if midx >= 0:
            self._fc_method.setCurrentIndex(midx)
        self._fc_method.currentIndexChanged.connect(self._on_forecast_changed)
        row.addWidget(self._fc_method)

        noun = PERIOD_NOUN.get(profile.freq, "period") if profile else "period"
        row.addWidget(QLabel("Horizon"))
        self._fc_horizon = QSpinBox()
        self._fc_horizon.setRange(1, 36)
        self._fc_horizon.setValue(result.horizon)
        self._fc_horizon.setSuffix(f" {noun}s")
        self._fc_horizon.setToolTip(
            f"How many {noun}s ahead to project. Accuracy degrades with distance."
        )
        self._fc_horizon.valueChanged.connect(self._on_forecast_changed)
        row.addWidget(self._fc_horizon)

        row.addWidget(QLabel("Confidence"))
        self._fc_conf = QComboBox()
        self._fc_conf.setToolTip(
            "Width of the shaded band. A 90% band is expected to contain the "
            "actual value 9 times out of 10 — wider means less precise, not "
            "more certain."
        )
        for pct in (80, 90, 95):
            self._fc_conf.addItem(f"{pct}%", pct / 100.0)
        cidx = self._fc_conf.findData(result.confidence)
        if cidx >= 0:
            self._fc_conf.setCurrentIndex(cidx)
        self._fc_conf.currentIndexChanged.connect(self._on_forecast_changed)
        row.addWidget(self._fc_conf)

        row.addStretch()
        cl.addLayout(row)

        hint = QLabel(
            f"Changing any of these recomputes locally — no query, no API call. "
            f"Horizon is measured in {noun}s, the grain detected in your data."
        )
        hint.setObjectName("SectionHint")
        hint.setWordWrap(True)
        cl.addWidget(hint)

        self._fc_badge = QLabel("")
        self._fc_badge.setObjectName("ResultMeta")
        self._fc_badge.setWordWrap(True)
        cl.addWidget(self._fc_badge)
        self._set_forecast_badge(result)

        if profile is not None:
            self._add_forecast_details(cl, profile, result)

        self._result_layout.addWidget(card)

    def _add_forecast_details(self, layout, profile, result) -> None:
        """Collapsible: series diagnostics, method scores, availability.

        Everything here is local arithmetic over history already in memory.
        Collapsed by default so the common case stays uncluttered.
        """
        toggle = QToolButton()
        toggle.setObjectName("LinkButton")
        toggle.setText("▸ Model details")
        toggle.setCheckable(True)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        body = QWidget()
        body.setVisible(False)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 6, 0, 0)
        bl.setSpacing(12)

        try:
            from app.core.forecasting import (
                compare_methods,
                method_availability,
                series_diagnostics,
            )

            diag = series_diagnostics(profile)
            bl.addWidget(self._diagnostics_grid(diag))
            bl.addWidget(self._sub_label(
                "Method comparison — each fitted on history minus the last "
                f"{diag['holdout']} periods, then scored on those held-out "
                "periods. Lower is better."
            ))
            bl.addWidget(self._method_table(
                compare_methods(profile, result.confidence), result.method
            ))
            bl.addWidget(self._sub_label(_METRIC_LEGEND))
            bl.addWidget(self._sub_label("Availability for this series"))
            bl.addWidget(self._availability_list(method_availability(profile)))
        except Exception as exc:  # noqa: BLE001 - details are optional
            from loguru import logger

            logger.warning("Forecast details unavailable: {}", exc)
            return

        layout.addWidget(body)

        def _on_toggle(checked: bool) -> None:
            body.setVisible(checked)
            toggle.setText("▾ Model details" if checked else "▸ Model details")

        toggle.toggled.connect(_on_toggle)

    def _sub_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionHint")
        label.setWordWrap(True)
        return label

    def _diagnostics_grid(self, diag: dict) -> QWidget:
        seasonal = (
            f"yes, {diag['seasonal_period']}-period cycle"
            if diag["seasonal"]
            else "not detected"
        )
        fields = [
            ("Time column", diag["time_column"]),
            ("Measure", diag["value_column"]),
            ("Detected grain", diag["freq_label"]),
            ("Periods", f"{diag['n_points']}"),
            ("Range", f"{diag['first']} → {diag['last']}"),
            ("Seasonality", seasonal),
            ("Backtest holdout", f"{diag['holdout']} periods"),
            ("Observed range", f"{diag['min']:,.0f} – {diag['max']:,.0f}"),
        ]
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        for i, (name, value) in enumerate(fields):
            key = QLabel(name)
            key.setObjectName("SectionHint")
            val = QLabel(str(value))
            val.setObjectName("InsightItem")
            grid.addWidget(key, i // 2, (i % 2) * 2)
            grid.addWidget(val, i // 2, (i % 2) * 2 + 1)
        # Value columns size to their content and the pairs stay adjacent; only
        # the trailing spacer absorbs slack, so nothing is flung to the edge.
        grid.setColumnMinimumWidth(1, 120)
        grid.setColumnMinimumWidth(3, 120)
        grid.setColumnStretch(4, 1)
        return wrap

    def _method_table(self, rows: list[dict], chosen: str) -> QWidget:
        """Scores per method, sized to its own content rather than the panel."""
        table = QTableWidget(len(rows), 4)
        table.setObjectName("DataTable")
        table.setHorizontalHeaderLabels(["Method", "MAPE", "MAE", "RMSE"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        for col, tip in enumerate(_METRIC_TOOLTIPS):
            header_item = table.horizontalHeaderItem(col)
            if header_item is not None and tip:
                header_item.setToolTip(tip)

        numeric = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for r, row in enumerate(rows):
            label = _METHOD_LABELS.get(row["method"], row["method"])
            if row["method"] == chosen:
                label += "   ← in use"
            cells = [
                label,
                "—" if row["mape"] is None else f"{row['mape']:.1f}%",
                "—" if row["mae"] is None else f"{row['mae']:,.0f}",
                "—" if row["rmse"] is None else f"{row['rmse']:,.0f}",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c > 0:
                    item.setTextAlignment(numeric)
                if not row["runnable"]:
                    item.setToolTip("Not runnable in this environment.")
                if row["method"] == chosen:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                table.setItem(r, c, item)
            if row["note"]:
                table.item(r, 0).setToolTip(row["note"])

        # Each column hugs its widest cell; no stretched last section, which is
        # what previously threw RMSE to the far edge of the panel.
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.resizeColumnsToContents()

        # Lock the content-derived widths in, plus a cushion: the stylesheet
        # pads header sections and content sizing can under-count that.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for c in range(table.columnCount()):
            table.setColumnWidth(c, table.columnWidth(c) + 16)

        width = sum(table.columnWidth(c) for c in range(table.columnCount()))
        width += 2 * table.frameWidth() + 2
        height = header.height() + 2 * table.frameWidth()
        for r in range(table.rowCount()):
            height += table.rowHeight(r)
        table.setFixedSize(width, height)

        # Left-aligned in a full-width row so the card layout stays intact.
        wrap = QWidget()
        row_layout = QHBoxLayout(wrap)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(table)
        row_layout.addStretch()
        return wrap

    def _availability_list(self, rows: list[dict]) -> QWidget:
        wrap = QWidget()
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(3)
        for row in rows:
            line = QLabel(
                f"{'✓' if row['offered'] else '✕'}  "
                f"{_METHOD_LABELS.get(row['method'], row['method'])} — "
                f"{row['reason']}"
            )
            line.setObjectName("InsightItem" if row["offered"] else "SectionHint")
            line.setWordWrap(True)
            if row["note"]:
                line.setToolTip(row["note"])
            vl.addWidget(line)
        return wrap

    def _add_predictive_analytics(self, analysis: Analysis) -> None:
        """Narrative for the forecast, mirroring Descriptive Analytics.

        Composed in Python from the forecast itself — no Gemini call, so this
        section costs nothing and cannot restate a number incorrectly.
        """
        from app.core import forecast_narrative

        content = forecast_narrative.build(analysis.ts_profile, analysis.forecast)
        if not content:
            return

        card = QFrame()
        card.setObjectName("InsightsCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(8)
        cl.addWidget(self._section_title("Predictive Analytics"))

        if content.get("summary"):
            summary = QLabel(content["summary"])
            summary.setObjectName("InsightItem")
            summary.setWordWrap(True)
            cl.addWidget(summary)

        for text in content.get("bullets", []):
            row = QHBoxLayout()
            row.setSpacing(8)
            bullet = QLabel("•")
            bullet.setObjectName("InsightBullet")
            bullet.setAlignment(Qt.AlignmentFlag.AlignTop)
            item = QLabel(text)
            item.setObjectName("InsightItem")
            item.setWordWrap(True)
            row.addWidget(bullet, alignment=Qt.AlignmentFlag.AlignTop)
            row.addWidget(item, stretch=1)
            cl.addLayout(row)

        if content.get("caveat"):
            caveat = QLabel(content["caveat"])
            caveat.setObjectName("SectionHint")
            caveat.setWordWrap(True)
            cl.addWidget(caveat)

        self._result_layout.addWidget(card)

    def _add_forecast_note(self, note: str) -> None:
        """Why a requested forecast could not be produced."""
        card = QFrame()
        card.setObjectName("InsightsCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(6)
        cl.addWidget(self._section_title("Predictive Analytics"))
        body = QLabel(f"No forecast for this result. {note}")
        body.setObjectName("InsightItem")
        body.setWordWrap(True)
        cl.addWidget(body)
        self._result_layout.addWidget(card)

    def _set_forecast_badge(self, result) -> None:
        if self._fc_badge is None:
            return
        metrics = result.metrics or {}
        mape, mae = metrics.get("mape"), metrics.get("mae")
        parts = [f"Model: {_METHOD_LABELS.get(result.method, result.method)}"]
        if mape is not None and mape == mape:  # not NaN
            parts.append(f"backtest MAPE {mape:.1f}%")
        if mae is not None and mae == mae:
            parts.append(f"MAE {mae:,.0f}")
        text = "  ·  ".join(parts)
        if result.warnings:
            text += f"\n{result.warnings[0]}"
        self._fc_badge.setText(text)

    def _on_forecast_changed(self, *args) -> None:
        if self._fc_profile is None or self._fc_method is None:
            return
        if self._fc_enabled is not None and not self._fc_enabled.isChecked():
            self._render_forecast_overlay(None)
            if self._fc_badge is not None:
                self._fc_badge.setText("Forecast hidden")
            return
        method = self._fc_method.currentData() or "auto"
        horizon = self._fc_horizon.value() if self._fc_horizon else 12
        confidence = self._fc_conf.currentData() if self._fc_conf else 0.8
        if self._fc_badge is not None:
            self._fc_badge.setText("Computing forecast…")
        from app.ui.workers.forecast_worker import ForecastWorker

        worker = ForecastWorker(self._fc_profile, method, horizon, confidence)
        worker.signals.finished.connect(self._apply_forecast_result)
        worker.signals.failed.connect(self._on_forecast_failed)
        QThreadPool.globalInstance().start(worker)

    def _apply_forecast_result(self, result) -> None:
        self._render_forecast_overlay(result)
        self._set_forecast_badge(result)
        if self._current_analysis is not None:
            self._current_analysis.forecast = result  # keep HTML export in sync

    def _on_forecast_failed(self, message: str) -> None:
        if self._fc_badge is not None:
            self._fc_badge.setText(f"Forecast error: {message}")

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _add_suggestions(self, suggestions: list[str]) -> None:
        card = QFrame()
        card.setObjectName("InsightsCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(10)
        cl.addWidget(self._section_title("Suggested follow-ups"))
        row = QHBoxLayout()
        row.setSpacing(8)
        for text in suggestions[:3]:
            btn = QPushButton(text)
            btn.setObjectName("SecondaryButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, t=text: self.suggestion_clicked.emit(t))
            row.addWidget(btn)
        row.addStretch()
        cl.addLayout(row)
        self._result_layout.addWidget(card)

    def _add_text_card(self, title: str, text: str) -> None:
        card = QFrame()
        card.setObjectName("SummaryCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(8)
        cl.addWidget(self._section_title(title))
        body = QLabel(text)
        body.setObjectName("SummaryBody")
        body.setWordWrap(True)
        cl.addWidget(body)
        self._result_layout.addWidget(card)

    def _add_insights(self, insights) -> None:
        card = QFrame()
        card.setObjectName("InsightsCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 16)
        cl.setSpacing(8)
        cl.addWidget(self._section_title("Descriptive Analytics"))
        for text in insights:
            row = QHBoxLayout()
            row.setSpacing(8)
            bullet = QLabel("•")
            bullet.setObjectName("InsightBullet")
            bullet.setAlignment(Qt.AlignmentFlag.AlignTop)
            item = QLabel(text)
            item.setObjectName("InsightItem")
            item.setWordWrap(True)
            row.addWidget(bullet, alignment=Qt.AlignmentFlag.AlignTop)
            row.addWidget(item, stretch=1)
            cl.addLayout(row)
        self._result_layout.addWidget(card)

    def _add_sql_card(self, sql: str) -> None:
        card = QFrame()
        card.setObjectName("SqlCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 10, 16, 12)
        cl.setSpacing(8)

        toggle = QToolButton()
        toggle.setObjectName("SqlToggle")
        toggle.setText("▸  SQL Query")
        toggle.setCheckable(True)
        toggle.setChecked(False)
        cl.addWidget(toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        block = QPlainTextEdit()
        block.setObjectName("SqlBlock")
        block.setPlainText(sql or "-- no SQL generated")
        block.setReadOnly(True)
        # Auto-size to content (2–14 lines) instead of a fixed tall box.
        line_count = (sql or "").count("\n") + 1
        line_h = block.fontMetrics().lineSpacing()
        block.setFixedHeight(min(max(line_count, 2), 14) * line_h + 24)
        block.setVisible(False)
        cl.addWidget(block)

        def _on_toggle(checked: bool) -> None:
            block.setVisible(checked)
            toggle.setText(("▾  SQL Query") if checked else ("▸  SQL Query"))

        toggle.toggled.connect(_on_toggle)
        self._result_layout.addWidget(card)

    def _add_table(self, chart_spec, analysis: Analysis) -> None:
        if not chart_spec.series:
            return
        card = QFrame()
        card.setObjectName("ChartCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 16)
        cl.setSpacing(8)
        cl.addWidget(self._section_title("Data"))
        table = QTableWidget()
        headers = ["Category", "Value"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        x_vals = chart_spec.x or []
        data = chart_spec.series[0].get("data", []) if chart_spec.series else []
        table.setRowCount(len(x_vals))
        for row, (x, y) in enumerate(zip(x_vals, data)):
            table.setItem(row, 0, QTableWidgetItem(str(x)))
            table.setItem(row, 1, QTableWidgetItem(str(y)))
        table.setMinimumHeight(min(len(x_vals), 12) * 30 + 40)
        cl.addWidget(table)
        self._result_layout.addWidget(card)

    def _clear_result(self) -> None:
        while self._result_layout.count():
            item = self._result_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            layout = item.layout()
            if layout:
                while layout.count():
                    sub = layout.takeAt(0)
                    w = sub.widget()
                    if w:
                        w.deleteLater()

    def _on_refresh(self) -> None:
        if self._current_question:
            self.refresh_requested.emit(self._current_question)

    def _on_export(self) -> None:
        if self._current_analysis is not None:
            self.export_requested.emit(self._current_analysis)

    def set_question_header(self, question: str) -> None:
        self._current_question = question
        self._question_label.setText(question)
        self._question_label.show()
