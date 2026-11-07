# Plan — Add Predictive Analytics (User‑Selectable Forecasting)

> Goal: extend the app from **descriptive** to **predictive** analytics by adding
> time‑series forecasting that (1) is offered **only on relevant data** (a real
> time series), (2) lets the user **choose among several forecasting methods**,
> and (3) is **efficient** — forecasts are computed deterministically in Python
> over rows the app has *already fetched*, adding **zero extra Gemini tokens** and
> **zero extra SQL round‑trips** for the default view; changing method/horizon
> recomputes locally with no API or DB call.
>
> This plan is **plan‑only — no code changes are made here.** It refactors the
> existing pipeline (`Orchestrator` → `gemini_planner` → execute → `gemini_analyst`
> → `CanvasPanel`). Work stage‑by‑stage; each stage is one Cursor Composer
> session. Run the Verify step before moving on. Commit between stages.

---

## Why this fits the current architecture

The app already enforces the key invariant that makes forecasting cheap and safe:
**"numbers always come from executed SQL rows, never the LLM"** (see
`PLAN_INTERACTIVE_ANALYTICS.md`). The analyst step already emits `line` charts
with an `x_column` / `y_column`, and `row_utils.fill_charts_from_rows` already
fills chart series from the real `exec_rows`. Forecasting slots in as a
**deterministic, local post‑processing step on those same rows** — the LLM's role
is unchanged and it never predicts a number.

```
Question ─► [LLM B] NL→SQL ─► execute (MCP)  ─► exec_rows (already capped)
         ─► [LLM C] rows → narrative + charts ─► Analysis
         ─► NEW: detect_time_series(exec_rows, chart)         ── pure Python, no LLM
                 │  relevant?  ──no──► (descriptive only, no forecast UI)
                 │  yes
                 ▼
            forecasting.forecast(series, method, horizon)      ── pure Python, no LLM
                 ▼
            ForecastResult (yhat + confidence band + backtest accuracy)
         ─► CanvasPanel renders history + dashed forecast + CI band
                 ▲
                 └── method / horizon dropdowns recompute LOCALLY (no API, no SQL)
```

## Design principles (carry these through every stage)

- **Forecasts are deterministic and local.** They come from statistical models
  over executed SQL rows — never from the LLM. The Gemini token count for a
  forecast is **0**.
- **Relevance gating first.** Forecast UI appears **only** when
  `detect_time_series` succeeds (a temporal axis + numeric measure + enough
  points). Bar/donut/categorical results show **no** forecast controls.
- **Only valid methods are offered.** The method dropdown is filtered per series:
  seasonal models appear only with ≥ 2 full seasonal cycles; SARIMA only above a
  length threshold; otherwise the app falls back to simpler methods.
- **Recompute is free.** Changing method, horizon, or confidence level reuses the
  in‑memory series — no new Gemini call, no new SQL query.
- **Degrade gracefully.** Forecasting is wrapped so a model failure never breaks
  the descriptive result; it falls back to a simpler method with a warning.
- **Keep modules < ~250 lines**; the forecasting engine is isolated, Qt‑free, and
  unit‑tested. New dependency footprint is minimal: **`statsmodels`** only
  (`numpy`/`pandas` already ship via `pandas`).

---

# STAGE 0 — Dependencies, models, and settings

**Why.** Establish the data structures the rest of the stages fill in, and add
the single new dependency before anything imports it.

**Files**
- `requirements.txt`
- `app/data/models.py`
- `app/config/settings.py`

**Cursor prompt**
```
Reference: @app/data/models.py @app/config/settings.py @requirements.txt

1. requirements.txt: add `statsmodels>=0.14`  (numpy/pandas already present).
2. models.py — add dataclasses (slots=True), no behavior yet:
   - TimeSeriesProfile{ time_column:str, value_column:str, freq:str,
       n_points:int, seasonal_period:int|None, is_seasonal:bool,
       x:list[str], y:list[float] }
   - ForecastPoint{ x:str, yhat:float, lower:float|None, upper:float|None }
   - ForecastResult{ method:str, horizon:int, points:list[ForecastPoint],
       fitted:list[float]|None, metrics:dict (mae/rmse/mape),
       confidence:float, warnings:list[str] }
   - Extend Analysis with: forecastable:bool=False,
       ts_profile:TimeSeriesProfile|None=None,
       available_methods:list[str]=field(default_factory=list),
       forecast:ForecastResult|None=None
   - Extend ChartSpec.options usage only (no new required fields); forecast
     overlay data will be passed via options at render time.
3. settings.py — add fields with safe defaults:
   forecast_default_method:str="auto", forecast_default_horizon:int=12,
   forecast_confidence:float=0.8, forecast_enabled_by_default:bool=True.
Do NOT implement detection or models yet — types and settings only.
```

**Verify**
```
.venv\Scripts\python -c "import statsmodels, app.data.models as m; \
print(m.ForecastResult, m.TimeSeriesProfile)"
```
Dataclasses construct; settings load with new defaults; app still launches.

Commit: `git commit -am "stage 0: predictive analytics models + statsmodels dep"`

---

# STAGE 1 — Time‑series relevance detection ("only relevant data")

**Why.** This is the gate for requirement *"forecast only on relevant data."* It
decides, with **no LLM call**, whether the current result is a forecastable time
series, and produces a clean, ordered series to model.

**Files**
- `app/core/timeseries.py` *(new)*

**Cursor prompt**
```
Create app/core/timeseries.py (pure Python, no Qt, no Gemini).

def detect_time_series(rows: list[dict], chart: ChartSpec|None,
                       profile_hint: dict|None=None) -> TimeSeriesProfile | None
Logic:
 1. Pick the TIME column: prefer chart.options["x_column"]; else scan columns for
    one that parses as date/datetime OR matches year/month patterns
    (YYYY, YYYY-MM, "Jan 2024", quarters). Use pandas.to_datetime(errors="coerce");
    require >=90% parseable to qualify.
 2. Pick the VALUE column: prefer chart.options["y_column"]; else first numeric
    column that is not the time column.
 3. Build (date, value) pairs, drop NaT/None, sort ascending, de-dupe by date
    (aggregate same-period rows by sum or mean — sum by default).
 4. Infer freq from median spacing -> one of D/W/M/Q/Y; reject if spacing is too
    irregular to label.
 5. Gate: return None if < MIN_POINTS (default 6) usable points, or if no valid
    time column, or value column non-numeric. (None => "not relevant".)
 6. Seasonality: set seasonal_period from freq (M=12, Q=4, W=52, D=7); is_seasonal
    = n_points >= 2*seasonal_period.
 Return TimeSeriesProfile with x as ISO/period strings and y as floats.

def available_methods(p: TimeSeriesProfile) -> list[str]:
   always: ["naive","moving_average","linear_trend"]
   + "seasonal_naive","holt_winters" if p.is_seasonal
   + "holt" if p.n_points >= 6
   + "sarima" if p.n_points >= max(2*p.seasonal_period, 16)
   + "auto" first in the list.
Keep it dependency-light (pandas only) and deterministic.
```

**Verify**
```
.venv\Scripts\python -m pytest tests/test_timeseries.py -q
```
Add `tests/test_timeseries.py`: monthly Superstore sales → profile with freq="M",
seasonal_period=12; "top 5 states by sales" (categorical x) → `None`; a 3‑point
series → `None` (below MIN_POINTS).

Commit: `git commit -am "stage 1: time-series relevance detection"`

---

# STAGE 2 — Forecasting engine (the selectable methods)

**Why.** This satisfies *"different forecasting methods."* Each method is a pure
function over the detected series, returning predictions **and** a confidence
band, plus a backtest score used for accuracy display and the `auto` choice.

**Files**
- `app/core/forecasting.py` *(new)*

**Cursor prompt**
```
Create app/core/forecasting.py (pure Python; numpy + statsmodels; no Qt/Gemini).

A method registry maps name -> callable(series:list[float], horizon:int,
period:int|None, confidence:float) -> (yhat:list[float], lower:list[float]|None,
upper:list[float]|None, fitted:list[float]|None, warnings:list[str]).

Implement:
 - naive               : last value repeated; CI from residual std (z * sigma).
 - seasonal_naive      : repeat last full season; needs period.
 - moving_average      : trailing window mean (window=min(period or 3, n));
                         residual-based CI.
 - linear_trend        : numpy.polyfit deg=1; CI from prediction-interval formula.
 - holt                : statsmodels ETS (trend, no seasonal).
 - holt_winters        : statsmodels ExponentialSmoothing (trend + seasonal,
                         additive; multiplicative only if all y>0); needs period.
 - sarima              : statsmodels SARIMAX small default order
                         (1,1,1)(1,1,0,period); model CI via get_forecast.
 - auto                : run backtest() over the candidate methods valid for this
                         series and pick the lowest backtest MAPE; record choice
                         in warnings.

def backtest(series, method, period, holdout:int) -> dict:
   hold out the last `holdout` points (default min(6, n//4, period or 6)),
   fit on the rest, predict, return {"mae","rmse","mape"}.

def forecast(profile: TimeSeriesProfile, method:str, horizon:int,
             confidence:float) -> ForecastResult:
   - clamp horizon to FORECAST_MAX_HORIZON (e.g. 36);
   - resolve "auto"; run the method; run backtest for metrics;
   - build future x labels by extending profile.freq;
   - if series is non-negative, clamp lower band at 0;
   - wrap each model in try/except -> on failure fall back to linear_trend and
     append a warning. Never raise to the caller.
Add module-level caching: lru_cache keyed by (id-safe hash of series, method,
horizon, confidence) so repeated UI toggles are instant.
```

**Verify**
```
.venv\Scripts\python -m pytest tests/test_forecasting.py -q
```
`tests/test_forecasting.py`: on a synthetic `trend + 12‑month seasonal` series,
`holt_winters` and `sarima` beat `naive` on backtest MAPE; CI satisfies
`lower <= yhat <= upper`; horizon caps; an intentionally bad fit falls back to
`linear_trend` with a warning rather than raising.

Commit: `git commit -am "stage 2: forecasting engine (selectable methods)"`

---

# STAGE 3 — Wire forecasting into the pipeline (no extra LLM call)

**Why.** Produce a default forecast as part of each analysis **without** a second
Gemini call or a second SQL query — reuse `exec_rows` already in hand.

**Files**
- `app/core/orchestrator.py`

**Cursor prompt**
```
Reference: @app/core/orchestrator.py @app/core/timeseries.py @app/core/forecasting.py

In Orchestrator.ask(), AFTER filled_charts/kpis are built and BEFORE returning:
 1. Choose the primary temporal chart: first chart with kind in {"line"} (or any
    chart whose x_column detects as a time column).
 2. profile = detect_time_series(exec_rows, that_chart). It reuses rows already
    fetched — do NOT re-query MCP and do NOT call Gemini.
 3. If profile is None: set analysis.forecastable=False and return as today.
 4. Else: methods = available_methods(profile);
    fc = forecasting.forecast(profile,
            settings.forecast_default_method, settings.forecast_default_horizon,
            settings.forecast_confidence)   # default view
    Attach forecastable=True, ts_profile=profile, available_methods=methods,
    forecast=fc to the Analysis.
 5. Wrap steps 1–4 in try/except: any failure logs a warning and leaves
    forecastable=False (descriptive result must never break).
Token accounting is unchanged (forecast adds 0 tokens). Keep orchestrator Qt-free.
Pass Settings (or the three forecast fields) into Orchestrator via __init__.
```

**Verify**
Ask *"monthly sales trend"* → returned `Analysis.forecast` is populated and
`planner_tokens + analyst_tokens` is identical to the pre‑forecast run (prove zero
extra tokens). Ask *"sales by category"* → `forecastable is False`, no forecast.

Commit: `git commit -am "stage 3: attach default forecast in orchestrator (0 tokens)"`

---

# STAGE 4 — Render forecast overlay on the chart

**Why.** Show history and prediction together: solid historical line, dashed
forecast segment, shaded confidence band.

**Files**
- `app/ui/charts/web_chart.py`
- `app/ui/charts/__init__.py` (if `build_chart` needs the forecast passed through)

**Cursor prompt**
```
Reference: @app/ui/charts/web_chart.py @app/data/models.py

When a line ChartSpec carries forecast overlay data (pass ForecastResult via
chart.options["forecast"] when building the chart):
 1. Append the forecast x labels to the category axis.
 2. Add a dashed "Forecast" series (lineStyle.type="dashed") starting at the last
    historical point so it visually connects.
 3. Render the confidence band as two stacked area series (lower as transparent
    base, (upper-lower) as a translucent fill) OR ECharts `markArea`; label it
    "<confidence>% interval".
 4. Keep existing interactivity (tooltip, dataZoom, legend toggle). Forecast and
    band get their own legend entries so the user can hide them.
 5. No band when lower/upper are None.
Only line/time charts get this; bar/donut unchanged.
```

**Verify**
A monthly‑sales line chart shows the historical solid line, a dashed forecast
tail, and a shaded band; legend toggles the forecast and band on/off; tooltips
show predicted values on the forecast segment.

Commit: `git commit -am "stage 4: forecast overlay on line charts"`

---

# STAGE 5 — Forecast controls (user picks the method, local recompute)

**Why.** The core of *"give the user the option to use different forecasting
methods on relevant data."* Controls appear **only** on forecastable charts and
recompute **locally** — no Gemini, no SQL.

**Files**
- `app/ui/widgets/canvas_panel.py`
- `app/ui/workers/forecast_worker.py` *(new)*

**Cursor prompt**
```
Reference: @app/ui/widgets/canvas_panel.py @app/ui/workers/analysis_worker.py
           @app/core/forecasting.py @app/data/models.py

1. canvas_panel: in render(), if analysis.forecastable, add a "Forecast" control
   card directly under the primary line chart containing:
     - an Enable toggle (default from settings.forecast_enabled_by_default),
     - a Method dropdown populated ONLY from analysis.available_methods
       (label "auto" as "Auto (best fit)"),
     - a Horizon spinbox (1..FORECAST_MAX_HORIZON, default from settings),
     - a Confidence dropdown (80/90/95%),
     - a small accuracy badge showing backtest MAPE/MAE for the current method,
     - optional "Compare methods" expander listing each method's backtest MAPE.
   If NOT forecastable, render NO forecast card at all.
2. forecast_worker.py: ForecastWorker(QRunnable) recomputes
   forecasting.forecast(profile, method, horizon, confidence) off the UI thread
   and emits the new ForecastResult. It does NOT touch Gemini or MCP.
3. On any control change: start a ForecastWorker; on finish, update ONLY the
   chart overlay (re-emit the chart with options["forecast"]=new result) and the
   accuracy badge. Do not re-run the analysis or re-query SQL.
4. Disabling the toggle hides the overlay/band but keeps the descriptive chart.
```

**Verify**
On a time‑series result, switch method `Auto → SARIMA → Holt‑Winters` and bump the
horizon: the chart and accuracy badge update in well under a second with **no
network/API activity** (watch the token badge stays unchanged and logs show no
Gemini/MCP call). On a categorical result, no forecast card appears.

Commit: `git commit -am "stage 5: forecast controls with local recompute"`

---

# STAGE 6 — Settings, suggestions, and export

**Why.** Make defaults configurable, surface forecasting as a natural follow‑up,
and carry predictions into exports — all without changing the LLM's job.

**Files**
- `app/ui/dialogs/settings_dialog.py`, `app/ui/dialogs/_sections.py`
- `app/core/report_export.py`
- `app/resources/prompts/analyst.md` *(optional, minimal)*

**Cursor prompt**
```
1. settings_dialog/_sections: add a "Forecasting" section binding the four
   settings fields (default method, default horizon, confidence, enabled-by-default).
2. report_export: when analysis.forecast is present, include the forecast series,
   the confidence band, the method name, and the backtest accuracy in the exported
   HTML, with a one-line disclaimer: "Forecasts are model estimates with
   uncertainty, not guaranteed outcomes."
3. (Optional, keep tokens flat) analyst.md: you MAY allow one suggestion phrased
   like "Forecast the next N months" so the existing follow-up chips can trigger a
   time query. The analyst must still NEVER output forecast numbers — prediction
   stays in app/core/forecasting.py. If unsure, skip this and instead have
   canvas auto-show the forecast card whenever forecastable=True.
```

**Verify**
Settings persist across restart and change the default forecast; an exported HTML
report shows the dashed forecast, band, method, accuracy, and disclaimer.

Commit: `git commit -am "stage 6: forecast settings, export, suggestions"`

---

# STAGE 7 — Verification, guardrails & docs

**Why.** Lock in correctness, the relevance gate, and the efficiency guarantees.

**Cursor prompt**
```
1. Tests:
   - test_timeseries.py: categorical/short/irregular inputs return None
     (no false positives); valid monthly/weekly series detected with right freq.
   - test_forecasting.py: each method returns horizon-length output with a valid
     CI (lower<=yhat<=upper); backtest metrics finite; horizon clamped; fallback
     path covered.
   - test_orchestrator_forecast.py: forecastable result attaches a forecast and
     adds ZERO Gemini tokens vs. the same run with forecasting disabled; a
     categorical result attaches none.
2. Guardrails: forecasting is fully wrapped so it can never break the descriptive
   answer; SARIMA/ETS calls have a try/except + simpler-method fallback; horizon
   and seasonal_period are bounded.
3. Efficiency assertions: assert the forecast path performs 0 MCP queries and 0
   Gemini calls; assert UI method/horizon changes hit the lru_cache or the local
   worker only.
4. Docs: update README (new "Predictive analytics" section + statsmodels in setup)
   and tick this plan's stage checkboxes.
```

**Verify**
```
test.bat
```
All tests pass; switching methods triggers no API/DB calls; a non‑time‑series
question shows no forecast UI.

Commit: `git commit -am "stage 7: predictive analytics guardrails + tests + docs"`

---

## How this meets your three requirements

| Requirement | How the plan delivers it |
|---|---|
| **Efficient** | Forecast runs on rows already fetched — **0 extra Gemini tokens, 0 extra SQL** for the default view (Stage 3). Method/horizon changes recompute **locally** off‑thread with `lru_cache` (Stages 2, 5). One lightweight dependency (`statsmodels`); heavy methods (SARIMA) only run when explicitly selected. |
| **Different forecasting methods** | A registry of selectable models — naive, seasonal‑naive, moving average, linear trend, Holt, Holt‑Winters, SARIMA, plus **Auto (best backtest)** — chosen from a dropdown, each with an accuracy badge (Stages 2, 5). |
| **Only relevant data** | `detect_time_series` gates everything: forecast UI and computation appear **only** when there is a genuine temporal axis + numeric measure + enough points; `available_methods` further restricts choices to those valid for the series (Stages 1, 5). |

## Method reference

| Method | Offered when | Confidence band | Relative cost |
|---|---|---|---|
| Naive / Seasonal‑naive | always / seasonal series | residual σ | trivial |
| Moving average | always | residual σ | trivial |
| Linear trend (OLS) | always | prediction interval | trivial |
| Holt (double ES) | ≥ 6 points | model | low |
| Holt‑Winters (triple ES) | ≥ 2 seasonal cycles | model | low |
| SARIMA | ≥ max(2·period, 16) points | model | moderate (on‑demand) |
| Auto | always | inherited from pick | low–moderate |

## Risks & mitigations

- **False "forecastable" positives** (e.g., an ID column that looks numeric/dated)
  → strict parse threshold (≥ 90%), MIN_POINTS, and freq‑regularity check in
  Stage 1; covered by tests in Stage 7.
- **Slow/heavy models blocking the UI** → off‑thread `ForecastWorker`, horizon
  caps, SARIMA only on explicit selection, `lru_cache` on repeats (Stages 2, 5).
- **Over‑trust in predictions** → confidence bands, backtest accuracy shown next
  to the method, and an export disclaimer (Stages 4, 6). Forecasts are model
  estimates, not guaranteed outcomes.
- **Dependency weight** → `statsmodels` only; `numpy`/`pandas` already present.

## Working notes

- One stage per Composer session; attach files with `@`; run Verify before moving on.
- **Predictions ALWAYS come from `app/core/forecasting.py`, never the LLM** — the
  same invariant the descriptive pipeline already follows for measured numbers.
- The LLM is never sent the forecast and never asked to predict; its token cost
  for forecasting is zero.
- Keep new modules (`timeseries.py`, `forecasting.py`, `forecast_worker.py`) small,
  Qt‑free where possible, and unit‑tested.
