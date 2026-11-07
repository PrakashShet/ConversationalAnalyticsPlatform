# Plan — Conversational Descriptive Analytics with Interactive Charts

> Goal: a chat-driven analytics app where (1) connecting builds a compact **data
> context** from *columns + 5 sample rows only*, (2) each question is turned into
> a **SQL query** using that context (no raw data sent), (3) the SQL **result rows**
> are sent back to the LLM to produce **descriptive narrative + interactive chart
> specs**, and (4) the right panel renders **interactive charts**.
>
> This plan refactors the existing app (Google Gemini + `DirectSqlClient` +
> `Orchestrator` + `CanvasPanel`). Work stage-by-stage; each stage is one Cursor
> Composer session. Run the Verify step before moving on. Commit between stages.

---

## Architecture target (the split)

```
Connect  ─►  Profiler (columns + 5 rows)  ─►  [LLM A] build data_context.md
                                                     │ (cached, reused)
Question ─►  [LLM B] NL → SQL (context only, NO data) ─► SQL
         ─►  DirectSqlClient executes SQL            ─► result rows (capped)
         ─►  [LLM C] rows → narrative + chart spec(s) ─► Analysis
         ─►  CanvasPanel renders INTERACTIVE charts
```

Three LLM roles, clearly separated:
- **A. Context builder** (once per connect): columns + 5 sample rows → markdown data dictionary.
- **B. SQL planner**: question + data_context + history → `{sql, chart_intent}`. Never sees row data; never returns numbers.
- **C. Analyst/visualizer**: question + executed result rows (compact) → `{summary, kpis, insights, charts[]}` where each chart is an interactive spec. Numbers come only from real rows.

---

# STAGE 1 — Fix data hygiene (column normalization)

**Why.** PostgreSQL folds unquoted identifiers to lowercase; CSV headers like
`Category` and `Order Date` (with a space) currently force fragile quoting and
cause intermittent `column "category" does not exist` failures.

**Files**
- `app/data/load_csv.py`

**Cursor prompt**
```
In app/data/load_csv.py, normalize column names before loading each CSV:
- lowercase, strip, replace any run of non-alphanumeric chars with "_",
  collapse repeats, trim leading/trailing "_".
- guarantee uniqueness (append _2, _3 on collisions).
Apply the mapping to the DataFrame columns prior to df.to_sql.
Print the original→normalized mapping per table in the load summary.
Add a unit test in tests/test_load_csv.py for the normalizer
(e.g. "Order Date"→"order_date", "Sales"→"sales").
```

**Verify**
```
load_data.bat data\raw
```
Reload Superstore; confirm columns become `order_date`, `sales`, `category`, etc.,
and queries no longer need quoting.

Commit: `git commit -am "stage 1: normalize CSV column names"`

---

# STAGE 2 — Lean connection context (columns + 5 rows only)

**Why.** The context must be built from *only* the schema (columns + types) and
5 sample rows per table — never the full table.

**Files**
- `app/ui/workers/context_worker.py`
- `app/core/gemini_client.py` (`build_data_context`)
- `app/core/schema_indexer.py`

**Cursor prompt**
```
Reference: @app/ui/workers/context_worker.py @app/core/gemini_client.py

Make the connect-time context strictly lean:
1. ContextWorker: for each table (cap 12), fetch ONLY:
   - column names + types (already via describe_table), and
   - exactly 5 sample rows (SELECT * ... LIMIT 5).
   Do NOT fetch counts or full scans. Build a samples dict {table: rows}.
2. gemini_client.build_data_context(schema_md, samples):
   - cap the serialized samples to ~4000 chars total,
   - instruct Gemini to output a compact markdown data dictionary:
     per table → purpose, column table (name, type, meaning),
     observed categorical values / ranges (from the 5 rows only),
     and 3 example questions.
3. Save to data/context.md, show in the Data source panel (already wired),
   and set it as the Orchestrator context.
Log the token usage of the context build.
```

**Verify**
Connect → "Data context" panel shows a concise dictionary; `data/context.md`
exists; context-build tokens logged are small (a few thousand).

Commit: `git commit -am "stage 2: lean data context"`

---

# STAGE 3 — Split the LLM: NL → SQL planner (no data)

**Why.** Stage B must translate the conversation to SQL using only the context.
It must not fabricate numbers or receive row data.

**Files**
- `app/core/gemini_client.py` — add `plan_sql(question, context_md, history) -> SqlPlan`
- `app/data/models.py` — add `SqlPlan { sql: str, chart_intent: str, rationale: str, needs_clarification: bool }`
- `app/resources/prompts/sql_planner.md` — new system prompt

**Cursor prompt**
```
Reference: @app/core/gemini_client.py @app/data/models.py

Add a dedicated NL→SQL planning step:
1. models.py: add dataclass SqlPlan(sql, chart_intent, rationale, needs_clarification).
   chart_intent ∈ {"kpi","bar","line","donut","table","auto"}.
2. prompts/sql_planner.md: system prompt that, given the data_context and the
   user question + short history, returns ONLY JSON {sql, chart_intent,
   rationale, needs_clarification}. Rules: SELECT-only, single statement, use
   exact (normalized) column names from context, add sensible LIMIT, and if the
   question is out of scope set sql="" and needs_clarification=true with a
   polite rationale.
3. gemini_client.plan_sql(...) -> SqlPlan using response_mime_type=application/json.
Keep this call free of any row data.
```

**Verify**
Unit-test `plan_sql` with a fake context: "top 5 states by sales" → returns a
SELECT with LIMIT 5 and `chart_intent="bar"`.

Commit: `git commit -am "stage 3: NL→SQL planner"`

---

# STAGE 4 — Execute + analyst/visualizer (rows → charts)

**Why.** Stage C turns *real* SQL result rows into the descriptive narrative and
interactive chart spec(s). Numbers come only from executed rows.

**Files**
- `app/core/orchestrator.py` — rewrite `ask()` to: plan_sql → execute → summarize
- `app/core/gemini_client.py` — add `summarize_result(question, sql, rows) -> ResultInsight`
- `app/data/models.py` — extend `ChartSpec` to support multiple charts + interactivity hints; add `ResultInsight { summary, kpis, insights, charts[] }`
- `app/resources/prompts/analyst.md` — new system prompt

**Cursor prompt**
```
Reference: @app/core/orchestrator.py @app/core/gemini_client.py @app/data/models.py

Implement the two-step pipeline in Orchestrator.ask(question, history):
1. plan = gemini.plan_sql(question, context, history)
   - if plan.needs_clarification or empty sql → return a polite Analysis
     (no SQL execution), reusing existing out-of-scope behavior.
2. rows = mcp.query(plan.sql)   # DirectSqlClient
3. Cap rows to N (e.g. 500) and downsample for the LLM to ~100 rows / 4000 chars.
4. insight = gemini.summarize_result(question, plan.sql, compact_rows)
   - prompts/analyst.md: returns JSON {summary, kpis, insights, charts:[...]}
     where each chart = {kind, title, x, series, options, interactions}.
   - The model proposes chart structure; the app fills series DATA from the real
     rows (never trust LLM numbers).
5. Build Analysis from real rows + insight; keep tokens = planner+analyst totals.
Keep orchestrator free of Qt. Update token accounting to sum both calls.
```

**Verify**
Ask "monthly sales by category" → SQL runs, a multi-series chart spec returns,
series data matches the SQL rows, KPIs computed from rows.

Commit: `git commit -am "stage 4: execute + analyst pipeline"`

---

# STAGE 5 — Interactive charts in the right panel

**Why.** QtCharts is largely static. For hover tooltips, zoom, series toggling,
and click-to-drill, render charts with ECharts inside a `QWebEngineView`.

**Files**
- `app/ui/charts/web_chart.py` — `WebChartWidget(QWebEngineView)` that loads a
  local HTML shell with ECharts and accepts a chart spec via JSON
- `app/ui/charts/__init__.py` — `build_chart` returns the web chart
- `app/ui/widgets/canvas_panel.py` — render multiple charts; wire drill-down
- `requirements.txt` — add `PySide6-WebEngine` (or confirm bundled)

**Cursor prompt**
```
Reference: @app/ui/widgets/canvas_panel.py @app/data/models.py

Replace static QtCharts with interactive ECharts via QWebEngineView:
1. web_chart.py: WebChartWidget builds an ECharts option object from a ChartSpec
   (bar/line/donut/scatter), enables tooltip, dataZoom (for line), legend toggle,
   and emits a Qt signal category_clicked(str) via QWebChannel when a data point
   is clicked (for drill-down).
2. Load ECharts from a vendored local file (app/resources/vendor/echarts.min.js)
   so it works offline; the HTML shell is inlined.
3. build_chart(spec) returns WebChartWidget; canvas renders a list of charts
   (insight.charts) each in its own card with a title.
4. Keep the drill-down → "Drill into <category>" follow-up working through the
   new signal.
Document that PySide6-WebEngine must be installed (add to requirements + setup.bat).
```

**Verify**
Charts show tooltips on hover, legend toggles series, line charts zoom, clicking
a bar triggers a drill-down follow-up.

Commit: `git commit -am "stage 5: interactive ECharts panel"`

---

# STAGE 6 — Conversational polish + suggestions

**Files**
- `app/ui/widgets/canvas_panel.py`, `app/ui/widgets/chat_panel.py`

**Cursor prompt**
```
Add conversational affordances:
1. After each answer, show 3 clickable "suggested follow-up" chips generated by
   the analyst step (add suggestions[] to ResultInsight).
2. Clicking a suggestion submits it as the next question.
3. Keep the last 6 turns of history for context (already partly done); show the
   active question prominently and keep prior answers reachable via History.
```

**Verify**
Ask a question → follow-up chips appear → clicking one runs it with context.

Commit: `git commit -am "stage 6: conversational suggestions"`

---

# STAGE 7 — Verification & guardrails

**Cursor prompt**
```
1. Add tests: NL→SQL planner returns SELECT-only; analyst never overrides row
   numbers; out-of-scope returns polite no-SQL Analysis.
2. SQL guard: reject non-SELECT statements before execution (defense in depth).
3. Token panel: show planner vs analyst token split in the result meta.
4. Update README + this plan's status checkboxes.
```

**Verify**
`test.bat` passes; a non-SELECT never reaches the DB; tokens show split.

Commit: `git commit -am "stage 7: guardrails + tests"`

---

## Working notes for Cursor
- One stage per Composer session; attach files with `@`; run Verify before moving on.
- Numbers ALWAYS come from executed SQL rows, never from the LLM.
- The LLM never receives full tables — only columns + 5 rows (context) and capped
  result rows (analyst step).
- Keep modules under ~250 lines; charts each in their own file.
```
