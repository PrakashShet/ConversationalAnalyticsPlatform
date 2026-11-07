"""Reusable error/info banner widget."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class Banner(QFrame):
    """Non-blocking banner for errors and actions."""

    action_clicked = Signal()

    def __init__(
        self,
        kind: str,
        message: str,
        action: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        self._label = QLabel(message)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, stretch=1)

        if action:
            btn = QPushButton(action)
            btn.setObjectName("SecondaryButton")
            btn.clicked.connect(self.action_clicked.emit)
            layout.addWidget(btn)

    def set_message(self, message: str) -> None:
        self._label.setText(message)
