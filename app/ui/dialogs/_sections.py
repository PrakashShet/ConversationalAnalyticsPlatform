"""Settings dialog section widgets."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import Settings


class ApiSection(QGroupBox):
    """Section A: API keys and model settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("API keys & model", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        form = QFormLayout(self)

        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._show_btn = QPushButton("Show")
        self._show_btn.setObjectName("SecondaryButton")
        self._show_btn.setCheckable(True)
        self._show_btn.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self.api_key)
        key_row.addWidget(self._show_btn)
        form.addRow("Gemini API Key", key_row)

        self.model = QComboBox()
        self.model.addItems(
            ["gemini-3.5-flash", "gemini-3.5-pro", "gemini-3-flash"]
        )
        form.addRow("Default Model", self.model)

        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(256, 8192)
        self.max_tokens.setSingleStep(256)
        form.addRow("Max Tokens", self.max_tokens)

    def _toggle_key_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.api_key.setEchoMode(mode)
        self._show_btn.setText("Hide" if checked else "Show")

    def load_from(self, settings: Settings, api_key: str) -> None:
        self.api_key.setText(api_key)
        idx = self.model.findText(settings.gemini_model)
        if idx >= 0:
            self.model.setCurrentIndex(idx)
        self.max_tokens.setValue(settings.max_tokens)

    def get_api_key(self) -> str:
        return self.api_key.text().strip()

    def get_model(self) -> str:
        return self.model.currentText()

    def get_max_tokens(self) -> int:
        return self.max_tokens.value()


class McpSection(QGroupBox):
    """Section B: MCP server / SQL connector."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Database connector", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        form = QFormLayout(self)

        self.server_type = QComboBox()
        self.server_type.addItems(["sqlite", "postgres", "mysql"])
        self.server_type.currentTextChanged.connect(self._on_type_changed)
        form.addRow("Server Type", self.server_type)

        self.server_command = QLineEdit()
        form.addRow("Server Command", self.server_command)

        self.db_url = QLineEdit()
        form.addRow("Connection URL", self.db_url)

        self.db_password = QLineEdit()
        self.db_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("DB Password", self.db_password)

        self.ssl_mode = QComboBox()
        self.ssl_mode.addItems(["disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
        form.addRow("SSL Mode", self.ssl_mode)

        self.readonly = QCheckBox("Read-only queries only")
        self.readonly.setChecked(True)
        form.addRow("", self.readonly)

        self.max_rows = QSpinBox()
        self.max_rows.setRange(100, 100000)
        self.max_rows.setSingleStep(100)
        form.addRow("Max Rows", self.max_rows)

    def _on_type_changed(self, server_type: str) -> None:
        remote = server_type in ("postgres", "mysql")
        self.db_url.setEnabled(remote)
        self.db_password.setEnabled(remote)
        self.ssl_mode.setEnabled(remote)

    def load_from(self, settings: Settings, db_password: str) -> None:
        idx = self.server_type.findText(settings.mcp_server_type)
        if idx >= 0:
            self.server_type.setCurrentIndex(idx)
        self.server_command.setText(settings.mcp_command_string())
        self.db_url.setText(settings.db_url)
        self.db_password.setText(db_password)
        ssl_idx = self.ssl_mode.findText(settings.ssl_mode)
        if ssl_idx >= 0:
            self.ssl_mode.setCurrentIndex(ssl_idx)
        self.readonly.setChecked(settings.readonly)
        self.max_rows.setValue(settings.max_rows)
        self._on_type_changed(settings.mcp_server_type)

    def apply_to(self, settings: Settings) -> None:
        settings.mcp_server_type = self.server_type.currentText()  # type: ignore[assignment]
        settings.set_mcp_command_string(self.server_command.text())
        settings.db_url = self.db_url.text().strip()
        settings.ssl_mode = self.ssl_mode.currentText()
        settings.readonly = self.readonly.isChecked()
        settings.max_rows = self.max_rows.value()

    def get_db_password(self) -> str:
        return self.db_password.text()


class PreferencesSection(QGroupBox):
    """Section C: App preferences."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Preferences", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        form = QFormLayout(self)

        self.theme = QComboBox()
        from app.ui.theme import THEME_NAMES

        self.theme.addItems(THEME_NAMES)
        form.addRow("Theme", self.theme)

        path_row = QHBoxLayout()
        self.history_path = QLineEdit()
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setObjectName("SecondaryButton")
        self._browse_btn.clicked.connect(self._browse_history_path)
        path_row.addWidget(self.history_path)
        path_row.addWidget(self._browse_btn)
        form.addRow("History DB path", path_row)

    def _browse_history_path(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "History Database", self.history_path.text(), "SQLite (*.sqlite)"
        )
        if path:
            self.history_path.setText(path)

    def load_from(self, settings: Settings) -> None:
        idx = self.theme.findText(settings.theme)
        if idx >= 0:
            self.theme.setCurrentIndex(idx)
        self.history_path.setText(settings.history_db_path)

    def apply_to(self, settings: Settings) -> None:
        settings.theme = self.theme.currentText()
        settings.history_db_path = self.history_path.text().strip()


class ForecastSection(QGroupBox):
    """Section D: predictive analytics (forecasting) defaults."""

    _METHODS = [
        ("auto", "Auto (best fit)"),
        ("naive", "Naive"),
        ("seasonal_naive", "Seasonal naive"),
        ("moving_average", "Moving average"),
        ("linear_trend", "Linear trend"),
        ("holt", "Holt (trend)"),
        ("holt_winters", "Holt-Winters (seasonal)"),
        ("sarima", "SARIMA"),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Forecasting (predictive analytics)", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        form = QFormLayout(self)

        self.enabled = QCheckBox("Show forecasts on time-series results by default")
        form.addRow("", self.enabled)

        self.method = QComboBox()
        for value, label in self._METHODS:
            self.method.addItem(label, value)
        form.addRow("Default method", self.method)

        self.horizon = QSpinBox()
        self.horizon.setRange(1, 36)
        self.horizon.setSingleStep(1)
        form.addRow("Default horizon (periods)", self.horizon)

        self.confidence = QComboBox()
        for pct in (80, 90, 95):
            self.confidence.addItem(f"{pct}%", pct / 100.0)
        form.addRow("Confidence interval", self.confidence)

    def load_from(self, settings: Settings) -> None:
        self.enabled.setChecked(bool(settings.forecast_enabled_by_default))
        midx = self.method.findData(settings.forecast_default_method)
        if midx >= 0:
            self.method.setCurrentIndex(midx)
        self.horizon.setValue(int(settings.forecast_default_horizon))
        cidx = self.confidence.findData(settings.forecast_confidence)
        if cidx >= 0:
            self.confidence.setCurrentIndex(cidx)

    def apply_to(self, settings: Settings) -> None:
        settings.forecast_enabled_by_default = self.enabled.isChecked()
        settings.forecast_default_method = self.method.currentData() or "auto"
        settings.forecast_default_horizon = self.horizon.value()
        settings.forecast_confidence = float(self.confidence.currentData() or 0.8)
