# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — onedir build with PySide6 + Qt WebEngine.

Two things this spec deliberately does *not* do:

**No ``collect_all("PySide6")``.** PyInstaller ships its own PySide6 hooks, and
they already pull QtWebEngine's helper process, resources and locales when
``PySide6.QtWebEngineWidgets`` is imported. Calling ``collect_all`` on top of
that bundles every Qt module in the wheel — Designer, Quick3D, 3D, Bluetooth,
sensors — and produced an 821 MB build. Worse, collecting the same DLLs twice
by two different routes is a classic source of a build that runs from source
but dies silently as a frozen exe.

**No blanket DLL removal.** QtWebEngine genuinely needs Qt6Quick, Qt6Qml,
Qt6QuickWidgets, Qt6WebChannel, Qt6Positioning and Qt6Network, and the FFmpeg
DLLs are linked by Qt6WebEngineCore. Only modules with no path to the app or to
WebEngine are dropped — see ``_DROP_QT_MODULES``.

Set ``CONV_BUILD_DEBUG=1`` to build a console executable, so a startup failure
prints instead of vanishing.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
DEBUG = os.environ.get("CONV_BUILD_DEBUG") == "1"

# --- application assets (paths mirror app.paths.resource_path) --------------

datas = [
    (str(ROOT / "app" / "ui" / "styles.qss"), "app/ui"),
    (str(ROOT / "app" / "ui" / "charts" / "chart_shell.html"), "app/ui/charts"),
    (str(ROOT / "app" / "resources" / "prompts"), "app/resources/prompts"),
    (str(ROOT / "app" / "resources" / "vendor"), "app/resources/vendor"),
]

# Fail the build loudly rather than shipping an exe that cannot find a prompt.
for src, _dest in datas:
    if not Path(src).exists():
        raise SystemExit(f"conv_analytics.spec: missing required asset: {src}")

binaries = []

# --- imports PyInstaller cannot see statically ------------------------------

hiddenimports = [
    # Qt: imported lazily inside functions, so static analysis misses them.
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
    "PySide6.QtCharts",
    # SQLAlchemy resolves its dialect by URL string at runtime.
    "sqlalchemy.dialects.postgresql.psycopg2",
    "sqlalchemy.dialects.mysql.pymysql",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "psycopg2",
    "psycopg2._psycopg",
    # keyring picks its backend by platform at runtime.
    "keyring.backends.Windows",
    "keyring.backends.fail",
]

# google-genai and the MCP client both import submodules dynamically. Guard
# each one: a missing optional package must not abort the whole build.
for _pkg in ("google.genai", "mcp.client"):
    try:
        hiddenimports += collect_submodules(_pkg)
    except Exception as _exc:                       # noqa: BLE001
        print(f"conv_analytics.spec: skipping {_pkg} ({_exc})")

# statsmodels is optional at runtime (forecasting degrades without it), but if
# it is installed we want the whole tsa subtree, which is full of lazy imports.
try:
    import statsmodels  # noqa: F401

    hiddenimports += collect_submodules("statsmodels.tsa")
    datas += collect_data_files("statsmodels", includes=["**/*.csv", "**/*.json"])
except ImportError:
    pass

# --- excludes ---------------------------------------------------------------

excludes = [
    # Test frameworks and bundled test data. `unittest` is deliberately NOT
    # excluded — numpy.testing imports it, and several libraries import that.
    "pytest", "_pytest",
    "pandas.tests", "numpy.tests", "statsmodels.tests", "scipy.io.tests",
    # Only used by the docs build and the data downloader, never by the app.
    "matplotlib", "graphviz", "kagglehub", "PIL", "tkinter",
    # Notebook stack occasionally dragged in by pandas.
    "IPython", "jupyter", "notebook", "nbformat", "sphinx", "docutils",
]
# Note: mcp.server is *not* excluded. Only the stdio client is used, but
# mcp/__init__.py re-exports server types, so excluding it breaks `import mcp`.

# Qt modules with no path to this app and none to QtWebEngine.
# Careful: Quick, Qml, QuickWidgets, WebChannel, Positioning, Network and the
# FFmpeg DLLs are all WebEngine dependencies and must stay.
_DROP_QT_MODULES = (
    "Qt6Designer", "Qt6DesignerComponents", "Qt6UiTools",
    "Qt63D", "Qt6Quick3D", "Qt6DataVisualization",
    "Qt6Bluetooth", "Qt6Nfc", "Qt6SerialPort", "Qt6SerialBus", "Qt6Sensors",
    "Qt6TextToSpeech", "Qt6RemoteObjects", "Qt6Scxml", "Qt6StateMachine",
    "Qt6Help", "Qt6Test", "Qt6Sql", "Qt6Location",
    "Qt6Multimedia",          # WebEngine uses FFmpeg directly, not QtMultimedia
    "Qt6SpatialAudio",
)


def _keep_binary(entry) -> bool:
    name = Path(entry[0]).name
    return not name.startswith(_DROP_QT_MODULES)


def _keep_data(entry) -> bool:
    dest = entry[0].replace("\\", "/")
    name = Path(dest).name
    # Chromium ships debug copies of every resource pack — ~78 MB unused.
    if name.endswith(".debug.pak"):
        return False
    if name.startswith("qtwebengine_devtools_resources"):
        return False
    # Qt and Chromium translations: keep English only.
    if "/qtwebengine_locales/" in dest and not name.startswith("en-US"):
        return False
    if "/translations/" in dest and name.endswith(".qm"):
        return name.startswith(("qt_en", "qtbase_en"))
    return True


a = Analysis(
    [str(ROOT / "entry_point.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "pyi_runtime_hook.py")],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Plain lists, not TOC(): the TOC class is deprecated in PyInstaller 6 and
# a.binaries / a.datas are ordinary lists there.
a.binaries = [e for e in a.binaries if _keep_binary(e)]
a.datas = [e for e in a.datas if _keep_data(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ConvAnalytics",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A windowed build hides startup errors completely. CONV_BUILD_DEBUG=1
    # produces a console build so the traceback is visible.
    console=DEBUG,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ConvAnalytics",
)
