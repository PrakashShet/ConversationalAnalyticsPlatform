# Conv-Analytics — Implementation Plan for Cursor Composer 2.5

> A PySide6 desktop app for conversational analytics over a SQL database via MCP,
> powered by the Google Gemini API (Gemini 3.5 Flash). Modular architecture, Windows-friendly (`setup.bat` / `run.bat`),
> built stage-by-stage so each stage is one Composer 2.5 session.

---

## How to use this plan

1. Open Cursor in an empty folder (e.g. `conv-analytics/`).
2. Work through stages **in order**. Each stage has:
   - **Goal** — what you'll have when done
   - **Files** — exact paths Composer should create/modify
   - **Composer 2.5 prompt** — copy/paste into Composer
   - **Verify** — run a command or click something; if green, move on
3. After each stage: commit to git. Stages are intentionally small so you can roll back.
4. Don't skip ahead. Composer 2.5 works best when the codebase already has the previous stage's structure to anchor to.

**Conventions used in prompts**
- `@filename` — Cursor reference syntax, attaches that file as context
- ⌘/Ctrl+I to open Composer, then pick **Agent / Composer 2.5** model
- Run terminal commands inside Cursor's integrated terminal so Composer sees the output

---

## Tech stack at a glance

| Layer | Library |
|---|---|
| UI | PySide6 (Qt 6) + QtCharts |
| LLM | `google-genai` Python SDK (Gemini 3.5 Flash) |
| MCP | `mcp` Python SDK (stdio transport) |
| MCP server (dev) | `mcp-server-sqlite` |
| MCP server (prod) | `mcp-server-postgres` or any SQL MCP server |
| Secrets | `keyring` (OS keychain) |
| Config | `pydantic-settings` + JSON file |
| History | `sqlite3` (stdlib) |
| Threads | `QThread` / `QRunnable` (no asyncio in UI thread) |
| Logging | `loguru` |

---

## Target project structure (final)

```
conv-analytics/
├── .venv/                       # created by setup.bat (gitignored)
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── setup.bat
├── run.bat
├── app/
│   ├── __init__.py
│   ├── main.py                 # entry point
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py         # pydantic settings + load/save
│   │   └── keychain.py         # keyring wrapper (API key, DB pw)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── mcp_client.py       # MCP stdio client
│   │   ├── schema_indexer.py   # introspect → context.md
│   │   ├── gemini_client.py    # google-genai SDK wrapper
│   │   └── orchestrator.py     # Q → SQL → result → render
│   ├── data/
│   │   ├── __init__.py
│   │   ├── history_db.py       # SQLite persistence
│   │   └── models.py           # dataclasses (Message, Analysis, ChartSpec)
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   ├── styles.qss
│   │   ├── widgets/
│   │   │   ├── __init__.py
│   │   │   ├── data_source_panel.py
│   │   │   ├── history_panel.py
│   │   │   ├── chat_panel.py
│   │   │   └── canvas_panel.py
│   │   ├── dialogs/
│   │   │   ├── __init__.py
│   │   │   └── settings_dialog.py
│   │   ├── charts/
│   │   │   ├── __init__.py
│   │   │   ├── bar_chart.py
│   │   │   ├── line_chart.py
│   │   │   └── donut_chart.py
│   │   └── workers/
│   │       ├── __init__.py
│   │       └── analysis_worker.py  # QRunnable to call Gemini
│   └── resources/
│       ├── icons/
│       └── prompts/
│           ├── system.md
│           └── schema_summary.md
├── tests/
│   └── test_smoke.py
└── data/                        # local SQLite for history + sample DB
    └── .gitkeep
```

---

# STAGE 0 — Bootstrap project skeleton

**Goal.** Empty but runnable project. `setup.bat` creates a venv and installs deps. `run.bat` launches a blank window.

### Files to create
- `setup.bat`, `run.bat`
- `requirements.txt`
- `.gitignore`, `.env.example`
- `README.md`
- `app/__init__.py`, `app/main.py` (opens a blank `QMainWindow`)
- Empty `__init__.py` files matching the structure above (touch them so the packages exist)
- `data/.gitkeep`, `app/resources/icons/.gitkeep`

### Composer 2.5 prompt

```
You are bootstrapping a new Python desktop app called "conv-analytics".

Create the following in the current empty directory:

1. requirements.txt — pin reasonable versions:
   PySide6>=6.7
   google-genai>=1.0
   mcp>=1.0
   keyring>=25
   pydantic>=2.6
   pydantic-settings>=2.2
   loguru>=0.7
   python-dotenv>=1.0

2. setup.bat — Windows batch script that:
   - Checks Python is available (3.10+)
   - Creates .venv with `python -m venv .venv`
   - Activates it
   - Upgrades pip
   - Installs from requirements.txt
   - Prints a "Setup complete. Copy .env.example to .env" message
   - Uses `if errorlevel 1` to bail on any failure

3. run.bat — Windows batch script that:
   - Verifies .venv exists (else tells user to run setup.bat)
   - Activates .venv
   - Runs `python -m app.main`

4. .gitignore — Python + Qt + venv + .env + data/*.sqlite

5. .env.example — placeholders for GEMINI_API_KEY and DB_URL

6. README.md — 1-page: what the app does, quickstart (setup.bat → fill .env → run.bat),
   and a short "architecture" section listing the modules from app/

7. app/main.py — entry that creates QApplication, opens a QMainWindow titled
   "Conv-Analytics" sized 1360×820, shows it, and runs the event loop.
   Use loguru for logging. Import sys, PySide6.QtWidgets.

8. Create empty __init__.py files for these packages:
   app/, app/config/, app/core/, app/data/, app/ui/, app/ui/widgets/,
   app/ui/dialogs/, app/ui/charts/, app/ui/workers/, tests/

9. Create .gitkeep files in: data/, app/resources/icons/, app/resources/prompts/

Modular rule for the whole project: NO module should exceed ~250 lines.
Split aggressively. UI widgets each in their own file.
```

### Verify
```bat
setup.bat
run.bat
```
You should see a blank window titled **Conv-Analytics**. Close it.

```
git init
git add .
git commit -m "stage 0: bootstrap"
```

---

# STAGE 1 — UI shell (three-pane layout + settings button)

**Goal.** The full layout from the wireframe, but with placeholder content in each panel. Settings button opens an empty dialog.

### Files to create / modify
- `app/ui/main_window.py` (move logic out of main.py)
- `app/ui/styles.qss` (qss based on the wireframe palette)
- `app/ui/widgets/data_source_panel.py` (placeholder)
- `app/ui/widgets/history_panel.py` (placeholder)
- `app/ui/widgets/chat_panel.py` (placeholder)
- `app/ui/widgets/canvas_panel.py` (placeholder)
- `app/ui/dialogs/settings_dialog.py` (empty QDialog, just a title)
- Update `app/main.py` to instantiate `MainWindow`

### Composer 2.5 prompt

```
Reference: @app/main.py

Stage 1: build the UI shell using PySide6. The layout matches this wireframe:

  [Title bar with "⚙ Settings" QToolButton on the right]
  ┌──────────────┬────────────────────────────────┐
  │ DataSource   │                                │
  │ (top, 320h)  │                                │
  ├──────────────┤        CanvasPanel             │
  │ History      │        (right, flexible)       │
  │ (middle,1fr) │                                │
  ├──────────────┤                                │
  │ Chat         │                                │
  │ (bot,200h)   │                                │
  └──────────────┴────────────────────────────────┘

Left column width = 400 px (resizable via QSplitter).
Use a vertical QSplitter on the left and a horizontal QSplitter splitting left/right.

Files to create:

1. app/ui/main_window.py
   - class MainWindow(QMainWindow)
   - Builds the layout described above
   - Top toolbar: QToolBar with a stretch + a "⚙ Settings" QAction
   - Settings action opens SettingsDialog (modal)
   - Loads app/ui/styles.qss via QFile and applies to itself
   - Window title "Conv-Analytics", size 1360×820

2. app/ui/styles.qss — Qt stylesheet using this palette:
   --ink #0e1116, --paper #f4f1ea, --accent #cc3a1f, --muted #6b6759
   Style QMainWindow, QToolBar, QPushButton, QListWidget, QTextEdit, QLineEdit, QDialog
   so the app feels like the wireframe (paper bg, dark borders, no flat-default look).

3. app/ui/widgets/data_source_panel.py
   - class DataSourcePanel(QWidget) with QVBoxLayout
   - Heading "01  Data Source · SQL via MCP"
   - Placeholder QLabel "Not connected" + QPushButton "Connect"
   - Empty QListWidget that will hold tables

4. app/ui/widgets/history_panel.py
   - class HistoryPanel(QWidget)
   - Heading "02  Conversation History"
   - QListWidget with 3 placeholder items

5. app/ui/widgets/chat_panel.py
   - class ChatPanel(QWidget)
   - Heading "03  Ask a Question"
   - QTextEdit (max 4 lines tall) + QPushButton "Send"
   - Ctrl+Enter triggers Send (use QShortcut)
   - Emit a Qt signal `question_submitted(str)` when Send is clicked

6. app/ui/widgets/canvas_panel.py
   - class CanvasPanel(QWidget)
   - Heading area showing the current question
   - For now just QLabel "No analysis yet" centered

7. app/ui/dialogs/settings_dialog.py
   - class SettingsDialog(QDialog)
   - Title "Settings — Configuration", size 620×600
   - Just a placeholder QLabel + Close button for now

8. Update app/main.py — import MainWindow from app.ui.main_window and use it.

Modular rule: each widget in its own file. NO inline lambdas longer than one line.
Use Qt's signal/slot pattern, not raw callbacks. Wire signals in MainWindow.__init__.
```

### Verify
Run `run.bat`. You should see:
- Three left panels stacked, with the right canvas
- Click ⚙ Settings → modal opens with just a Close button
- Resizing left/right and within-left splitters works

Commit: `git commit -am "stage 1: UI shell"`

---

# STAGE 2 — Settings dialog + config + keychain

**Goal.** Fully working settings dialog. API key and DB password stored in OS keychain. Other config persisted as JSON. Settings survive restart.

### Files to create / modify
- `app/config/settings.py` — pydantic Settings class + load/save
- `app/config/keychain.py` — `keyring` wrapper
- `app/ui/dialogs/settings_dialog.py` — full form (Sections A, B, C from wireframe)
- Wire `MainWindow` to load settings on startup

### Composer 2.5 prompt

```
Reference: @app/ui/dialogs/settings_dialog.py @app/config @app/ui/main_window.py

Stage 2: implement Settings persistence.

1. app/config/keychain.py
   - get_secret(key: str) -> str | None — reads from `keyring` under service name "conv-analytics"
   - set_secret(key: str, value: str) -> None
   - delete_secret(key: str) -> None
   Keys used: "gemini_api_key", "db_password"

2. app/config/settings.py
   - Use pydantic BaseModel (not BaseSettings) for the schema.
   - Fields:
       gemini_model: str = "gemini-3.5-flash"
       max_tokens: int = 4096
       mcp_server_type: Literal["sqlite", "postgres", "mysql"] = "sqlite"
       mcp_server_command: list[str]  # e.g. ["uvx", "mcp-server-sqlite", "--db-path", "./data/sample.db"]
       db_url: str = ""                # e.g. postgresql://user@host:5432/db (no password)
       ssl_mode: str = "require"
       readonly: bool = True
       max_rows: int = 10000
       theme: str = "paper"
       history_db_path: str = "./data/history.sqlite"
   - load() classmethod: reads ~/.config/conv-analytics/config.json (or %APPDATA% on Windows).
     If missing, returns defaults.
   - save() method: writes the same path.
   - Use platformdirs for the config dir.
   - Add platformdirs to requirements.txt and document this.

3. app/ui/dialogs/settings_dialog.py — full form with three QGroupBox sections:

   Section A: API Keys & Model
     - "Gemini API Key" QLineEdit, EchoMode=Password, with a small "show" toggle button
     - "Default Model" QComboBox: ["gemini-3.5-flash","gemini-3.5-pro","gemini-3-flash"]
     - "Max Tokens" QSpinBox (range 256..8192)

   Section B: MCP Server / SQL Connector
     - "Server Type" QComboBox: sqlite, postgres, mysql
     - "Server Command" QLineEdit (the command to spawn the MCP server,
       e.g. `uvx mcp-server-sqlite --db-path ./data/sample.db`)
     - "Connection URL" QLineEdit (only enabled for postgres/mysql)
     - "DB Password" QLineEdit, EchoMode=Password (only enabled for postgres/mysql)
     - "SSL Mode" QComboBox
     - "Read-only" QCheckBox (default checked)
     - "Max Rows" QSpinBox

   Section C: App Preferences
     - "Theme" QComboBox: ["paper"]  (placeholder)
     - "History DB path" QLineEdit + Browse button

   Footer:
     - "Test Connection" button (left). On click, spawn MCP server briefly, call list_tables,
       show "✓ Connected · N tables" or red error label. (For Stage 2, stub this to just
       return True for sqlite if the db file exists, else False — real test comes in Stage 3.)
     - Spacer
     - "Cancel" and "Save" buttons (right)

   On Save:
     - Write API key and DB password to keychain via keychain.set_secret
     - Write the rest to config.json via Settings.save()
     - Emit signal `settings_saved` so MainWindow can react

4. MainWindow:
   - On __init__, call Settings.load() and stash on self.settings
   - Pass to SettingsDialog as a constructor arg
   - After Save, reload self.settings

Modular rule: keep settings_dialog.py under 250 lines. If it grows, split each
section into its own small QGroupBox subclass under app/ui/dialogs/_sections/.
```

### Verify
1. Open settings, fill in your real API key, save.
2. Close the app, re-open with `run.bat`.
3. Reopen settings — API key field shows masked content, model dropdown remembers.
4. Open `%APPDATA%\conv-analytics\config.json` — model/db_url present, **no secrets**.
5. (Optional) `python -c "import keyring; print(keyring.get_password('conv-analytics','gemini_api_key'))"` returns the key.

Commit: `git commit -am "stage 2: settings + keychain"`

---

# STAGE 3 — MCP client + schema introspection

**Goal.** Click "Connect" in the DataSourcePanel → app spawns the MCP server, introspects the schema, populates the tables list, and generates `context.md` (the schema summary).

### Pre-flight: install an MCP server for dev

```bat
pip install uv
uv tool install mcp-server-sqlite
```

Make `data/sample.db` with at least an `orders`, `customers`, `products` table. (Composer can do this in the prompt below.)

### Files to create / modify
- `app/core/mcp_client.py` — stdio MCP client wrapper
- `app/core/schema_indexer.py` — turns schema → markdown
- `app/resources/prompts/schema_summary.md` — prompt template for context.md
- Flesh out `app/ui/widgets/data_source_panel.py`
- Add a tiny `app/data/seed_sample_db.py` to populate `data/sample.db`

### Composer 2.5 prompt

```
Reference: @app/config/settings.py @app/ui/widgets/data_source_panel.py

Stage 3: SQL-via-MCP wiring.

1. app/data/seed_sample_db.py
   - Standalone script. Creates data/sample.db (SQLite) with:
       customers(id, name, city, segment)
       products(id, name, category, price)
       orders(id, customer_id, product_id, order_date, net_amount, qty, campaign)
   - Inserts ~300 realistic rows across Karnataka cities including "Mysore",
     dates from 2026-07-01 to 2026-09-30. Use random with fixed seed for reproducibility.
   - Idempotent (drops + recreates).
   - Run-able via `python -m app.data.seed_sample_db`.

2. app/core/mcp_client.py
   - class McpClient
       async connect(command: list[str]) -> None
           Uses mcp.client.stdio.stdio_client to spawn the server and open a session.
       async list_tools() -> list[Tool]
       async list_tables() -> list[str]
       async describe_table(name: str) -> dict   # columns, types, PK
       async query(sql: str) -> list[dict]        # readonly enforcement done server-side
       async close() -> None
   - Because PySide6 is sync, wrap async calls behind a helper:
       def run_sync(coro) — uses asyncio.run on a fresh loop in a worker thread.
   - Provide a higher-level sync facade `SyncMcpClient` so UI code doesn't see asyncio.

3. app/core/schema_indexer.py
   - Pure-Python, no UI.
   - def build_context_md(tables: list[dict]) -> str
       Renders a markdown like:
           # Database schema
           Tables: 3
           ## orders
           | column | type | notes |
           |---|---|---|
           | id | INTEGER PRIMARY KEY | |
           | customer_id | INTEGER FK→customers.id | |
           ...
   - def save_context(md: str, path: Path) -> None
   - Default save path: data/context.md

4. app/resources/prompts/schema_summary.md
   - System prompt template to optionally enrich the schema with semantic notes via Gemini.
   - For Stage 3, the basic build_context_md result is enough; no Gemini call yet.

5. app/ui/widgets/data_source_panel.py — flesh out:
   - "Connect" button → uses Settings.mcp_server_command to spawn server via SyncMcpClient
   - On connect success:
       * Show "● LIVE" green badge + latency in ms
       * Populate QListWidget with checkboxes for each table
       * Save context.md via schema_indexer
   - On failure: show red error label with message
   - Emit signal `connected(client: SyncMcpClient, tables_in_scope: list[str])` for MainWindow
   - All blocking work runs in a QThreadPool / QRunnable so the UI never freezes.

6. Wire MainWindow to hold a reference to the connected client.

Modular rule: keep mcp_client.py focused on transport.
Schema rendering belongs in schema_indexer.py. UI strings stay in the panel.
```

### Verify
```bat
python -m app.data.seed_sample_db
run.bat
```
- Click **Connect** in the data source panel.
- Watch the badge turn green and the table list populate with `customers`, `products`, `orders` (each with a checkbox).
- Inspect `data/context.md` — should show schema tables in markdown.

Commit: `git commit -am "stage 3: MCP client + schema introspection"`

---

# STAGE 4 — Gemini client + prompt templates + data models

**Goal.** A clean wrapper around the Anthropic SDK that takes a question + context.md and returns a structured analysis. No UI yet — just unit-testable.

### Files to create / modify
- `app/data/models.py` — dataclasses
- `app/core/gemini_client.py` — Anthropic SDK wrapper
- `app/resources/prompts/system.md` — system prompt
- `tests/test_gemini_client.py` — smoke test (live API, gated by env var)

### Composer 2.5 prompt

```
Reference: @app/config/settings.py @app/config/keychain.py @app/core/mcp_client.py

Stage 4: Gemini integration. Pure logic, no UI.

1. app/data/models.py — define dataclasses (use @dataclass(slots=True)):
   - ChartSpec:
       kind: Literal["bar","line","donut","table","kpi_only"]
       title: str
       x: list[str] | None
       series: list[dict]   # [{"name": "Revenue", "data": [14.1, 18.6, 15.5]}, ...]
       options: dict        # free-form (axis labels, formatting)
   - Kpi:
       label: str
       value: str
       delta: str | None
       trend: Literal["up","down","flat"] | None
   - Analysis:
       question: str
       sql: str
       summary: str        # the description paragraph
       kpis: list[Kpi]
       chart: ChartSpec | None
       insights: list[str]
       row_count: int
       elapsed_ms: int
       created_at: datetime

2. app/resources/prompts/system.md — system prompt that:
   - Explains: "You are a data analyst. The user has a SQL database described below.
     They will ask questions in natural language. You must return ONLY a JSON object
     matching this exact schema: { sql, summary, kpis, chart, insights }."
   - Shows the JSON schema as an inline JSON example.
   - Rules: SELECT only, no DDL, no DML. Cap to 10k rows.
     Use only tables listed in the schema. If the question is ambiguous, return a
     `summary` asking for clarification and an empty kpis/chart.
   - Instructs to pick the chart `kind` based on the question:
       single value → kpi_only
       trend over time → line
       categories → bar
       parts of a whole → donut
       raw rows → table

3. app/core/gemini_client.py — class GeminiClient:
   - __init__(api_key: str, model: str, max_tokens: int)
   - def analyze(question: str, context_md: str, history: list[dict] | None = None) -> Analysis
       * Builds messages: system (from system.md + context_md appended), then history,
         then the new user message.
       * Uses genai.Client().models.generate_content with response_mime_type="application/json".
       * Forces JSON output via the prompt; parse with json.loads after stripping ```json fences.
       * Validate against the Analysis dataclass; raise AnalysisParseError on failure.
       * Re-prompt once with the parse error if validation fails.
   - Helpful errors: surface 401 as InvalidApiKeyError, 429 as RateLimitError.
   - Sync interface (google-genai SDK already supports this).

4. tests/test_gemini_client.py
   - One smoke test that runs only if GEMINI_API_KEY env var is set
     (else pytest.skip).
   - Asks "How many tables are there?" against a tiny fake context.md
   - Asserts an Analysis is returned with non-empty summary.

Modular rule: gemini_client.py knows nothing about Qt or MCP.
It takes a question + context_md and returns an Analysis. That's it.
```

### Verify
```bat
.venv\Scripts\activate
set GEMINI_API_KEY=sk-ant-...
pytest tests/test_gemini_client.py -v
```
Should pass with `1 passed`.

Commit: `git commit -am "stage 4: claude client + models"`

---

# STAGE 5 — Orchestrator (Q → SQL → result → Analysis)

**Goal.** Wire everything together. ChatPanel emits a question → orchestrator calls Gemini → executes the returned SQL via MCP → enriches the Analysis with real numbers → emits result for CanvasPanel.

### Files to create / modify
- `app/core/orchestrator.py`
- `app/ui/workers/analysis_worker.py` (`QRunnable`)
- Wire `ChatPanel` → `MainWindow` → `Orchestrator` → `CanvasPanel`

### Composer 2.5 prompt

```
Reference: @app/core/gemini_client.py @app/core/mcp_client.py @app/data/models.py
           @app/ui/widgets/chat_panel.py @app/ui/widgets/canvas_panel.py @app/ui/main_window.py

Stage 5: end-to-end question pipeline.

1. app/core/orchestrator.py — class Orchestrator:
   - __init__(gemini: GeminiClient, mcp: SyncMcpClient, context_md: str)
   - def ask(question: str, history: list[dict]) -> Analysis:
       a. Call gemini.analyze(question, context_md, history) → analysis_v1
       b. If analysis_v1.sql is non-empty:
            - Execute via mcp.query(sql)
            - If rows returned, REPLACE the kpi values + chart.series in analysis_v1
              with values computed from rows (do this in a small helper compute_kpis()).
              Don't trust LLM-fabricated numbers; trust the SQL output.
            - Set analysis.row_count and elapsed_ms.
         If sql is empty (clarification flow): leave kpis empty, return as-is.
       c. Return final Analysis.

   - Helper compute_kpis(rows, chart_spec, kpi_specs) — see notes:
       * For numeric KPIs, the Gemini response should include a `kpi_specs` like
         { "label":"Total Sales","aggregation":"sum","column":"net_amount","format":"₹{:,.0f}" }
         Update system.md so Gemini returns this shape under a new top-level key "kpi_specs".
       * Aggregation values: sum, mean, count, count_distinct, min, max.
       * Format strings use Python str.format.

   - Update Analysis dataclass with kpi_specs field if needed (or keep separate).
     Document the contract clearly in models.py docstring.

2. app/ui/workers/analysis_worker.py — class AnalysisWorker(QRunnable):
   - signals: started, finished(Analysis), failed(str)
   - run() executes orchestrator.ask in a background thread (QRunnable + QThreadPool)
   - Use Signals via a separate WorkerSignals(QObject) helper (standard PySide6 pattern).

3. Wire-up in MainWindow:
   - When DataSourcePanel emits connected(...), construct Orchestrator on self
   - When ChatPanel emits question_submitted(text):
       * Show a loading indicator on CanvasPanel
       * Submit AnalysisWorker to QThreadPool
       * On finished, call canvas_panel.render(analysis)
       * On failed, show error on CanvasPanel
   - Maintain self.history list[dict] of {"role":"user"|"assistant","content":...}
     for follow-up context. Cap to last 6 turns.

4. CanvasPanel — flesh out enough to show:
   - The question as a big header
   - The generated SQL in a monospace dark block
   - The summary in a paper-bg card
   - A simple QLabel-based KPI row (real charts come in Stage 6)
   - Insights as a bulleted QTextBrowser
   - A loading state (animated dots) while worker is running

5. Update system.md to include the kpi_specs schema and clarify the contract.

Modular rule: orchestrator.py has zero Qt imports. Workers are the bridge.
```

### Verify
- Run app, connect MCP, type "How many orders are there in Mysore?" → press Send.
- See loading state, then SQL block + summary + KPI showing the right count.
- Type a follow-up "Break that down by month" — should use history.

Commit: `git commit -am "stage 5: orchestrator + end-to-end"`

---

# STAGE 6 — Charts (QtCharts) + canvas polish

**Goal.** Real charts replace the QLabel stubs. The canvas matches the wireframe — KPI tiles, bar/line/donut, insights.

### Files to create / modify
- `app/ui/charts/bar_chart.py`, `line_chart.py`, `donut_chart.py`
- `app/ui/charts/__init__.py` — `build_chart(spec: ChartSpec) -> QWidget` factory
- Polish `canvas_panel.py`

### Composer 2.5 prompt

```
Reference: @app/data/models.py @app/ui/widgets/canvas_panel.py

Stage 6: render real charts using QtCharts.

1. app/ui/charts/bar_chart.py
   - class BarChartWidget(QWidget)
   - __init__(spec: ChartSpec)
   - Uses QChartView, QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis
   - Highlight rule: if spec.options has "highlight_index", that bar uses --accent color
   - Title from spec.title

2. app/ui/charts/line_chart.py
   - class LineChartWidget(QWidget) using QLineSeries
   - Supports multiple series from spec.series

3. app/ui/charts/donut_chart.py
   - class DonutChartWidget(QWidget) using QPieSeries with hole-size > 0
   - Legend on the right

4. app/ui/charts/__init__.py
   - def build_chart(spec: ChartSpec) -> QWidget
   - Dispatches on spec.kind; raises NotImplementedError for "table" (handle in canvas).

5. Polish canvas_panel.py to match the wireframe:
   - QScrollArea wrapping a vertical layout
   - Section order: question header, SQL block (collapsible via QToolButton "▾ SQL"),
     summary card, KPI row (use QFrame tiles in QGridLayout), chart widget, insights card
   - For ChartSpec.kind == "kpi_only", only render the KPI row + summary
   - For "table", render a QTableWidget
   - Apply styles via objectName + the existing styles.qss; do NOT inline stylesheets.

6. Add styles to styles.qss for: KpiTile (QFrame#KpiTile), Sql block (QPlainTextEdit#SqlBlock,
   read-only, monospace, dark bg), Summary card (QFrame#SummaryCard).

7. Add a "Refresh" button to canvas_panel that re-runs the orchestrator with the same
   question — emit signal `refresh_requested(question: str)` for MainWindow.

Modular rule: each chart kind in its own file. No chart file imports another.
build_chart in __init__.py is the only place that knows about all kinds.
```

### Verify
- Ask "Monthly sales in Mysore by category" → bar chart appears.
- Ask "Category mix in Mysore" → donut chart appears.
- Ask "How many orders in Mysore?" → only KPI tiles + summary, no chart.
- Resize the window — charts scale.

Commit: `git commit -am "stage 6: charts + canvas polish"`

---

# STAGE 7 — History persistence (SQLite + re-render)

**Goal.** Every analysis is saved. Clicking a history item re-renders without calling the API. "New chat" button clears the canvas.

### Files to create / modify
- `app/data/history_db.py`
- Flesh out `app/ui/widgets/history_panel.py`
- Wire `MainWindow` to save on completion and re-render on click

### Composer 2.5 prompt

```
Reference: @app/data/models.py @app/ui/widgets/history_panel.py @app/ui/main_window.py

Stage 7: persist conversation history.

1. app/data/history_db.py
   - Uses stdlib sqlite3. Path comes from Settings.history_db_path.
   - Schema:
       conversations(id INTEGER PK, title TEXT, created_at TEXT)
       analyses(id INTEGER PK, conversation_id INTEGER FK, question TEXT,
                analysis_json TEXT, created_at TEXT)
   - Functions (sync, simple):
       init_db(path) — creates schema if missing
       new_conversation(title: str) -> int
       save_analysis(conv_id: int, analysis: Analysis) -> int
       list_conversations() -> list[dict]
       get_conversation(conv_id) -> dict with analyses list
       delete_conversation(conv_id)
   - Analysis serialized as json (use a custom encoder for datetime).

2. app/ui/widgets/history_panel.py
   - Heading + "+ New chat" QToolButton at the top
   - QListWidget below — each item shows: question title (first 60 chars), timestamp
   - On item click → emit signal `history_item_selected(analysis_id: int)`
   - On "+ New" click → emit `new_conversation_requested`
   - public method `refresh()` re-queries the DB

3. MainWindow wiring:
   - On startup, init DB and create a new conversation (or load most recent).
   - After each successful AnalysisWorker.finished:
       * save_analysis(self.current_conv_id, analysis)
       * history_panel.refresh()
   - On history_item_selected: load analysis JSON, deserialize to Analysis,
     call canvas_panel.render(analysis) — DO NOT re-call API.
   - On new_conversation_requested:
       * Clear canvas
       * Clear self.history (in-memory turns list)
       * Create a new conv row

4. Make sure history items show which conversation they belong to (group by
   conversation with a small header row, OR put the conversation switcher in a
   QComboBox at the top of HistoryPanel — your call, pick the cleaner one).

Modular rule: history_db.py is the only file that knows SQL for history.
UI components call its functions, never raw queries.
```

### Verify
- Ask three different questions. Each appears in the history list.
- Close the app, reopen — history is still there.
- Click an old item — canvas re-renders with the same SQL/summary/chart, with NO new API call (watch network or add a log line in claude_client.analyze).
- Click "+ New chat" — canvas clears, history list still shows the old conversation.

Commit: `git commit -am "stage 7: history persistence"`

---

# STAGE 8 — Polish, error handling, UX

**Goal.** No silent failures, no UI freezes, every state has a visual.

### Composer 2.5 prompt

```
Reference: @app/ui @app/core

Stage 8: polish pass. No new features — make existing ones robust.

1. Error UX
   - Show a non-blocking error banner at the top of CanvasPanel for:
     * Invalid API key (red, "Settings → check your Anthropic API key")
     * MCP server crashed (orange, "Reconnect" action)
     * SQL execution error (red, show the SQL that failed in a collapsible)
     * Rate limit (yellow, "Retry in N seconds")
   - Banner is a reusable widget: app/ui/widgets/banner.py with kind + message + action.

2. Loading states
   - CanvasPanel shows an animated "thinking" indicator while the worker runs.
   - DataSourcePanel shows "Connecting..." with disabled controls during connect.

3. Empty states
   - No connection yet: CanvasPanel shows "Connect a database in the left panel".
   - Connected but no question: CanvasPanel shows "Ask a question below".

4. Validation
   - Block "Send" if there's no MCP connection.
   - Block "Send" if the chat input is empty/whitespace.
   - In Settings, block "Save" if API key is empty AND MCP server type is non-sqlite
     (i.e., a remote DB always requires API key).

5. Logging
   - Configure loguru in app/main.py to write to ./data/logs/app.log with rotation (1 MB).
   - Sprinkle .info/.warning/.error in orchestrator, mcp_client, claude_client.
   - On uncaught exception in any worker, log full traceback and surface to banner.

6. Keyboard shortcuts
   - Ctrl+, → open Settings
   - Ctrl+N → new conversation
   - Ctrl+Enter → submit chat (already there from Stage 1, verify)
   - Esc → close any open dialog

7. README.md update
   - Add a "Troubleshooting" section with common errors
   - Add a screenshot section (use placeholders)

Modular rule: any new widget gets its own file under app/ui/widgets/.
Don't bloat existing modules.
```

### Verify
- Unplug your network, ask a question → see a clean error banner, not a crash.
- Delete `data/sample.db`, click Connect → see a clear error, not a stack trace.
- Try Ctrl+N, Ctrl+, , Esc — all behave as expected.

Commit: `git commit -am "stage 8: polish"`

---

# Optional Stage 9 — Drill-down + multi-DB profiles

Once Stages 0–8 are stable, candidate next features:

- **Drill-down** ✅ *implemented*: clicking a bar/slice emits `category_clicked` from the chart widget; `CanvasPanel.drilldown_requested` routes it to `MainWindow`, which submits "Drill into <category>" as a follow-up question (re-using conversation history).
- **Multi-DB profiles** ✅ *implemented*: `Settings` holds a `profiles: list[Profile]` plus `active_profile_index`; `apply_profile()` mirrors the chosen profile onto the flat connection fields so the rest of the app is unchanged. A profile switcher (`QComboBox`) sits above the data source panel; switching drops the live connection and prompts a reconnect. The Settings dialog syncs edits back into the active profile. Tests in `tests/test_settings_profiles.py`.
- **Export** ✅ *implemented*: "Export HTML" button on the canvas → `app/core/report_export.py` writes a self-contained HTML report (inline CSS, Chart.js via CDN with a data-table fallback). Tests in `tests/test_report_export.py`.
- **Streaming** ✅ *implemented*: in streaming mode the model emits the plain-text summary first, then a `===JSON===` delimiter, then the JSON object. `GeminiClient.analyze(..., on_chunk=cb)` streams via `generate_content_stream`, forwarding only the prose deltas (before the delimiter) to the callback; `split_summary_and_json()` separates the parts and the JSON is parsed at the end. `AnalysisWorker` emits cumulative summary text via `summary_streamed(str)`, and the canvas renders it live word-by-word with a caret, then swaps to the full rendered result on completion. Non-streaming path (pure JSON via `response_mime_type`) is used when no callback is given. Tests in `tests/test_gemini_stream_split.py`.

Each is one Composer 2.5 session at this size of codebase.

---

# Working agreements with Cursor Composer 2.5

A few habits that keep the agent productive on this project:

1. **One stage per session.** Open a fresh Composer for each stage. Long sessions drift.
2. **Always attach files with `@`.** Don't rely on Composer's auto-context; it misses things.
3. **Run the verify step before moving on.** If verify fails, paste the error back into the *same* Composer session — don't start a new one.
4. **Don't accept "I'll skip this for now"** answers from Composer. If it asks, say "do it all".
5. **Commit between stages.** If Composer wrecks something in Stage N, `git checkout .` brings Stage N-1 back in seconds.
6. **Keep files under 250 lines.** When a file grows, ask Composer to split it. The modular rule above is non-negotiable.
7. **Pin requirement versions** once a stage works — easier rollback.

---

# Quick reference: `setup.bat` and `run.bat`

**`setup.bat`**
```bat
@echo off
setlocal

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.10+ and retry.
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo venv creation failed & exit /b 1 )
)

call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 ( echo dependency install failed & exit /b 1 )

if not exist .env (
    copy .env.example .env >nul
    echo Created .env from template. Edit it to add your GEMINI_API_KEY.
)

echo.
echo ============================================================
echo  Setup complete.
echo  Next:
echo    1. Edit .env if needed
echo    2. (Optional) python -m app.data.seed_sample_db
echo    3. run.bat
echo ============================================================
endlocal
```

**`run.bat`**
```bat
@echo off
setlocal
if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat
python -m app.main %*
endlocal
```

---

**That's the plan.** Stages 0–8 should take a focused day of work with Composer 2.5; Stage 9 is open-ended. Good luck.
