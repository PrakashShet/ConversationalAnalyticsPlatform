---
name: conversational-analytics-platform
description: Working on the AI-Powered Conversational Analytics Platform — the PySide6 desktop app that turns natural-language questions into SQL via Gemini and adds local forecasts. Use for any change to its code, tests, docs, UI, or packaging.
---

# Conversational Analytics Platform

**Location:** `C:\WorkSpace\ConversationalAnalyticsPlatform`

A PySide6 desktop app. User asks a question in English → Gemini writes SQL →
the app executes it → Gemini narrates the result → Python computes the numbers
and, when the result is a time series, a forecast. It is also the artifact
behind an EMBA capstone, so the documentation matters as much as the code.

Read `docs/ARCHITECTURE.md` before any non-trivial change. It has the full
diagrams and is kept current.

---

## The four rules this codebase is built on

Do not break these. Every design decision follows from them.

1. **Never send table data to the LLM.** The planner sees a schema summary only.
   The analyst sees at most ~100 rows / 4,000 chars (`row_utils.compact_rows`).
2. **The LLM writes SQL and prose — never numbers.** Gemini emits a `KpiSpec`
   (`{label, aggregation, column, format}`); Python computes the value from real
   rows. Forecasts and the predictive narrative are numpy/Python only.
3. **Read-only by default**, enforced at two independent points.
4. **Degrade, never crash.** Optional statsmodels, optional QtWebEngine, JSON
   repair-retry, CSV encoding fallbacks. A forecast failure must leave the
   descriptive answer intact.

---

## Layout

```
app/config/    settings.py (pydantic + platformdirs JSON), keychain.py (OS keyring)
app/core/      orchestrator, gemini_client/planner/analyst, sql_client, mcp_client,
               timeseries, forecasting, row_utils, schema_indexer, report_export,
               data_source (provenance), forecast_narrative
app/data/      models.py (dataclasses), history_db.py (SQLite), load_csv.py,
               column_normalize.py, download_*.py, seed_sample_db.py
app/resources/ prompts/*.md (system, sql_planner, analyst, schema_summary),
               vendor/echarts.min.js (vendored — no CDN)
app/ui/        main_window.py, widgets/, charts/, dialogs/ (incl. notices), workers/
app/paths.py   dev-vs-frozen path resolution — the only place that knows
docs/          ARCHITECTURE.md, plans/, reports/ (incl. reports/forecasting/)
tests/         pytest, core + data only
```

**`app/core` must never import Qt.** That separation is what makes the engine
testable. If you need threading, add a `QRunnable` in `app/ui/workers/`.

This file is the in-repo copy of the skill. An identical skill is saved to the
user's Claude account under the same name — keep the two in sync; editing one
does not update the other.

---

## The pipeline (`Orchestrator.ask`)

Two Gemini calls per question, plus a one-off context build at connect time.

1. `plan_sql()` — prompt = `sql_planner.md` + `data/context.md`; returns
   `SqlPlan{sql, chart_intent, rationale, needs_clarification, forecast_requested}`.
2. Gate: `is_select_only()` → refuse anything else.
3. Execute; `exec_rows = rows[:MAX_EXEC_ROWS]` (500); `compact_rows()` for the LLM.
4. `summarize_result()` — returns `ResultInsight`.
5. `fill_charts_from_rows()` + `compute_kpis()` — real numbers, in Python.
6. `_attach_forecast()` — local, 0 tokens, 0 SQL, wrapped in try/except.

Returns a single `Analysis` dataclass, stamped with the active
`SourceFingerprint`, which is also what gets JSON-serialised into
`data/history.sqlite` so history replay costs no API calls.

---

## Persistence of an Analysis (`app/data/history_db.py`)

Descriptive results are stored **verbatim** — chart `x`/`series` embedded, KPIs
as already-formatted strings — so replay never recomputes a number the user was
shown.

The predictive layer is stored **both ways**:

- the full `ForecastResult` (points, band, fitted, metrics, warnings) under
  `forecast` — the authoritative record of what the user saw, so it cannot drift
  if the engine changes later; rebuilding it needs no numpy;
- its inputs (`ts_profile`, `forecast_settings`, `available_methods`) — these
  keep the controls interactive, so changing method or horizon on a replayed
  item recomputes locally against the stored profile.

Also persisted: `source` (the `SourceFingerprint`), `needs_clarification`,
`forecast_requested`, `forecast_note`.

Details that matter:

- `_restore_forecast` prefers the stored result; it only recomputes for older
  inputs-only payloads.
- `forecastable` is set from **profile presence**, not from the forecast — a
  stored result without a profile is display-only, so the controls stay hidden.
- NaN metrics (`backtest` returns them on series too short to score) are written
  as `null`; bare `NaN` is invalid JSON. Both consumers — `report_export` and
  `canvas_panel._set_forecast_badge` — already guard on `None` first.
- Malformed profile *or* malformed points must degrade to a descriptive-only
  replay, never raise out of `get_analysis()`. Keep the parsing **inside** the
  try block, not just the compute — that was a real bug.
- Cost: ~2.6 KB for a 36-point series with a 12-period horizon.

If you add a field to `Analysis`, add it to **both** `_analysis_to_dict` and
`_dict_to_analysis`, and extend `tests/test_history_db.py` — that pairing has
been broken before.

---

## Data-source provenance (`app/core/data_source.py`)

A saved analysis outlives its connection, and its suggested follow-ups /
drill-downs / Refresh are questions written against *that* schema. Running them
against whatever is connected now yields a confident, unrelated answer — so
every `Analysis` carries a `SourceFingerprint`:

- `name` / `kind` — profile label and engine, for dialog wording
- `target` — connection URL, **password redacted** (`redact_url`); fingerprints
  are persisted, so a password must never reach one
- `schema_hash` — 12-hex digest of sorted `table(column,…)`, ignoring column
  types and ordering. Catches what a URL check misses: `load_data.bat` drops and
  recreates the public schema, so the same URL can hold different data
- `table_count`

`compare()` returns `different_target` / `schema_changed` / `unknown_source` /
`None`. A missing fingerprint on either side is `unknown_source`, never a silent
match — pre-provenance analyses cannot be vouched for.

**The gate:** `MainWindow._on_derived_question` handles suggestion clicks,
drill-downs and Refresh; it calls `_confirm_source_for_displayed()` and raises a
modal on mismatch (Cancel is the default; "Ask anyway" proceeds — it is a
warning, not a block). Questions typed into the chat box bypass the gate — they
are new questions about the current data, not follow-ups.

**Dialog wording lives in `data_source.explain()`, not in the UI**, so the copy
is testable without Qt. `app/ui/dialogs/notices.py` is the thin Qt layer and
also owns the modals for not-connected, missing API key, question-doesn't-fit,
forecast-unavailable, and classified failures. Anything that would otherwise be
an easily-missed inline banner belongs there.

**Session state is per–data source.** `_reset_session_state()` clears
`_chat_history` and opens a new conversation on disconnect, DB-type change, and
any reconnect whose fingerprint differs. Chat history is fed to the planner as
context, so leaking it across databases corrupts SQL generation.

---

## Forecasting

`timeseries.detect_time_series()` is the **relevance gate**. It returns `None`
for anything that is not a forecastable series, and `None` means no forecast UI
appears. Thresholds:

- `MIN_POINTS = 6`
- `PARSE_THRESHOLD = 0.9` — ≥90% of time cells must parse as dates
- `_REGULARITY = 0.6` — ≥60% of gaps must match one frequency band
- Frequency bands in days: D 0.5–2, W 5–9, M 26–32, Q 84–96, Y 350–380
- Seasonal periods: D→7, W→52, M→12, Q→4, Y→none

`available_methods(profile)` is data-driven: auto/naive/moving_average/
linear_trend always; `holt` at n≥6; `seasonal_naive` + `holt_winters` when
seasonal; `sarima` only when `seasonal_period ≤ 24` and `n ≥ max(2·period, 16)`.

`_REGISTRY` holds **7** methods; `auto` is a selection strategy resolved before
dispatch, not a registry entry. It picks the lowest backtest MAPE inside
`_compute`, so `ForecastResult.method` is always the method actually used — that
is what gets persisted and what the controls display on replay.

Confidence bands use hardcoded z-scores to avoid a SciPy dependency. Recompute
runs in `ForecastWorker` over the in-memory `TimeSeriesProfile` — never re-query.

`docs/plans/diagnose_forecast.py` is the script for debugging detection against
real rows.

**Deep documentation:** `docs/reports/forecasting/` holds a five-report series —
architecture, per-method mathematics (equations and band derivations), the
relevance gate, parameter selection, and backtesting/accuracy. It states the
governing constants and the known limitations (approximate Holt/Holt-Winters
bands, MAPE asymmetry, selection bias in the reported score, fixed SARIMA
orders, no coverage check). **If you change a threshold, a method, or the
selection criterion, update the relevant report in the same change** — the
quick-reference tables in `docs/reports/forecasting/README.md` are the most
likely to drift.

The same five reports exist as `.docx` under `docs/reports/forecasting/docx/`.
**They are generated, never hand-edited** — `python docs/tools/build_reports_docx.py`
rebuilds them from the Markdown. The toolchain is worth knowing before touching
it: `mermaid_render.py` redraws the Mermaid subset used here with Graphviz and
matplotlib (no Node, no headless Chromium) and draws each figure at its *final
print size*, because scaling a twelve-inch diagram into a seven-inch column
gives three-point text; wide figures get a landscape page. Pandoc converts the
LaTeX to native Word equations (OMML), not pictures. `docx_postprocess.py` then
fixes two things pandoc 2.9 will not: it populates the empty `<w:tblGrid/>` and
per-cell `<w:tcW>` (without both, LibreOffice renders every table as one
stacked column), and it inserts the landscape section breaks.

### Forecast questions are first-class

**"Get me weekly sales" and "get me a sales forecast" must produce
substantially the same SQL.** `sql_planner.md` states this outright and at
length, because the model's instinct is to refuse a forecast on the grounds
that the database holds no future rows — true, irrelevant, and the cause of a
real bug. The app forecasts locally from whatever history the SQL returns.

`SqlPlan.forecast_requested` records that the user asked. It changes no SQL; it
means that if detection then fails the app owes an explanation.
`timeseries.explain_not_forecastable(rows, chart)` produces it — naming the
missing date column, the period count short of `MIN_POINTS`, or irregular
spacing — surfaced both as a modal (`notices.forecast_unavailable`) and as a
card in place of the predictive section. Never let a requested forecast vanish
silently.

### Model transparency

Three pure functions in `forecasting.py`, all local arithmetic over history
already in memory, feed the collapsible "Model details" panel:

- `series_diagnostics(profile)` — columns, grain, period count, range,
  seasonality, backtest holdout, observed min/max
- `compare_methods(profile, confidence)` — MAPE/MAE/RMSE per eligible method,
  best first, unscorable ones last rather than hidden. **`auto`'s winner must
  be the top scored row** — there is a test for that
- `method_availability(profile)` — every known method with why it is offered or
  withheld

`METHOD_NOTES` / `PERIOD_NOUN` / `FREQ_LABELS` back the tooltips and help text.

### Predictive analytics narrative (`app/core/forecast_narrative.py`)

Whenever a forecast exists a **Predictive Analytics** card renders beneath
**Descriptive Analytics**, same shape: summary paragraph then bullets.
Composed in Python — direction and size of change, horizon total vs the prior
equivalent window, model and backtest accuracy in words, band width at the far
end, seasonality and whether the model uses it, whether the projection leaves
observed range.

**Zero tokens, no Gemini call.** Not just economy: rule two says the LLM never
states a predicted number, and never asking is the surest way to hold that.
Deterministic, so the prose is assertable in tests — and `report_export`
renders the identical text, so a report and the screen cannot disagree. If you
add a fact to the narrative, add it to both.

---

## Threading

Everything expensive is a `QRunnable` on `QThreadPool.globalInstance()`:
`ConnectWorker`, `ContextWorker`, `AnalysisWorker`, `ForecastWorker`.

Three patterns you must preserve when adding a worker:

- **Generation guard** — `MainWindow._connection_gen` increments on every
  connect/disconnect/source-change. Workers store `connection_gen` and an
  `is_current` callback; stale emissions are dropped rather than crashing
  against a closed SQL client.
- **Parent the signals object** — `WorkerSignals(parent)` so the QObject
  survives the runnable.
- **Catch `RuntimeError` on emit** — the receiver may be deleted; log at debug.

Only signal handlers on the main thread touch widgets.

---

## Data access

Two clients, same duck-typed interface (`connect`, `list_tables`,
`describe_table`, `query`, `close`):

- `DirectSqlClient` (SQLAlchemy) — PostgreSQL and MySQL. The default path.
- `SyncMcpClient` (MCP stdio subprocess) — SQLite only. The original design;
  direct SQL was added because spawning `npx` on Windows was fragile.

`ConnectWorker` also builds the `SourceFingerprint` while the introspected
schema is in hand, and emits it on `ConnectSignals.finished`.

Type hints across the codebase still say `SyncMcpClient` where a
`DirectSqlClient` is passed. Read them as "SQL client".

---

## Known issues — do not re-discover these

| # | Issue | Where |
|---|---|---|
| 1 | KPIs computed over `exec_rows` (first 500) while `row_count` reports the full result — a `sum` under-reports silently. Also truncates long series before detection. | `core/orchestrator.py` |
| 2 | `list_tables`/`describe_table` hardcode `table_schema = 'public'` (Postgres-only) though MySQL is offered in the UI. | `core/sql_client.py` |
| 3 | `describe_table` f-string-interpolates the table name into SQL. | `core/sql_client.py` |
| 4 | Misleading `SyncMcpClient` type hints. | `orchestrator.py`, `data_source_panel.py` |
| 5 | `fill_chart_from_rows` calls `float(...)` unguarded — non-numeric y-column raises mid-render. | `core/row_utils.py` |

**Fixed (do not reintroduce):** loguru's default `diagnose=True` printed local
variable values in tracebacks, which put the `x-goog-api-key` header into
`data/logs/app.log`. Sinks now live in `app/log_config.py` with
`diagnose=False`; `tests/test_log_config.py` fails if a secret reaches the log.
Any new `logger.add(...)` must pass `diagnose=False`.

**Commit guard:** `.githooks/pre-commit` (enable per clone with
`git config core.hooksPath .githooks`) blocks key-shaped strings, the literal
`.env` key, and `.env`/logs/history/context files. GitHub secret scanning and
push protection are on for the public repo. Build fake keys at runtime in
tests (`"AIza" + "Q" * 35`) — a literal would trip both guards.

`gemini-3.5-flash` (the default) is a valid model id — verified 2026-11-07; an
earlier note calling it invalid was wrong. The repo is public on GitHub under
MIT; `.env`, `data/` runtime files, `input_data/*.csv` (third-party data) and
`docs/reports/*.docx` (EMBA coursework) are gitignored and must stay out of it.

**Fixed (do not reintroduce):** the planner used to refuse forecast questions
("the dataset contains only historical records"), so "get me a sales forecast"
returned a clarification instead of a series. `sql_planner.md` now covers this
at length — do not trim that section.

**Fixed (do not reintroduce):** dialogs were unstyled, so under a dark-mode
Windows a `QMessageBox` rendered near-white text on its light surface and was
unreadable. `theme.py` now applies a light `QPalette` before the stylesheet and
`styles.qss` names `QDialog` / `QMessageBox` explicitly.

**Fixed (do not reintroduce):** saved analyses had no provenance, so a follow-up
clicked on a replayed item ran silently against whichever database happened to
be connected; `_chat_history` also survived source changes. Now gated by
`SourceFingerprint` + modal, with `_reset_session_state()` on every source
transition.

**Fixed (do not reintroduce):** history persistence used to drop the entire
predictive layer — `forecastable`, `ts_profile`, `available_methods`, `forecast`
were never serialised, so replaying a history item silently lost the forecast
while `report_export` still emitted one. Now the result is stored verbatim
alongside its inputs, covered by `tests/test_history_db.py`.

Forecasting-specific limitations (approximate Holt/Holt-Winters bands, MAPE
asymmetry, single-holdout selection bias, fixed SARIMA orders, no interval
coverage check, no MASE) are catalogued in
`docs/reports/forecasting/05-backtesting.md` §7.

If you fix one, remove it from this table, from `docs/ARCHITECTURE.md` §14, and
from the README where referenced.

---

## Conventions

- `from __future__ import annotations` at the top of core modules; modern
  union syntax (`str | None`).
- Dataclasses with `slots=True` for models. No pydantic outside `app/config`.
- Logging via `loguru`, brace-style: `logger.info("Found {} tables", n)`.
- Broad excepts are allowed **only** where a failure must not break the user's
  result, and must carry `# noqa: BLE001` plus a comment saying why. Put the
  *parsing* inside the guard too, not just the compute.
- Docstrings state what the module does *and what it deliberately does not do*
  (e.g. "no LLM, no Qt"). Keep that habit — it is load-bearing documentation.
- Prompts live in `app/resources/prompts/*.md`, loaded via
  `paths.resource_path()`. Never inline a prompt in Python.
- Assets are loaded through `paths.resource_path()` so frozen builds work.
- Anything persisted to JSON must be strict-JSON safe — no NaN, no Inf, and no
  credentials.
- User-facing copy for a dialog belongs in `app/core`, not the widget, so it can
  be asserted in tests.
- **Style every new top-level window explicitly.** Dialogs inherit nothing from
  the `QMainWindow` rule, so an unstyled `QMessageBox` picks up the OS palette
  and goes white-on-white under dark-mode Windows. `theme.py` applies a light
  `QPalette` as a floor *before* the stylesheet; `styles.qss` names `QDialog`,
  `QMessageBox`, and Qt's internal `qt_msgbox_label` /
  `qt_msgbox_informativelabel`. Never rely on colour inheritance for a new
  dialog. The accent themes remap only the indigo family — surface and text
  colours are deliberately outside that map so contrast cannot break.
- Anything shown on the canvas should also reach the HTML export. They have
  drifted apart twice.

---

## Working on it

**Environment:** the `.venv` is a Windows venv (`.venv/Scripts/`). A Linux
sandbox cannot run the full suite (no PySide6, loguru, pytest, statsmodels; pip
has no network) but *can* exercise `app/core` and `app/data` — numpy and pandas
are present. Stub `loguru` and a minimal `pytest` (`approx`, `fixture`) on
`PYTHONPATH` and drive the test functions directly. statsmodels methods will be
absent, so only the numpy methods get covered. Anything Qt — dialogs, styling,
widgets — cannot be verified there at all; ask the user to run `test.bat` and to
eyeball UI changes.

**Scripts:** `setup.bat`, `run.bat`, `test.bat`, `load_data.bat <dir> [--keep]`,
`run_postgres.bat`, `run_build.bat`, `download_data.bat`, `download_public.bat`.

**Packaging:** PyInstaller onedir via `conv_analytics.spec`, entry
`entry_point.py`, runtime hook `pyi_runtime_hook.py`. Ship the whole
`dist/ConvAnalytics/` folder. If you add a non-Python asset, add it to `datas`
in the spec **and** load it through `resource_path()`; the spec hard-fails if a
declared asset is missing.

The spec deliberately does **not** call `collect_all("PySide6")` — that bundled
every Qt module (821 MB) and collecting the same DLLs by two routes is a classic
cause of a frozen build that dies silently. Rely on PyInstaller's own PySide6
hooks. When trimming Qt DLLs, remember QtWebEngine needs Qt6Quick, Qt6Qml,
Qt6QuickWidgets, Qt6WebChannel, Qt6Positioning, Qt6Network and the FFmpeg DLLs;
`_DROP_QT_MODULES` lists only what is genuinely unreachable. Do not exclude
`unittest` (numpy.testing imports it) or `mcp.server` (`mcp/__init__.py`
re-exports it). Use plain lists for `a.binaries`/`a.datas`, not `TOC()`, which is
deprecated in PyInstaller 6.

**Diagnosing a frozen build that will not start.** A windowed build has no
console, so failures are invisible. `entry_point.py` writes `boot.log` before
importing the app, enables `faulthandler`, catches `BaseException` into
`crash.log`, and supports `--selftest`, which imports every dependency and
verifies every bundled asset without opening a window. `run_build.bat` /
`run_build.sh` run that automatically after each build and print the report;
they also tee PyInstaller output to `build/build.log` and accept `--debug`
(console build) and `--fast` (skip dependency install). **No log files at all
means the process died before Python started — almost always a missing DLL.**

**Persistence:** settings JSON in `platformdirs.user_config_dir("conv-analytics")`;
API key in the OS keychain (service `conv-analytics`); history in
`data/history.sqlite`; data dictionary in `data/context.md`; logs in
`data/logs/app.log`.

**Docs:** when behaviour changes, update `docs/ARCHITECTURE.md` in the same
change — including the Mermaid diagram, not just the prose. A stale diagram is
worse than none. `docs/plans/` is historical intent, not current truth; do not
"fix" plans to match the code. `docs/reports/forecasting/` is current truth for
the predictive subsystem and must be kept so.

**Reports:** `docs/reports/*.docx` are EMBA deliverables. Never overwrite a
draft — add a new version suffix.

**README screenshots** live in `docs/images/` (1600 px wide, settings 720 px).
To re-shoot without spending tokens, drive `MainWindow` from a script, connect
for real, and replay saved analyses with `_on_history_selected(id)`; capture
with `QWidget.grab()` (it includes WebEngine charts and survives a locked
screen, unlike screen grabs). Point `history_db_path` at a scratch copy and
never let a screenshot show it — the Settings dialog displays that path.

