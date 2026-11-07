# Architecture

AI-Powered Conversational Analytics Platform — a PySide6 desktop application
that answers natural-language questions about a SQL database and, when the
result is a genuine time series, adds a locally computed forecast.

---

## 1. Design principles

The whole architecture follows from four rules:

| # | Principle | Consequence in the code |
|---|---|---|
| 1 | **Never send table data to the LLM.** | The planner sees only a schema summary. The analyst sees at most ~100 rows / 4,000 characters (`row_utils.compact_rows`). |
| 2 | **The LLM writes SQL and prose — never numbers.** | KPIs are recomputed in Python from real rows (`row_utils.compute_kpis`). Forecasts are pure numpy/statsmodels (`core/forecasting.py`), and the predictive narrative is composed in Python (`core/forecast_narrative.py`). |
| 3 | **Read-only by default.** | Two independent gates: `row_utils.is_select_only` before execution and `DirectSqlClient.query`'s prefix check at the driver. |
| 4 | **Degrade, never crash.** | Optional `statsmodels`, optional QtWebEngine, JSON repair-retry, CSV encoding fallbacks, forecast failures leave the descriptive answer intact. |

---

## 2. Component map

```mermaid
graph TB
    subgraph UI["app/ui — Qt widgets (main thread)"]
        MW["MainWindow<br/>orchestration + state"]
        DSP["DataSourcePanel<br/>connect / tables / context"]
        HP["HistoryPanel"]
        CP["ChatPanel"]
        CV["CanvasPanel<br/>KPIs, charts, forecast controls"]
        SD["SettingsDialog"]
        NO["notices<br/>modal warnings"]
    end

    subgraph WK["app/ui/workers — QThreadPool"]
        AW["AnalysisWorker"]
        CW["ContextWorker"]
        FW["ForecastWorker<br/>(local, 0 tokens)"]
    end

    subgraph CORE["app/core — engine (no Qt)"]
        ORC["Orchestrator"]
        PL["gemini_planner<br/>NL → SQL"]
        AN["gemini_analyst<br/>rows → insight"]
        GC["GeminiClient"]
        RU["row_utils<br/>KPIs / chart fill / SELECT gate"]
        TS["timeseries<br/>relevance gate"]
        FC["forecasting<br/>7 methods + auto + backtest"]
        SQL["DirectSqlClient"]
        MCP["SyncMcpClient"]
        SI["schema_indexer"]
        RE["report_export"]
        DS["data_source<br/>provenance + mismatch"]
        FN["forecast_narrative<br/>predictive prose, 0 tokens"]
    end

    subgraph DATA["app/data + app/config"]
        MD["models — dataclasses"]
        HDB["history_db — SQLite"]
        LC["load_csv"]
        ST["Settings + Profiles"]
        KC["keychain"]
    end

    subgraph EXT["External"]
        GEM(["Google Gemini API"])
        PG[("PostgreSQL / MySQL")]
        LITE[("SQLite via MCP server")]
    end

    MW --> DSP & HP & CP & CV & SD
    MW --> NO --> DS
    DSP --> DS
    MW --> AW & CW
    CV --> FW
    AW --> ORC
    CW --> AN
    ORC --> PL & AN & RU & FC
    PL & AN --> GC --> GEM
    FC --> TS
    FW --> FC
    CV --> FN --> FC
    RE --> FN
    DSP --> SQL --> PG
    DSP --> MCP --> LITE
    DSP --> SI
    ORC --> SQL
    MW --> HDB
    CV --> RE
    SD --> ST & KC
    ORC -.-> MD
```

### Package responsibilities

| Package | Rule |
|---|---|
| `app/core` | Pure engine. **No Qt imports.** Unit-testable in isolation. |
| `app/data` | Dataclasses, SQLite history, CSV ingestion, column normalisation. |
| `app/config` | Settings persistence (JSON, `platformdirs`) and OS keychain access. |
| `app/ui` | Widgets, dialogs, charts. Holds no business logic beyond presentation. |
| `app/ui/workers` | `QRunnable` bridges — the only place where core meets threads. |
| `app/resources` | Prompt Markdown files and the vendored `echarts.min.js`. |

---

## 3. The three-step pipeline

The heart of the app is `Orchestrator.ask()`. One question costs **exactly two
Gemini calls** (plus a one-off context build at connect time).

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant MW as MainWindow
    participant W as AnalysisWorker<br/>(thread pool)
    participant O as Orchestrator
    participant G as Gemini
    participant DB as SQL database
    participant F as forecasting<br/>(local)

    U->>MW: "Top 10 products by revenue in 2024"
    MW->>MW: set_question_header + show_loading
    MW->>W: start(question, chat_history)

    W->>O: ask(question, history)

    rect rgba(120,140,255,0.10)
    note over O,G: STEP 1 — PLAN (schema only, no row data)
    O->>G: sql_planner.md + context.md + history + question
    G-->>O: {sql, chart_intent, rationale,<br/>needs_clarification, forecast_requested}
    end

    alt needs_clarification or empty SQL
        O-->>W: clarification Analysis (no SQL run)
    else not SELECT-only
        O-->>W: refusal Analysis
    else
        rect rgba(120,200,140,0.12)
        note over O,DB: STEP 2 — EXECUTE (no LLM involved)
        O->>DB: execute plan.sql
        DB-->>O: rows (capped at max_rows)
        O->>O: exec_rows = rows[:500]<br/>compact = compact_rows(exec_rows)
        end

        rect rgba(120,140,255,0.10)
        note over O,G: STEP 3 — ANALYSE (≤100 rows / 4k chars)
        O->>G: analyst.md + question + SQL + compact rows
        G-->>O: {summary, kpi_specs, insights, charts, suggestions}
        end

        O->>O: fill_charts_from_rows + compute_kpis<br/>(real numbers, recomputed in Python)

        rect rgba(255,190,120,0.15)
        note over O,F: STEP 4 — FORECAST (0 tokens, 0 SQL)
        O->>F: forecast_bundle(exec_rows, chart, ...)
        F-->>O: profile + methods + ForecastResult, or None
        alt None and forecast_requested
            O->>O: explain_not_forecastable() → forecast_note
        end
        end

        O-->>W: Analysis
    end

    W-->>MW: finished(Analysis)
    MW->>MW: canvas.render + history_db.save_analysis
```

### Why this is cheap

```mermaid
graph LR
    A["Full table<br/>~10⁶ rows"] -->|never sent| X["✕ LLM"]
    B["Schema + 5 sample rows/table"] -->|once per connect| C["Context build"]
    C --> D["context.md<br/>~4 KB"]
    D -->|every question| E["Planner call"]
    F["≤100 result rows<br/>≤4 KB"] -->|every question| G["Analyst call"]
    H["Forecast"] -->|"0 tokens"| I["Local numpy/statsmodels"]

    style X fill:#ffd9d9,stroke:#c00
    style I fill:#d9ffe0,stroke:#0a0
```

---

## 4. Connection lifecycle

Connections are generational. Every connect/disconnect bumps
`MainWindow._connection_gen`, and workers carry the generation they were born
in — so results from an abandoned connection are dropped instead of crashing
against a closed SQL client.

```mermaid
stateDiagram-v2
    [*] --> Disconnected

    Disconnected --> Connecting: Connect clicked
    Connecting --> Disconnected: connect failed (banner)
    Connecting --> Connected: list_tables + describe_table OK

    state Connected {
        [*] --> BuildingContext
        BuildingContext --> Ready: ContextWorker writes data/context.md
        BuildingContext --> Ready: build failed (schema-only context kept)
        Ready --> Analysing: question submitted
        Analysing --> Ready: Analysis rendered + saved
        Analysing --> Ready: error banner
    }

    Connected --> Disconnected: Disconnect / DB type changed
    note right of Connected
        _connection_gen++ on every
        transition in or out.
        Stale worker results are
        discarded by generation check.
    end note
```

Two things happen the moment a connection succeeds:

1. **`ContextWorker`** asks Gemini to turn schema + sample rows into a rich
   Markdown data dictionary, cached at `data/context.md`.
2. **`_run_default_analytics()`** immediately fires a canned overview question
   so the canvas is never empty.

---

## 5. Data access: two clients, one interface

```mermaid
graph LR
    DSP["DataSourcePanel<br/>ConnectWorker"]
    DSP -->|postgres / mysql| DSC["DirectSqlClient<br/>SQLAlchemy engine"]
    DSP -->|sqlite| SMC["SyncMcpClient<br/>stdio MCP subprocess"]
    DSC --> PG[("PostgreSQL")]
    SMC --> SRV["@modelcontextprotocol<br/>server-*"] --> LITE[("SQLite")]

    DSC -.->|"connect / list_tables /<br/>describe_table / query / close"| IFACE{{"shared duck-typed<br/>interface"}}
    SMC -.-> IFACE
```

Both classes expose the same five methods, so the `Orchestrator` does not care
which it holds. The MCP path exists because it was the original design; the
direct path was added because spawning `npx` subprocesses on Windows proved
fragile.

> **Naming caveat:** the type hints still say `SyncMcpClient`
> (`Orchestrator.__init__`, `DataSourcePanel._client`) even though the Postgres
> and MySQL paths pass a `DirectSqlClient`. Read those annotations as
> "SQL client", not as a literal type.

---

## 6. Predictive analytics — the relevance gate

> **Full treatment:** this section summarises the subsystem. The mathematics of
> each method, the detection rules, parameter semantics and the evaluation
> procedure are documented in the
> [forecasting report series](reports/forecasting/README.md).

Forecast controls appear **only** on data that is genuinely a time series.
`timeseries.detect_time_series` is the gate; it returns `None` for anything
else, and `None` means the forecast layer is silently skipped.

```mermaid
flowchart TD
    A["exec_rows from STEP 2"] --> B{"rows non-empty<br/>and dict-shaped?"}
    B -->|no| Z(["No forecast"])
    B -->|yes| C["Pick time column<br/>(chart x_column → hint → best guess)"]
    C --> D{"≥90% of values<br/>parse as dates?<br/>(PARSE_THRESHOLD)"}
    D -->|no| Z
    D -->|yes| E["Pick numeric value column<br/>(≥80% numeric)"]
    E --> F{"≥6 points?<br/>(MIN_POINTS)"}
    F -->|no| Z
    F -->|yes| G["Sort + infer spacing<br/>D / W / M / Q / Y bands"]
    G --> H{"≥60% of gaps match<br/>one band? (_REGULARITY)"}
    H -->|no| Z
    H -->|yes| I["TimeSeriesProfile<br/>freq, seasonal_period, x, y"]
    I --> J["available_methods(profile)"]
    J --> K["forecast(profile, method,<br/>horizon, confidence)"]
    K --> L(["Forecast band + backtest<br/>metrics on the canvas"])

    style Z fill:#f2f2f2,stroke:#999
    style L fill:#d9ffe0,stroke:#0a0
```

### Forecast questions are first-class

"Get me weekly sales" and "get me a sales forecast" must produce substantially
the same SQL. The planner prompt states this outright, because the model's
instinct is otherwise to refuse a forecast on the grounds that the database
holds no future rows — which is true and irrelevant, since the app forecasts
locally from the history the SQL returns.

`SqlPlan.forecast_requested` records that the user asked. It changes nothing
about the SQL; it means that if detection then fails, the app owes an
explanation rather than a silently descriptive answer.
`timeseries.explain_not_forecastable()` produces it — naming the missing date
column, the period count that fell short of six, or the irregular spacing — and
it surfaces both as a modal and as a card in place of the predictive section.

### Method availability is data-driven

| Method | Offered when | Engine |
|---|---|---|
| `auto` | always (picks the best by backtest) | — |
| `naive` | always | numpy |
| `moving_average` | always | numpy |
| `linear_trend` | always | numpy |
| `holt` | `n_points ≥ 6` | statsmodels |
| `seasonal_naive` | series is seasonal | numpy |
| `holt_winters` | series is seasonal | statsmodels |
| `sarima` | `seasonal_period ≤ 24` and `n_points ≥ max(2·period, 16)` | statsmodels |

Seasonal periods by frequency: `D→7`, `W→52`, `M→12`, `Q→4`, `Y→none`.
Confidence bands use hardcoded z-scores (`0.80→1.2816` … `0.99→2.5758`) to
avoid a SciPy dependency. If `statsmodels` is missing, the statistical methods
disappear from the list and the numpy methods carry on.

### Transparency: the “Model details” panel

`Auto` picking a method invisibly is a black box, so everything behind it is
inspectable in a collapsible panel under the Forecast controls. All of it is
local arithmetic over history already in memory.

| Section | Source | Shows |
|---|---|---|
| Series diagnostics | `series_diagnostics()` | Time column, measure, detected grain, period count, date range, seasonality, backtest holdout, observed range |
| Method comparison | `compare_methods()` | MAPE / MAE / RMSE for every eligible method, sorted best-first, with the one in use marked |
| Availability | `method_availability()` | Every known method with why it is offered or withheld — too few points, not seasonal, statsmodels absent, seasonal period too long |
| Parameter help | `METHOD_NOTES`, tooltips | What each method assumes; horizon in the series' own units; what a confidence band means |

The comparison table is what makes `Auto` auditable: its winner must be the top
scored row, and a test asserts exactly that.

### Predictive analytics narrative

Whenever a forecast exists, a **Predictive Analytics** card renders beneath
**Descriptive Analytics**, in the same shape — a summary paragraph then
bullets. `app/core/forecast_narrative.py` composes it in Python: direction and
size of change, horizon total against the prior equivalent window, which model
and its backtest accuracy in words, band width at the far end, whether
seasonality is present and whether the chosen model uses it, and whether the
projection leaves observed territory.

**This costs zero tokens and no Gemini call.** That is not only economy — rule
two says the LLM never states a predicted number, and the surest way to hold
that line is to never ask it to. Being deterministic, the prose is also
assertable in tests, and the HTML export renders the identical text so a report
and the screen cannot disagree.

### Recompute is free

Changing method, horizon, or confidence dispatches a `ForecastWorker` that
re-runs `forecasting.forecast()` over the in-memory `TimeSeriesProfile`.
**No Gemini call. No SQL. No network.** Results are memoised in
`forecasting._CACHE`.

---

## 7. Data model

```mermaid
classDiagram
    class Analysis {
        +str question
        +str sql
        +str summary
        +int row_count
        +int elapsed_ms
        +int planner_tokens
        +int analyst_tokens
        +bool forecastable
        +bool forecast_requested
        +str forecast_note
        +bool needs_clarification
        +all_charts() list
    }
    class SqlPlan {
        +str sql
        +ChartIntent chart_intent
        +str rationale
        +bool needs_clarification
        +bool forecast_requested
    }
    class SourceFingerprint {
        +str name
        +str kind
        +str target
        +str schema_hash
        +int table_count
    }
    class ResultInsight {
        +str summary
        +list insights
        +list suggestions
    }
    class ChartSpec {
        +ChartKind kind
        +str title
        +list x
        +list series
        +dict options
    }
    class Kpi {
        +str label
        +str value
        +str delta
        +str trend
    }
    class KpiSpec {
        +str label
        +str aggregation
        +str column
        +str format
    }
    class TimeSeriesProfile {
        +str time_column
        +str value_column
        +str freq
        +int n_points
        +int seasonal_period
        +bool is_seasonal
    }
    class ForecastResult {
        +str method
        +int horizon
        +float confidence
        +dict metrics
        +list warnings
    }
    class ForecastPoint {
        +str x
        +float yhat
        +float lower
        +float upper
    }

    Analysis "1" o-- "*" Kpi
    Analysis "1" o-- "*" KpiSpec
    Analysis "1" o-- "*" ChartSpec
    Analysis "1" o-- "0..1" TimeSeriesProfile
    Analysis "1" o-- "0..1" ForecastResult
    Analysis "1" o-- "0..1" SourceFingerprint
    ForecastResult "1" o-- "*" ForecastPoint
    ResultInsight "1" o-- "*" ChartSpec
    ResultInsight "1" o-- "*" Kpi
    ResultInsight "1" o-- "*" KpiSpec
```

`KpiSpec` vs `Kpi` is the key distinction: the LLM emits a **spec**
(`{label, aggregation, column, format}`), and Python computes the **value** from
real rows. The model never states a figure that wasn't calculated.

---

## 8. Threading model

Everything expensive runs on `QThreadPool.globalInstance()`; only signal
handlers touch widgets.

```mermaid
graph TB
    subgraph MAIN["Main (GUI) thread"]
        M1["MainWindow / panels"]
        M2["Signal handlers → render"]
    end
    subgraph POOL["QThreadPool"]
        T1["ConnectWorker<br/>connect + introspect"]
        T2["ContextWorker<br/>Gemini context build"]
        T3["AnalysisWorker<br/>full pipeline"]
        T4["ForecastWorker<br/>local recompute"]
    end
    M1 -->|start| T1 & T2 & T3 & T4
    T1 -->|finished/failed| M2
    T2 -->|ready/failed| M2
    T3 -->|summary_streamed/finished/failed| M2
    T4 -->|finished/failed| M2
```

Three safety mechanisms are worth knowing about:

- **Generation guard** — each worker stores `connection_gen` and an `is_current`
  callback; stale emissions are dropped.
- **Parented signal objects** — `WorkerSignals(parent)` keeps the `QObject`
  alive for the runnable's lifetime.
- **`RuntimeError` swallowing** — emitting to a deleted receiver is logged at
  debug level rather than crashing.

---

## 9. Persistence

```mermaid
erDiagram
    conversations ||--o{ analyses : contains
    conversations {
        int id PK
        text title
        text created_at
    }
    analyses {
        int id PK
        int conversation_id FK
        text question
        text analysis_json
        text created_at
        int favorite
    }
```

The `Analysis` is serialised to JSON in `analysis_json`, so replaying a history
item re-renders the canvas with **zero API calls and zero SQL**. `init_db`
performs an inline migration adding `favorite` to older databases.

The two halves of an analysis are stored differently — deliberately:

```mermaid
graph LR
    subgraph SAVE["save_analysis"]
        D1["Descriptive:<br/>summary, insights, charts<br/>with x + series data,<br/>KPI values as formatted strings"] --> V["stored verbatim"]
        P1["Predictive result:<br/>points, band, fitted,<br/>metrics, warnings"] --> V2["stored verbatim"]
        P2["Predictive inputs:<br/>TimeSeriesProfile +<br/>method / horizon / confidence"] --> I["stored alongside"]
    end
    subgraph LOAD["get_analysis"]
        V --> R1["re-rendered as-is"]
        V2 --> R2["restored as-is —<br/>needs no numpy"]
        I --> R3["powers the controls:<br/>change method / horizon<br/>→ local recompute"]
    end
    R1 & R2 & R3 --> C["identical canvas,<br/>still interactive"]
```

**Descriptive** results are stored verbatim: chart `x`/`series` data is embedded
and KPIs are stored as the already-computed formatted strings, so replay never
recomputes a number that was shown to the user.

**Predictive** results are stored the same way, and then some. The full
`ForecastResult` — every point, confidence band, fitted value, backtest metric
and warning — is persisted under `forecast`, so the record of what the user
actually saw is authoritative and cannot drift if the forecasting code changes
later. Rebuilding it requires nothing but the stored dicts, so history replays
even where numpy is unavailable.

Its *inputs* are stored alongside: the `TimeSeriesProfile`, the **resolved**
method (`auto` has already collapsed to what the backtest chose), horizon,
confidence, and `available_methods`. Those are what keep the forecast controls
live — changing method or horizon on a replayed item recomputes locally against
the stored profile, exactly as on a fresh result. Total predictive payload is
about 2.6 KB for a 36-point series with a 12-period horizon.

| Situation | Behaviour |
|---|---|
| Result + inputs present | Result restored verbatim; controls interactive |
| Inputs only (older payload) | Forecast recomputed — deterministic, so identical |
| Result only, no profile | Forecast displayed; `forecastable=False`, controls hidden |
| Neither | Descriptive-only replay |
| Malformed profile or points | Degrades to descriptive-only; never raises |

Each payload also carries `source` (the `SourceFingerprint`, password-free), `needs_clarification`, and `forecast_requested` / `forecast_note` — so a replayed analysis explains a missing forecast exactly as the live one did.

NaN metrics (returned by `backtest` on series too short to score) are written as
`null` — bare `NaN` is not valid JSON. Both consumers, `report_export` and
`canvas_panel._set_forecast_badge`, already guard on `None` before their NaN
check. All of the above is covered by `tests/test_history_db.py`.

| What | Where |
|---|---|
| Settings (non-secret) | `platformdirs.user_config_dir("conv-analytics")/config.json` |
| Gemini API key | OS keychain, service `conv-analytics` |
| Conversation history | `data/history.sqlite` |
| Data dictionary | `data/context.md` |
| Logs | `data/logs/app.log` (1 MB rotation, 5 kept), `crash.log` |

---

## 10. Data-source provenance

A saved analysis outlives the connection that produced it. Its suggested
follow-ups, drill-downs and Refresh button are all questions written against
*that* database's schema — so running them against whatever happens to be
connected now would produce a confident, unrelated answer.

Every `Analysis` therefore carries a `SourceFingerprint`, computed at connect
time from the active profile plus the schema just introspected:

| Field | Purpose |
|---|---|
| `name`, `kind` | Profile label and engine, for the dialog wording |
| `target` | Connection URL, **password redacted** — fingerprints are persisted |
| `schema_hash` | 12-hex digest of sorted `table(column,…)` names |
| `table_count` | Displayed in the dialog |

`schema_hash` deliberately ignores column *types* and result ordering, so a
widening `int4 → int8` is not a change, but a renamed column is. That makes it
catch the case a URL comparison misses: `load_data.bat` drops and recreates the
public schema, so the same URL can hold entirely different data.

```mermaid
flowchart TD
    A["User clicks a suggested follow-up,<br/>drill-down, or Refresh"] --> B{"Connected?"}
    B -->|no| N1["Modal: Not connected"]
    B -->|yes| C["compare(displayed.source, live.source)"]
    C -->|None| G["Run the question"]
    C -->|different_target| M1["Modal: belongs to another database<br/>names both, says how to reconnect"]
    C -->|schema_changed| M2["Modal: data reloaded since save"]
    C -->|unknown_source| M3["Modal: no provenance recorded"]
    M1 & M2 & M3 --> D{"Ask anyway?"}
    D -->|Cancel<br/>(default)| X(["Nothing runs"])
    D -->|Ask anyway| G
    G --> H{"API key set?"}
    H -->|no| N2["Modal: API key required<br/>→ Open Settings"]
    H -->|yes| I["AnalysisWorker"]
    I -->|needs_clarification| N3["Modal: question doesn't fit this data"]
    I -->|exception| N4["Modal: classified failure"]
    I -->|ok| R(["Rendered"])

    style X fill:#f2f2f2,stroke:#999
    style R fill:#d9ffe0,stroke:#0a0
```

The gate applies only to questions **derived from what is on screen**. A
question typed into the chat box is a new question about the current data and
passes straight through. Cancel is the default button — the safe choice needs
no thought — but the mismatch is a warning, not a block, since the question may
still be valid against the new schema.

`app/core/data_source.py` holds the logic and, deliberately, the dialog
*wording* (`explain()`), so the copy is testable without Qt.
`app/ui/dialogs/notices.py` is the thin Qt layer.

### Session state is per–data source

Switching databases resets more than the connection. `_reset_session_state`
also clears `_chat_history` and opens a new conversation, because:

- chat history is fed to the planner as conversation context — DB A's Q&A would
  otherwise shape DB B's SQL;
- `_current_conv_id` would otherwise file results from two databases under one
  conversation in the history panel.

This fires on disconnect, on database-type change, and on a reconnect whose
fingerprint differs from the previous one.

---

## 11. Rendering

```mermaid
graph LR
    CS["ChartSpec"] --> BC["charts.build_chart()"]
    BC -->|QtWebEngine present| WCW["WebChartWidget<br/>ECharts in QWebEngineView"]
    BC -->|ImportError| FB["QtCharts fallback<br/>bar / line / donut"]
    WCW <-->|QWebChannel| BR["_ChartBridge<br/>category_clicked"]
    BR --> DD["drilldown_requested →<br/>'Drill into &lt;category&gt;'"]
```

### Theming and dialog contrast

`theme.py` applies a fully-specified light `QPalette` **before** the stylesheet.
The palette is the floor for widgets `styles.qss` never names — message boxes,
menus, popups — and the stylesheet overrides it wherever it does.

This matters because dialogs are separate top-level windows and inherit nothing
from the `QMainWindow` rule. Without explicit colours they fall through to the
operating system palette, so on a dark-mode Windows a `QMessageBox` rendered
near-white text on its light surface and was unreadable. `styles.qss` now names
`QDialog`, `QMessageBox`, and Qt's internal `qt_msgbox_label` /
`qt_msgbox_informativelabel`.

The three accent themes remap only the indigo family; surface and text colours
are deliberately outside that map, so contrast cannot be broken by a theme
switch.

ECharts is **vendored** at `app/resources/vendor/echarts.min.js` — the app makes
no CDN calls and renders offline. Clicking a category in a chart emits a
drill-down that becomes the next natural-language question.

---

## 12. Packaging

```mermaid
graph LR
    EP["entry_point.py"] --> SPEC["conv_analytics.spec"]
    SPEC --> PYI["PyInstaller onedir"]
    PYI --> OUT["dist/ConvAnalytics/<br/>ConvAnalytics.exe + _internal/"]
    RH["pyi_runtime_hook.py"] --> PYI
    ASSETS["styles.qss, chart_shell.html,<br/>prompts/, vendor/echarts.min.js"] --> PYI
    QT["QtWebEngineProcess.exe<br/>+ Chromium resources"] --> PYI
```

`app/paths.py` is the single source of truth for path resolution:

| Function | Dev | Frozen |
|---|---|---|
| `app_dir()` | repo root | folder containing the `.exe` |
| `bundle_dir()` | repo root | `sys._MEIPASS` |
| `resource_path(*p)` | `<repo>/app/...` | `<_MEIPASS>/app/...` |

`ensure_app_cwd()` chdirs beside the executable when frozen so relative `data/`
paths behave. Ship the **entire** `dist/ConvAnalytics/` folder — the `.exe`
alone will not run.

---

## 13. Security boundaries

```mermaid
graph TD
    Q["User question"] --> P["Planner (LLM)"]
    P --> S["Generated SQL"]
    S --> G1{"is_select_only()<br/>orchestrator"}
    G1 -->|reject| R["Clarification response"]
    G1 -->|pass| G2{"DirectSqlClient<br/>readonly prefix check"}
    G2 -->|reject| R
    G2 -->|pass| EX["Execute, fetchmany(max_rows)"]

    style R fill:#ffd9d9,stroke:#c00
```

| Control | Where | Strength |
|---|---|---|
| SELECT/WITH-only | `row_utils.is_select_only` | prefix check |
| Read-only client | `DirectSqlClient.query` | prefix check |
| Row cap | `fetchmany(max_rows)`, default 10,000 | hard |
| Secrets | OS keychain via `app/config/keychain.py` | good |
| No table data to LLM | by construction | strong |

Both SQL gates are **prefix checks**, not parsers. For an untrusted database,
back them with a genuinely read-only database role — that is the only control
that cannot be talked around.

---

## 14. Known issues

Carry these forward; they are real and currently unfixed.

| # | Issue | Location |
|---|---|---|
| 1 | KPIs are computed over `exec_rows` (first 500) while `row_count` reports the full result — a `sum` over a larger result silently under-reports. | `app/core/orchestrator.py` (`MAX_EXEC_ROWS`) |
| 2 | `list_tables`/`describe_table` hardcode `table_schema = 'public'` (Postgres-only) although MySQL is offered in the UI. | `app/core/sql_client.py` |
| 3 | `describe_table` interpolates the table name into SQL with an f-string. | `app/core/sql_client.py` |
| 4 | Type hints say `SyncMcpClient` where a `DirectSqlClient` is actually passed. | `orchestrator.py`, `data_source_panel.py` |
| 5 | `fill_chart_from_rows` calls `float(...)` unguarded — a non-numeric y-column raises `ValueError` mid-render. | `app/core/row_utils.py` |
| 6 | The file log sink keeps loguru's default `diagnose=True`, so `logger.exception` tracebacks print local variables — including the Gemini request's `x-goog-api-key` header — into `data/logs/app.log`. Treat logs as secret until fixed (`diagnose=False` on the sink). | `app/main.py` (`_configure_logging`) |

**Fixed:** saved analyses had no record of which database produced them, so
clicking a suggested follow-up on a replayed item silently ran it against
whatever was connected — and `_chat_history` was never cleared on a source
change, feeding one database's Q&A into another's planner prompt. Analyses now
carry a `SourceFingerprint` and derived questions are gated by a modal (§10).

**Fixed:** history persistence previously dropped the entire predictive layer —
`forecastable`, `ts_profile`, `available_methods` and `forecast` were never
serialised, so replaying a history item silently lost the forecast while the
export path still emitted one. The computed result is now stored verbatim
alongside its inputs (§9), with round-trip coverage in
`tests/test_history_db.py`.

---

## 15. Repository layout

```
ConversationalAnalyticsPlatform/
├── app/
│   ├── config/      settings.py, keychain.py
│   ├── core/        orchestrator, gemini_*, sql_client, mcp_client,
│   │                timeseries, forecasting, forecast_narrative,
│   │                row_utils, report_export, data_source, schema_indexer
│   ├── data/        models.py, history_db.py, load_csv.py, download_*.py
│   ├── resources/   prompts/*.md, vendor/echarts.min.js
│   ├── ui/          main_window, widgets/, charts/, workers/,
│   │                dialogs/ (settings_dialog, notices)
│   ├── main.py      entry point
│   └── paths.py     dev vs frozen path resolution
├── docs/
│   ├── ARCHITECTURE.md   this file
│   ├── plans/            historical design plans + diagnostics
│   ├── tools/            docs build: mermaid_render, build_reports_docx
│   └── reports/          forecasting/ report series (+ docx), EMBA drafts
├── tests/           pytest suite (core only; UI is not covered)
├── input_data/      sample CSVs for load_data.bat
├── data/            context.md, history.sqlite, logs/, pgdata/
├── conv_analytics.spec   PyInstaller spec
└── *.bat            setup / run / test / load_data / run_build
```
