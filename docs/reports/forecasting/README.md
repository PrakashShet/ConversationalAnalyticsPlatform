# Forecasting — Technical Report Series

Five reports documenting the predictive-analytics subsystem of the AI-Powered
Conversational Analytics Platform: its architecture, the mathematics of each
method, how a result is judged forecastable, how parameters are chosen, and how
accuracy is measured.

Written to be read in order, but each stands alone.

| # | Report | Covers |
|---|---|---|
| 1 | [Forecasting Architecture](01-architecture.md) | Where forecasting sits in the pipeline, why it is isolated from the LLM, module boundaries, data flow, concurrency, persistence, failure containment |
| 2 | [Method Reference](02-method-reference.md) | The seven methods — model equations, point forecasts, confidence-band derivations, assumptions, failure modes |
| 3 | [The Relevance Gate](03-relevance-gate.md) | Detection: column selection, date parsing, frequency inference, thresholds, and how a rejection is explained |
| 4 | [Parameter Selection](04-parameter-selection.md) | Method eligibility, horizon, confidence, defaults, and what is deliberately not configurable |
| 5 | [Backtesting and Accuracy](05-backtesting.md) | Holdout construction, MAE/RMSE/MAPE, automatic selection, worked example, known gaps |

---

## Quick reference

### Methods

| Method | Trend | Season | Min $n$ | Dependency |
|---|:---:|:---:|:---:|---|
| Naive | — | — | 2 | numpy |
| Seasonal naive | — | ✓ | $2m$ | numpy |
| Moving average | — | — | 1 | numpy |
| Linear trend | ✓ | — | 2 | numpy |
| Holt | ✓ | — | 6 | statsmodels |
| Holt-Winters | ✓ | ✓ | $2m$ | statsmodels |
| SARIMA | ✓ | ✓ | $\max(2m,16)$, $m \le 24$ | statsmodels |

`auto` is a selection strategy, not a method — see Report 5 §4.

### Governing constants

| Constant | Value | Module | Report |
|---|---:|---|:---:|
| `MIN_POINTS` | 6 | `timeseries` | 3 |
| `PARSE_THRESHOLD` | 0.90 | `timeseries` | 3 |
| `_REGULARITY` | 0.60 | `timeseries` | 3 |
| `FORECAST_MAX_HORIZON` | 36 | `forecasting` | 4 |
| Cache size | 128 | `forecasting` | 1 |
| Backtest holdout | $\min(6, \lfloor n/4 \rfloor, m)$ | `forecasting` | 5 |

### Frequency bands and seasonal periods

| Freq | Day gap | $m$ |
|---|---|---:|
| `D` | 0.5 – 2.0 | 7 |
| `W` | 5.0 – 9.0 | 52 |
| `M` | 26.0 – 32.0 | 12 |
| `Q` | 84.0 – 96.0 | 4 |
| `Y` | 350.0 – 380.0 | — |

---

## Source modules

| Module | Role | Report |
|---|---|:---:|
| `app/core/timeseries.py` | Detection, frequency inference, method eligibility, rejection explanations | 3, 4 |
| `app/core/forecasting.py` | The seven methods, backtesting, auto-selection, diagnostics, comparison | 2, 4, 5 |
| `app/core/forecast_narrative.py` | Predictive-analytics prose, composed arithmetically | 1 |
| `app/data/models.py` | `TimeSeriesProfile`, `ForecastResult`, `ForecastPoint` | 1 |
| `app/ui/workers/forecast_worker.py` | Off-thread recomputation | 1, 4 |
| `app/ui/widgets/canvas_panel.py` | Controls, model-details panel, predictive card | 4, 5 |

## Verification

| Concern | Test module |
|---|---|
| Detection thresholds, rejection paths | `tests/test_timeseries.py` |
| Method correctness, band behaviour | `tests/test_forecasting.py` |
| Narrative, diagnostics, comparison, availability | `tests/test_forecast_narrative.py` |
| Pipeline attachment | `tests/test_orchestrator_forecast.py` |
| Persistence round-trip | `tests/test_history_db.py` |

---

## Word versions

`docx/` holds the same five reports as `.docx`, regenerated from this Markdown —
never edited by hand, so the two cannot drift.

    python docs/tools/build_reports_docx.py

| File | Pages |
|---|---:|
| `docx/01-architecture.docx` | 12 |
| `docx/02-method-reference.docx` | 9 |
| `docx/03-relevance-gate.docx` | 10 |
| `docx/04-parameter-selection.docx` | 7 |
| `docx/05-backtesting.docx` | 10 |
| `docx/README.docx` | 4 |

What the build does:

- **Diagrams become images.** `docs/tools/mermaid_render.py` redraws the Mermaid
  subset used here with Graphviz and matplotlib — no Node, no headless browser.
  Each figure is drawn at its *final print size* rather than scaled down
  afterwards, because a diagram squeezed from twelve inches into a seven-inch
  column has three-point text. Wide diagrams get their own landscape page.
- **Equations stay equations.** Pandoc converts the LaTeX to native Word
  equation objects (OMML), so they remain selectable and editable rather than
  becoming pictures. There are 192 of them across the series.
- **Tables get real column widths.** Pandoc 2.9 emits an empty `<w:tblGrid/>`,
  which LibreOffice renders as a single stacked column;
  `docs/tools/docx_postprocess.py` sizes the grid and every cell from the
  content.

Rendered figures are kept in `docx/figures/` so they can be reused in slides or
the coursework documents.

## Notes on these documents

**Mathematical notation** uses LaTeX between `$…$` and `$$…$$`. GitHub renders
this natively; VS Code needs a Markdown-math extension. Where a formula matters
to a reader without a renderer, it is also stated in prose.

**Diagrams** are [Mermaid](https://mermaid.js.org) fenced blocks.

**Constants cited** in these reports are taken from the source and were verified
against it at the time of writing. Where the code changes, these reports must
change with it — the quick-reference tables above are the most likely to drift.

**Criticism is deliberate.** Each report states the limitations of what it
describes: approximate confidence bands, MAPE's asymmetry, selection bias in the
reported accuracy, fixed SARIMA orders, the absence of coverage checks. A
technical report that only lists strengths is not useful for judging whether to
trust the output.

---

## Related documentation

- [`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md) — whole-system architecture; §6
  summarises the material expanded here
- [`docs/plans/PLAN_PREDICTIVE_ANALYTICS.md`](../../plans/PLAN_PREDICTIVE_ANALYTICS.md)
  — original design intent, retained as a historical record
- [`README.md`](../../../README.md) — user-facing description
