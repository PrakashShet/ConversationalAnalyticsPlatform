"""Chat input panel for natural language questions."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ChatPanel(QWidget):
    """Left-bottom panel for asking questions."""

    question_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        heading = QLabel("Ask a question")
        heading.setObjectName("SectionHeading")
        layout.addWidget(heading)

        hint = QLabel("Natural language queries over your connected data")
        hint.setObjectName("SectionHint")
        layout.addWidget(hint)

        self._input = QTextEdit()
        self._input.setPlaceholderText("Ask a question about your data…")
        self._input.setMaximumHeight(96)
        layout.addWidget(self._input)

        row = QHBoxLayout()
        row.addStretch()
        self._send_btn = QPushButton("Send message")
        self._send_btn.setObjectName("PrimaryButton")
        self._send_btn.clicked.connect(self._on_send)
        row.addWidget(self._send_btn)
        layout.addLayout(row)

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(self._on_send)

    def _on_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self.question_submitted.emit(text)
        self._input.clear()
