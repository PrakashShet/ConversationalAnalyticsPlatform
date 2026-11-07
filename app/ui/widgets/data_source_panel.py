"""Data source panel — MCP connection and table selection."""

import time

from loguru import logger
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import Settings
from app.core import data_source, schema_indexer
from app.core.mcp_client import SyncMcpClient
from app.core.sql_client import DirectSqlClient
from app.data.models import SourceFingerprint


class ConnectSignals(QObject):
    # client, tables, context_md, elapsed_ms, SourceFingerprint
    finished = Signal(object, list, str, int, object)
    failed = Signal(str)


class ConnectWorker(QRunnable):
    """Background worker to connect to MCP server and introspect schema."""

    def __init__(self, settings: Settings, signals: ConnectSignals) -> None:
        super().__init__()
        self._settings = settings
        self.signals = signals

    def run(self) -> None:
        server_type = self._settings.mcp_server_type
        try:
            start = time.perf_counter()
            if server_type in ("postgres", "mysql"):
                client = DirectSqlClient(
                    readonly=self._settings.readonly,
                    max_rows=self._settings.max_rows,
                )
                logger.info("Connecting directly to {}: {}",
                            server_type, self._settings.db_url)
                client.connect(self._settings.db_url)
            else:
                client = SyncMcpClient()
                cmd = self._settings.mcp_server_command
                logger.info("Connecting to MCP server: {}", " ".join(cmd))
                client.connect(cmd)
            tables = client.list_tables()
            logger.info("Found {} tables: {}", len(tables), tables)
            table_defs = []
            for name in tables:
                info = client.describe_table(name)
                info["table"] = name
                table_defs.append(info)
            md = schema_indexer.build_context_md(table_defs)
            schema_indexer.save_context(md)
            # Identify this source now, while the introspected schema is in
            # hand — every analysis from this connection is stamped with it.
            profile = self._settings.active_profile()
            fingerprint = data_source.fingerprint(
                name=profile.name,
                kind=server_type,
                db_url=self._settings.db_url,
                table_defs=table_defs,
            )
            logger.info(
                "Data source fingerprint: {} schema={} tables={}",
                fingerprint.target, fingerprint.schema_hash, fingerprint.table_count,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self.signals.finished.emit(client, tables, md, elapsed_ms, fingerprint)
        except Exception as exc:
            logger.exception("Database connect failed")
            try:
                self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                logger.debug("Connect failed signal dropped; source no longer alive")


class DataSourcePanel(QWidget):
    """Left-top panel for database connection via MCP."""

    connected = Signal(object, list)
    disconnected = Signal()
    source_changed = Signal()

    # Display label -> settings.mcp_server_type value
    _DB_TYPES = [("PostgreSQL", "postgres"), ("MySQL", "mysql"), ("SQLite", "sqlite")]

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DataSourcePanel")
        self._settings = settings
        self._client: SyncMcpClient | None = None
        self._context_md = ""
        self._fingerprint: SourceFingerprint | None = None
        self._thread_pool = QThreadPool.globalInstance()
        self._connect_signals: ConnectSignals | None = None
        self._connect_worker: ConnectWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        heading = QLabel("Data source")
        heading.setObjectName("SectionHeading")
        layout.addWidget(heading)

        self._status_label = QLabel("Not connected")
        self._status_label.setObjectName("StatusMuted")
        layout.addWidget(self._status_label)

        self._initial_label = QLabel("")
        self._initial_label.setObjectName("SectionHint")
        self._initial_label.hide()
        layout.addWidget(self._initial_label)

        # Database-type dropdown aligned on the same row as the Connect button.
        controls_row = QHBoxLayout()
        self._db_combo = QComboBox()
        for label, _ in self._DB_TYPES:
            self._db_combo.addItem(label)
        self._select_current_db_type()
        self._db_combo.currentIndexChanged.connect(self._on_db_type_changed)
        controls_row.addWidget(self._db_combo, stretch=1)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("PrimaryButton")
        self._connect_btn.clicked.connect(self._on_connect)
        controls_row.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("SecondaryButton")
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        self._disconnect_btn.hide()
        controls_row.addWidget(self._disconnect_btn)
        layout.addLayout(controls_row)

        self._error_label = QLabel("")
        self._error_label.setObjectName("StatusError")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        layout.addWidget(self._error_label)

        self._tables_list = QListWidget()
        layout.addWidget(self._tables_list, stretch=1)

        # Collapsible data-context document (built by Gemini after connecting).
        self._context_toggle = QToolButton()
        self._context_toggle.setObjectName("SqlToggle")
        self._context_toggle.setText("▸  Data context")
        self._context_toggle.setCheckable(True)
        self._context_toggle.hide()
        self._context_toggle.toggled.connect(self._on_context_toggle)
        layout.addWidget(self._context_toggle)

        self._context_view = QTextBrowser()
        self._context_view.setObjectName("ContextView")
        self._context_view.hide()
        layout.addWidget(self._context_view, stretch=2)

    def set_initial_analysis_time(self, text: str) -> None:
        """Show when the first (connect-time) analytics was generated."""
        self._initial_label.setText(f"Initial analysis · {text}")
        self._initial_label.show()

    def show_context(self, markdown_text: str) -> None:
        """Display the Gemini-built data-context document in the panel."""
        self._context_view.setMarkdown(markdown_text)
        self._context_toggle.show()
        self._context_toggle.setChecked(True)

    def _on_context_toggle(self, checked: bool) -> None:
        self._context_view.setVisible(checked)
        self._context_toggle.setText(
            "▾  Data context" if checked else "▸  Data context"
        )

    def _set_status(self, text: str, object_name: str) -> None:
        """Set status text + style, repolishing so the QSS color applies."""
        self._status_label.setText(text)
        self._status_label.setObjectName(object_name)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _select_current_db_type(self) -> None:
        """Set the combo to match settings.mcp_server_type without firing the slot."""
        current = self._settings.mcp_server_type
        index = next(
            (i for i, (_, val) in enumerate(self._DB_TYPES) if val == current), 0
        )
        self._db_combo.blockSignals(True)
        self._db_combo.setCurrentIndex(index)
        self._db_combo.blockSignals(False)

    def refresh_source(self) -> None:
        """Public hook for MainWindow after the settings dialog edits the source."""
        self._select_current_db_type()

    def _reset_connection_ui(self) -> None:
        self._set_status("Not connected", "StatusMuted")
        self._tables_list.clear()
        self._client = None
        self._fingerprint = None
        self._connect_btn.setText("Connect")
        self._disconnect_btn.hide()
        self._error_label.hide()
        self._context_toggle.hide()
        self._context_view.hide()
        self._context_view.clear()
        self._initial_label.hide()

    def _on_db_type_changed(self, index: int) -> None:
        if index < 0:
            return
        self._settings.mcp_server_type = self._DB_TYPES[index][1]
        self._settings.save()
        old = self._client
        self._reset_connection_ui()
        self.source_changed.emit()
        if old is not None:
            try:
                old.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass

    def _on_disconnect(self) -> None:
        # Invalidate in-flight workers first (MainWindow bumps connection gen),
        # then close the SQL client so stale workers fail quietly.
        client = self._client
        self._reset_connection_ui()
        self.disconnected.emit()
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass

    @property
    def client(self) -> SyncMcpClient | None:
        return self._client

    @property
    def context_md(self) -> str:
        return self._context_md

    @property
    def fingerprint(self) -> SourceFingerprint | None:
        """Identity of the live connection, or ``None`` when not connected."""
        return self._fingerprint

    def _on_connect(self) -> None:
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Connecting…")
        self._error_label.hide()

        # Keep a strong ref so ConnectSignals is not GC'd before the worker emits.
        self._connect_signals = ConnectSignals(self)
        self._connect_signals.finished.connect(self._on_connected)
        self._connect_signals.failed.connect(self._on_connect_failed)

        worker = ConnectWorker(self._settings, self._connect_signals)
        self._connect_worker = worker
        self._thread_pool.start(worker)

    @Slot(object, list, str, int, object)
    def _on_connected(
        self,
        client: SyncMcpClient,
        tables: list,
        context_md: str,
        elapsed_ms: int,
        fingerprint: SourceFingerprint | None = None,
    ) -> None:
        old = self._client
        self._client = client
        self._context_md = context_md
        self._fingerprint = fingerprint
        self._set_status(f"Live · {elapsed_ms} ms", "StatusOk")
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Reconnect")
        self._disconnect_btn.show()
        self._connect_worker = None

        self._tables_list.clear()
        for name in tables:
            item = QListWidgetItem()
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)
            self._tables_list.addItem(item)
            self._tables_list.setItemWidget(item, checkbox)

        tables_in_scope = tables
        self.connected.emit(client, tables_in_scope)

        # Close the previous client only after the UI has switched over. In-flight
        # workers from the old session are invalidated by MainWindow's connection
        # generation counter.
        if old is not None and old is not client:
            try:
                old.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass

    @Slot(str)
    def _on_connect_failed(self, message: str) -> None:
        self._connect_worker = None
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Connect")
        self._disconnect_btn.hide()
        self._set_status("Not connected", "StatusMuted")
        self._error_label.setText(message)
        self._error_label.show()

    def get_selected_tables(self) -> list[str]:
        selected = []
        for i in range(self._tables_list.count()):
            item = self._tables_list.item(i)
            widget = self._tables_list.itemWidget(item)
            if isinstance(widget, QCheckBox) and widget.isChecked():
                selected.append(widget.text())
        return selected

    def set_connecting(self, connecting: bool) -> None:
        self._connect_btn.setEnabled(not connecting)
        self._connect_btn.setText("Connecting…" if connecting else "Connect")
