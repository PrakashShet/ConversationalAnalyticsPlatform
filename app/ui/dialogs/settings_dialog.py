"""Settings dialog — configuration form."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.config import keychain
from app.config.settings import Settings
from app.ui.dialogs._sections import (
    ApiSection,
    ForecastSection,
    McpSection,
    PreferencesSection,
)


class SettingsDialog(QDialog):
    """Modal dialog for app configuration."""

    settings_saved = Signal()

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self._settings = settings.model_copy(deep=True)
        self.setWindowTitle("Settings — Configuration")
        self.resize(620, 600)
        self._build_ui()
        self._load_values()
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.reject)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("SettingsHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 16, 20, 12)
        title = QLabel("Settings")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("Manage API keys, database connection, and app preferences")
        subtitle.setObjectName("DialogSubtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container.setObjectName("SettingsBody")
        form_layout = QVBoxLayout(container)
        form_layout.setContentsMargins(20, 8, 20, 16)
        form_layout.setSpacing(12)

        self._api_section = ApiSection()
        self._mcp_section = McpSection()
        self._prefs_section = PreferencesSection()
        self._forecast_section = ForecastSection()
        form_layout.addWidget(self._api_section)
        form_layout.addWidget(self._mcp_section)
        form_layout.addWidget(self._prefs_section)
        form_layout.addWidget(self._forecast_section)
        form_layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll, stretch=1)

        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 12, 20, 16)

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.clicked.connect(self._test_connection)
        footer_layout.addWidget(self._test_btn)

        self._test_result = QLabel("")
        footer_layout.addWidget(self._test_result)
        footer_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        footer_layout.addWidget(cancel_btn)
        footer_layout.addWidget(save_btn)
        outer.addWidget(footer)

    def _load_values(self) -> None:
        api_key = keychain.get_secret("gemini_api_key") or ""
        db_password = keychain.get_secret("db_password") or ""
        self._api_section.load_from(self._settings, api_key)
        self._mcp_section.load_from(self._settings, db_password)
        self._prefs_section.load_from(self._settings)
        self._forecast_section.load_from(self._settings)

    def _set_test_result(self, ok: bool, message: str) -> None:
        self._test_result.setObjectName("TestOk" if ok else "TestError")
        self._test_result.setText(message)

    def _test_connection(self) -> None:
        server_type = self._mcp_section.server_type.currentText()
        if server_type == "sqlite":
            cmd = self._mcp_section.server_command.text()
            db_path = None
            parts = cmd.split()
            for i, part in enumerate(parts):
                if part == "--db-path" and i + 1 < len(parts):
                    db_path = parts[i + 1]
                    break
            if db_path and Path(db_path).exists():
                self._set_test_result(True, "✓ Connected · database file found")
            else:
                self._set_test_result(False, "✗ Database file not found")
        else:
            self._set_test_result(True, "✓ Connection test available in Stage 3")

    def _save(self) -> None:
        api_key = self._api_section.get_api_key()
        server_type = self._mcp_section.server_type.currentText()
        if not api_key and server_type != "sqlite":
            self._set_test_result(False, "API key is required for remote databases")
            return

        if api_key:
            keychain.set_secret("gemini_api_key", api_key)

        db_password = self._mcp_section.get_db_password()
        if db_password:
            keychain.set_secret("db_password", db_password)

        self._settings.gemini_model = self._api_section.get_model()
        self._settings.max_tokens = self._api_section.get_max_tokens()
        self._mcp_section.apply_to(self._settings)
        self._prefs_section.apply_to(self._settings)
        self._forecast_section.apply_to(self._settings)
        self._sync_active_profile()
        self._settings.save()

        self.settings_saved.emit()
        self.accept()

    def _sync_active_profile(self) -> None:
        """Mirror the edited connection fields back into the active profile."""
        profile = self._settings.active_profile()
        profile.mcp_server_type = self._settings.mcp_server_type
        profile.mcp_server_command = list(self._settings.mcp_server_command)
        profile.db_url = self._settings.db_url
        profile.ssl_mode = self._settings.ssl_mode
        profile.readonly = self._settings.readonly
        profile.max_rows = self._settings.max_rows

    @property
    def settings(self) -> Settings:
        return self._settings
