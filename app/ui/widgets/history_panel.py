"""Conversation history panel with favorites and delete."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.data import history_db


class HistoryRow(QWidget):
    """A single history entry: star toggle, clickable title, delete button."""

    selected = Signal(int)
    favorite_toggled = Signal(int, bool)
    deleted = Signal(int)

    def __init__(self, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._id = int(item["id"])
        self._is_fav = bool(item.get("favorite"))
        self.setObjectName("HistoryRow")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 6, 6)
        row.setSpacing(6)

        self._star = QToolButton()
        self._star.setObjectName("StarButton")
        self._star.setCheckable(True)
        self._star.setChecked(self._is_fav)
        self._star.setText("★" if self._is_fav else "☆")
        self._star.setToolTip("Favorite")
        self._star.clicked.connect(self._on_star)
        row.addWidget(self._star, alignment=Qt.AlignmentFlag.AlignTop)

        question = item["question"]
        title = question[:58] + ("…" if len(question) > 58 else "")
        ts = item["created_at"][:16].replace("T", " ")
        self._title = QPushButton(f"{title}\n{ts}")
        self._title.setObjectName("HistoryTitle")
        self._title.setCursor(Qt.CursorShape.PointingHandCursor)
        self._title.clicked.connect(lambda: self.selected.emit(self._id))
        row.addWidget(self._title, stretch=1)

        self._del = QToolButton()
        self._del.setObjectName("DeleteButton")
        self._del.setText("🗑")
        self._del.setToolTip("Delete")
        self._del.clicked.connect(lambda: self.deleted.emit(self._id))
        row.addWidget(self._del, alignment=Qt.AlignmentFlag.AlignTop)

    def _on_star(self) -> None:
        self._is_fav = not self._is_fav
        self._star.setChecked(self._is_fav)
        self._star.setText("★" if self._is_fav else "☆")
        self.favorite_toggled.emit(self._id, self._is_fav)


class HistoryPanel(QWidget):
    """Left-middle panel showing past analyses, favorites pinned to the top."""

    history_item_selected = Signal(int)
    new_conversation_requested = Signal()

    def __init__(self, history_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HistoryPanel")
        self._history_path = history_path
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        heading = QLabel("History")
        heading.setObjectName("SectionHeading")
        header.addWidget(heading)
        header.addStretch()

        self._new_btn = QPushButton("New chat")
        self._new_btn.setObjectName("GhostButton")
        self._new_btn.clicked.connect(self.new_conversation_requested.emit)
        header.addWidget(self._new_btn)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setObjectName("HistoryList")
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._list, stretch=1)

    def _add_section(self, label: str) -> None:
        from PySide6.QtGui import QColor, QFont

        item = QListWidgetItem(label.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(Qt.ItemDataRole.UserRole, "section")
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 110)
        item.setFont(font)
        item.setForeground(QColor("#94a3b8"))
        self._list.addItem(item)

    def _add_row(self, entry: dict) -> None:
        row = HistoryRow(entry)
        row.selected.connect(self.history_item_selected.emit)
        row.favorite_toggled.connect(self._on_favorite)
        row.deleted.connect(self._on_delete)
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setSizeHint(row.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, row)

    def refresh(self) -> None:
        self._list.clear()
        try:
            items = history_db.list_all_analyses(self._history_path)
        except Exception:
            items = []

        favorites = [i for i in items if i.get("favorite")]
        others = [i for i in items if not i.get("favorite")]

        if favorites:
            self._add_section("★  Favorites")
            for entry in favorites:
                self._add_row(entry)
        if others:
            self._add_section("Recent")
            for entry in others:
                self._add_row(entry)

    def _on_favorite(self, analysis_id: int, is_fav: bool) -> None:
        history_db.set_favorite(analysis_id, is_fav, self._history_path)
        self.refresh()

    def _on_delete(self, analysis_id: int) -> None:
        history_db.delete_analysis(analysis_id, self._history_path)
        self.refresh()
