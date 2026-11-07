"""Shared Qt stylesheet loading with selectable accent themes.

The base stylesheet (styles.qss) is a light "paper" theme built around an indigo
accent. Additional themes remap only the accent-color family — buttons, badges,
highlights, links — leaving surfaces and text untouched, so contrast is always
safe.

The app is light-only. A light palette is applied alongside the stylesheet so
that any widget the stylesheet does not name — dialogs, menus, popups — still
gets readable colours instead of inheriting the operating system's dark theme.
Without it, a message box on a dark-mode Windows renders near-white text on its
light surface and is effectively invisible.
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.paths import resource_path

_STYLES_PATH = resource_path("ui", "styles.qss")

# theme name -> {original accent hex: replacement hex}
THEMES: dict[str, dict[str, str]] = {
    "paper": {},  # default indigo, no remap
    "ocean": {
        "#6366f1": "#0ea5e9",
        "#4f46e5": "#0284c7",
        "#4338ca": "#0369a1",
        "#eef2ff": "#e0f2fe",
        "#e0e7ff": "#bae6fd",
        "#c7d2fe": "#bae6fd",
        "#3730a3": "#075985",
    },
    "emerald": {
        "#6366f1": "#10b981",
        "#4f46e5": "#059669",
        "#4338ca": "#047857",
        "#eef2ff": "#ecfdf5",
        "#e0e7ff": "#d1fae5",
        "#c7d2fe": "#a7f3d0",
        "#3730a3": "#065f46",
    },
}

THEME_NAMES = list(THEMES.keys())


def read_stylesheet() -> str:
    return _STYLES_PATH.read_text(encoding="utf-8")


def build_stylesheet(theme: str = "paper") -> str:
    qss = read_stylesheet()
    for original, replacement in THEMES.get(theme, {}).items():
        qss = qss.replace(original, replacement)
        qss = qss.replace(original.upper(), replacement)
    return qss


# Surface and text colours from the stylesheet header, kept in sync by hand.
_PALETTE_COLORS = {
    "window": "#f1f5f9",       # app shell
    "surface": "#ffffff",      # cards, inputs, dialogs
    "alt_surface": "#f8fafc",  # sidebar, alternating rows
    "text": "#0f172a",         # primary
    "text_muted": "#94a3b8",   # placeholders, disabled
    "accent": "#6366f1",       # selection
    "on_accent": "#ffffff",
    "tooltip_bg": "#0f172a",
    "tooltip_text": "#f8fafc",
}


def light_palette(theme: str = "paper") -> QPalette:
    """A fully-specified light palette — no role left to the OS default."""
    remap = THEMES.get(theme, {})
    c = {k: QColor(remap.get(v, v)) for k, v in _PALETTE_COLORS.items()}

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, c["window"])
    palette.setColor(QPalette.ColorRole.WindowText, c["text"])
    palette.setColor(QPalette.ColorRole.Base, c["surface"])
    palette.setColor(QPalette.ColorRole.AlternateBase, c["alt_surface"])
    palette.setColor(QPalette.ColorRole.Text, c["text"])
    palette.setColor(QPalette.ColorRole.Button, c["alt_surface"])
    palette.setColor(QPalette.ColorRole.ButtonText, c["text"])
    palette.setColor(QPalette.ColorRole.BrightText, c["on_accent"])
    palette.setColor(QPalette.ColorRole.ToolTipBase, c["tooltip_bg"])
    palette.setColor(QPalette.ColorRole.ToolTipText, c["tooltip_text"])
    palette.setColor(QPalette.ColorRole.Highlight, c["accent"])
    palette.setColor(QPalette.ColorRole.HighlightedText, c["on_accent"])
    palette.setColor(QPalette.ColorRole.PlaceholderText, c["text_muted"])
    palette.setColor(QPalette.ColorRole.Link, c["accent"])
    palette.setColor(QPalette.ColorRole.LinkVisited, c["accent"])

    # Disabled state, or Qt greys it against the wrong base.
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, c["text_muted"])
    palette.setColor(disabled, QPalette.ColorRole.Text, c["text_muted"])
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, c["text_muted"])
    return palette


def apply_app_theme(app: QApplication, theme: str = "paper") -> None:
    """Apply the selected theme to the entire application.

    Order matters: the palette is the floor for widgets the stylesheet never
    names (message boxes, menus, popups), and the stylesheet then overrides it
    wherever it does.
    """
    app.setPalette(light_palette(theme))
    app.setStyleSheet(build_stylesheet(theme))
