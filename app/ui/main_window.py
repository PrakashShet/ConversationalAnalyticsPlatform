"""Main application window."""

from loguru import logger

from app.paths import app_dir
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.config import keychain
from app.config.settings import Settings
from app.core import data_source
from app.core.gemini_client import GeminiClient
from app.core.orchestrator import Orchestrator
from app.data import history_db
from app.ui.dialogs import notices
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.widgets.banner import Banner
from app.ui.widgets.canvas_panel import CanvasPanel
from app.ui.widgets.chat_panel import ChatPanel
from app.ui.widgets.data_source_panel import DataSourcePanel
from app.ui.widgets.history_panel import HistoryPanel
from app.ui.workers.analysis_worker import AnalysisWorker


class MainWindow(QMainWindow):
    """Three-pane layout: data source / history / chat on left, canvas on right."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self._orchestrator: Orchestrator | None = None
        self._mcp_client = None
        self._gemini = None
        self._awaiting_initial = False
        self._context_md = ""
        self._source = None
        self._chat_history: list[dict] = []
        self._thread_pool = QThreadPool.globalInstance()
        self._current_conv_id: int | None = None
        self._banner: Banner | None = None
        # Bumped on connect/disconnect so in-flight workers from a prior session
        # are ignored (and don't crash after the SQL client is closed).
        self._connection_gen = 0
        self._active_workers: set[AnalysisWorker] = set()
        self._active_context_workers: set = set()

        history_db.init_db(self.settings.history_db_path)
        self._current_conv_id = history_db.new_conversation(
            "New conversation", self.settings.history_db_path
        )

        self.setWindowTitle("AI-Powered Conversational Analytics Platform")
        self.resize(1360, 820)
        self._apply_theme()
        self._build_layout()
        self._wire_shortcuts()
        self._canvas.show_empty_state(connected=False)

    def _build_header(self) -> QWidget:
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import (
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QToolButton,
        )

        header = QFrame()
        header.setObjectName("AppHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(14, 8, 20, 8)
        h.setSpacing(10)

        # Collapse / expand the sidebar.
        self._toggle_btn = QToolButton()
        self._toggle_btn.setObjectName("ToggleButton")
        self._toggle_btn.setText("◀")  # arrow points toward the panel (collapse)
        self._toggle_btn.setToolTip("Collapse panel")
        self._toggle_btn.setFixedWidth(40)
        self._toggle_btn.clicked.connect(self._toggle_sidebar)
        h.addWidget(self._toggle_btn)

        # Balance the right-side Settings button so the title stays centered.
        left_pad = QWidget()
        left_pad.setFixedWidth(120 - 40 - 10)
        h.addWidget(left_pad)
        h.addStretch()

        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(2)
        title = QLabel("AI-Powered Conversational Analytics Platform")
        title.setObjectName("AppTitle")
        title.setAlignment(_Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Natural language analytics over your SQL data")
        subtitle.setObjectName("AppSubtitle")
        subtitle.setAlignment(_Qt.AlignmentFlag.AlignCenter)
        brand_layout.addWidget(title)
        brand_layout.addWidget(subtitle)
        h.addWidget(brand)

        h.addStretch()

        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("GhostButton")
        settings_btn.setFixedWidth(120)
        settings_btn.clicked.connect(self._open_settings)
        h.addWidget(settings_btn)

        return header

    def _toggle_sidebar(self) -> None:
        collapsed = self._sidebar.isVisible()
        self._sidebar.setVisible(not collapsed)
        # Arrow always points toward the panel: ▶ to expand, ◀ to collapse.
        self._toggle_btn.setText("▶" if collapsed else "◀")
        self._toggle_btn.setToolTip("Expand panel" if collapsed else "Collapse panel")

    def _build_layout(self) -> None:
        self._data_source = DataSourcePanel(self.settings)
        self._history = HistoryPanel(self.settings.history_db_path)
        self._chat = ChatPanel()
        self._canvas = CanvasPanel()

        self._data_source.connected.connect(self._on_mcp_connected)
        self._data_source.source_changed.connect(self._on_source_changed)
        self._data_source.disconnected.connect(self._on_disconnected)
        self._chat.question_submitted.connect(self._on_question)
        self._canvas.refresh_requested.connect(self._on_derived_question)
        self._canvas.export_requested.connect(self._on_export)
        self._canvas.drilldown_requested.connect(self._on_drilldown)
        self._canvas.suggestion_clicked.connect(self._on_derived_question)
        self._history.history_item_selected.connect(self._on_history_selected)
        self._history.new_conversation_requested.connect(self._on_new_conversation)

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(self._data_source)
        left_splitter.addWidget(self._history)
        left_splitter.addWidget(self._chat)
        left_splitter.setSizes([320, 400, 200])
        left_splitter.setStretchFactor(0, 0)
        left_splitter.setStretchFactor(1, 1)
        left_splitter.setStretchFactor(2, 0)

        self._sidebar = QWidget()
        self._sidebar.setObjectName("Sidebar")
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(left_splitter)

        # Right column: header on top, canvas below.
        right_column = QWidget()
        right_column.setObjectName("CentralRoot")
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_header())
        right_layout.addWidget(self._canvas, stretch=1)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(self._sidebar)
        main_splitter.addWidget(right_column)
        main_splitter.setSizes([400, 960])
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)

        self.setCentralWidget(main_splitter)

    def _wire_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+,"), self, self._open_settings)
        QShortcut(QKeySequence("Ctrl+N"), self, self._on_new_conversation)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        dialog.settings_saved.connect(self._on_settings_saved)
        dialog.exec()

    def _on_settings_saved(self) -> None:
        self.settings = Settings.load()
        self._apply_theme()

    def _apply_theme(self) -> None:
        from PySide6.QtWidgets import QApplication

        from app.ui.theme import apply_app_theme

        app = QApplication.instance()
        if app is not None:
            apply_app_theme(app, getattr(self.settings, "theme", "paper"))

    def _on_mcp_connected(self, client, tables: list) -> None:
        self._connection_gen += 1
        gen = self._connection_gen
        self._mcp_client = client

        # Reconnecting to a *different* source (profile or URL switched, or the
        # schema was reloaded) starts a clean session: the previous database's
        # Q&A must not leak into this one's planner prompt, and results from
        # two databases must not share one conversation.
        incoming = self._data_source.fingerprint
        if self._source is not None and data_source.compare(self._source, incoming):
            logger.info(
                "Data source changed on reconnect ({} → {}); starting a new "
                "conversation",
                data_source.describe(self._source),
                data_source.describe(incoming),
            )
            self._chat_history = []
            self._current_conv_id = history_db.new_conversation(
                "New conversation", self.settings.history_db_path
            )
            self._history.refresh()

        context_path = app_dir() / "data" / "context.md"
        if context_path.exists():
            self._context_md = context_path.read_text(encoding="utf-8")
        else:
            self._context_md = self._data_source.context_md

        api_key = keychain.get_secret("gemini_api_key") or ""
        self._gemini = GeminiClient(
            api_key=api_key,
            model=self.settings.gemini_model,
            max_tokens=self.settings.max_tokens,
        )
        self._source = self._data_source.fingerprint
        self._orchestrator = Orchestrator(
            self._gemini,
            client,
            self._context_md,
            source=self._source,
            forecast_enabled=self.settings.forecast_enabled_by_default,
            forecast_method=self.settings.forecast_default_method,
            forecast_horizon=self.settings.forecast_default_horizon,
            forecast_confidence=self.settings.forecast_confidence,
        )
        self._clear_banner()
        logger.info("Connected, {} tables in scope", len(tables))

        # 1. Build a detailed data-context document via Gemini (shown in the
        #    connect panel) using sample rows from the live connection.
        from app.ui.workers.context_worker import ContextWorker

        ctx_worker = ContextWorker(
            self._gemini,
            client,
            self._context_md,
            list(tables),
            connection_gen=gen,
            is_current=lambda g=gen: self._connection_gen == g,
            parent=self,
        )
        self._active_context_workers.add(ctx_worker)
        ctx_worker.signals.ready.connect(
            lambda md, w=ctx_worker: self._on_context_ready(md, w)
        )
        ctx_worker.signals.failed.connect(
            lambda msg, w=ctx_worker: self._on_context_failed(msg, w)
        )
        self._thread_pool.start(ctx_worker)

        # 2. At the same time, fill the right panel with default descriptive
        #    analytics for the connected dataset.
        self._run_default_analytics()

    def _on_context_ready(self, context_md: str, worker=None) -> None:
        if worker is not None:
            self._active_context_workers.discard(worker)
        if worker is not None and worker.connection_gen != self._connection_gen:
            return
        if not context_md.strip():
            return
        self._context_md = context_md
        ctx_path = app_dir() / "data" / "context.md"
        ctx_path.parent.mkdir(parents=True, exist_ok=True)
        ctx_path.write_text(context_md, encoding="utf-8")
        if self._orchestrator:
            self._orchestrator.set_context(context_md)
        self._data_source.show_context(context_md)
        logger.info("Data-context document ready ({} chars)", len(context_md))

    def _on_context_failed(self, message: str, worker=None) -> None:
        if worker is not None:
            self._active_context_workers.discard(worker)
        if worker is not None and worker.connection_gen != self._connection_gen:
            return
        logger.warning("Context build failed: {}", message)

    def _run_default_analytics(self) -> None:
        self._awaiting_initial = True
        question = (
            "Give a high-level descriptive analytics overview of this dataset: "
            "the most important totals as KPIs, a chart of the main breakdown, "
            "and 3-4 notable insights."
        )
        self._on_question(question)

    def _on_derived_question(self, question: str) -> None:
        """A question derived from whatever is on screen.

        Suggested follow-ups, chart drill-downs and Refresh all belong to the
        *displayed* analysis. When that analysis was saved against a different
        database — or the connected one has been reloaded since — answering it
        silently against the live connection would produce a confident,
        unrelated result. So the mismatch is raised as a modal first.

        Questions typed into the chat box do not go through here; they are new
        questions about the current data, not follow-ups to an old one.
        """
        if not question.strip():
            return
        if self._orchestrator and not self._confirm_source_for_displayed():
            logger.info("Follow-up cancelled: data source mismatch")
            return
        self._on_question(question)

    def _confirm_source_for_displayed(self) -> bool:
        """Check the displayed analysis against the live connection.

        ``True`` to proceed. Only prompts when there is something to say — a
        matching fingerprint passes silently.
        """
        analysis = self._canvas.current_analysis
        if analysis is None:
            return True
        reason = data_source.compare(analysis.source, self._source)
        if reason is None:
            return True
        logger.info(
            "Source mismatch ({}): saved={} current={}",
            reason,
            data_source.describe(analysis.source),
            data_source.describe(self._source),
        )
        return notices.confirm_source_mismatch(
            self, reason, analysis.source, self._source
        )

    def _on_question(self, question: str) -> None:
        if not question.strip():
            return
        if not self._orchestrator:
            notices.not_connected(self)
            return

        api_key = keychain.get_secret("gemini_api_key")
        if not api_key:
            if notices.missing_api_key(self):
                self._open_settings()
            return

        self._clear_banner()
        self._canvas.set_question_header(question)
        self._canvas.show_loading()

        gen = self._connection_gen
        worker = AnalysisWorker(
            self._orchestrator,
            question,
            list(self._chat_history),
            connection_gen=gen,
            is_current=lambda g=gen: self._connection_gen == g,
            parent=self,
        )
        self._active_workers.add(worker)
        worker.signals.summary_streamed.connect(self._canvas.show_stream_summary)
        worker.signals.finished.connect(
            lambda result, w=worker: self._on_analysis_finished(result, w)
        )
        worker.signals.failed.connect(
            lambda message, w=worker: self._on_analysis_failed(message, w)
        )
        self._thread_pool.start(worker)

    def _reset_session_state(self) -> None:
        """Drop everything tied to the connection that is going away.

        Chat history and the open conversation are per–data source. Carrying
        them across a switch would feed one database's Q&A into the other's
        planner prompt as context, and file results from both under a single
        conversation.
        """
        self._connection_gen += 1
        self._orchestrator = None
        self._mcp_client = None
        self._context_md = ""
        self._source = None
        self._awaiting_initial = False
        self._chat_history = []
        self._current_conv_id = history_db.new_conversation(
            "New conversation", self.settings.history_db_path
        )
        self._history.refresh()

    def _on_disconnected(self) -> None:
        self._reset_session_state()
        self._clear_banner()
        self._canvas.show_empty_state(connected=False)
        logger.info("Disconnected from database")

    def _on_source_changed(self) -> None:
        # Changing the database type drops the live connection; user reconnects.
        self._reset_session_state()
        self._canvas.show_empty_state(connected=False)
        db_type = self.settings.mcp_server_type
        logger.info("Database type changed to '{}'", db_type)
        self._show_banner(
            "orange", f"Database type '{db_type}' selected — click Connect to use it."
        )

    def _on_drilldown(self, category: str) -> None:
        category = (category or "").strip()
        if not category:
            return
        logger.info("Drill-down requested for '{}'", category)
        # Derived from the displayed chart, so it goes through the source gate.
        self._on_derived_question(f"Drill into {category}")

    def _on_export(self, analysis) -> None:
        from app.core.report_export import export_report

        default_name = "analysis.html"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export analysis", default_name, "HTML files (*.html)"
        )
        if not path:
            return
        try:
            out = export_report(analysis, path)
        except OSError as exc:
            logger.error("Export failed: {}", exc)
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        logger.info("Exported analysis to {}", out)
        QMessageBox.information(
            self, "Exported", f"Saved report to:\n{out}"
        )

    def _on_analysis_finished(self, analysis, worker=None) -> None:
        if worker is not None:
            self._active_workers.discard(worker)
            if worker.connection_gen != self._connection_gen:
                logger.info("Ignoring stale analysis from a previous connection")
                return
        self._canvas.render(analysis)
        was_initial = self._awaiting_initial
        # The planner could not map the question onto the connected schema —
        # the canvas shows only a rationale, which reads like a real answer.
        if analysis.needs_clarification and not was_initial:
            notices.question_not_answerable(self, analysis.summary)
        # A forecast was explicitly asked for but the result isn't a series —
        # say why rather than quietly returning a descriptive answer.
        elif (
            analysis.forecast_requested
            and not analysis.forecastable
            and analysis.forecast_note
            and not was_initial
        ):
            notices.forecast_unavailable(self, analysis.forecast_note)
        if self._awaiting_initial:
            self._awaiting_initial = False
            from datetime import datetime

            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._data_source.set_initial_analysis_time(stamp)
            logger.info("Initial analytics generated at {}", stamp)
        self._chat_history.append({"role": "user", "content": analysis.question})
        self._chat_history.append({
            "role": "assistant",
            "content": analysis.summary,
        })
        if len(self._chat_history) > 12:
            self._chat_history = self._chat_history[-12:]

        if self._current_conv_id:
            history_db.save_analysis(
                self._current_conv_id, analysis, self.settings.history_db_path
            )
            self._history.refresh()
        logger.info("Analysis complete: {} rows", analysis.row_count)

    def _on_analysis_failed(self, message: str, worker=None) -> None:
        if worker is not None:
            self._active_workers.discard(worker)
            if worker.connection_gen != self._connection_gen:
                logger.info("Ignoring stale analysis failure from a previous connection")
                return
        was_initial = self._awaiting_initial
        self._awaiting_initial = False
        logger.error("Analysis failed: {}", message)
        # Keep the canvas message for context, then surface it as a modal so it
        # cannot be missed when the canvas is scrolled.
        self._canvas.show_error(message)
        if was_initial:
            # The automatic overview on connect — a modal here would ambush the
            # user before they have asked anything.
            self._show_banner("warning", "Could not build the initial overview.")
            return
        low = message.lower()
        if "401" in low or "403" in low or "api key" in low or "authentic" in low:
            if notices.missing_api_key(self):
                self._open_settings()
            return
        notices.analysis_failed(self, message)

    def _on_history_selected(self, analysis_id: int) -> None:
        try:
            analysis = history_db.get_analysis(
                analysis_id, self.settings.history_db_path
            )
            self._canvas.render(analysis)
            logger.info("Rendered history item {} without API call", analysis_id)
        except KeyError as exc:
            self._canvas.show_error(str(exc))

    def _on_new_conversation(self) -> None:
        self._chat_history = []
        self._current_conv_id = history_db.new_conversation(
            "New conversation", self.settings.history_db_path
        )
        connected = self._orchestrator is not None
        self._canvas.show_empty_state(connected=connected)
        self._history.refresh()

    def _show_banner(self, kind: str, message: str, action: str | None = None) -> None:
        self._clear_banner()
        self._banner = Banner(kind, message, action, self._canvas)
        layout = self._canvas.layout()
        if layout:
            layout.insertWidget(0, self._banner)

    def _clear_banner(self) -> None:
        if self._banner:
            self._banner.deleteLater()
            self._banner = None
