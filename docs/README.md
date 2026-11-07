# Documentation index

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | **Start here.** Design principles, component map, the three-step pipeline, forecasting gate and model transparency, data-source provenance, threading, persistence, rendering, packaging, security, known issues. All diagrams. |
| [../README.md](../README.md) | Quickstart, setup, configuration, troubleshooting. |

### Finding your way around ARCHITECTURE.md

| Looking for | Section |
|---|---|
| Why the design is shaped this way | §1 Design principles |
| What talks to what | §2 Component map |
| What one question costs | §3 The three-step pipeline |
| When forecasts appear, and the model details panel | §6 Predictive analytics |
| What a saved analysis contains | §9 Persistence |
| Why a follow-up on an old analysis warns you | §10 Data-source provenance |
| Dialog contrast and theming | §11 Rendering |
| Open defects | §14 Known issues |

## Plans (`plans/`)

Historical design documents. They record intent at the time of writing and may
lag the code — `ARCHITECTURE.md` is the current description.

| File | Subject |
|---|---|
| `IMPLEMENTATION_PLAN.md` | Original end-to-end build plan. |
| `PLAN_INTERACTIVE_ANALYTICS.md` | Interactive ECharts, drill-down, export. |
| `PLAN_PREDICTIVE_ANALYTICS.md` | Forecasting design: relevance gate, method selection, backtesting, UI. |
| `diagnose_forecast.py` | Standalone script for debugging time-series detection against real rows. |

## Reports (`reports/`)

### [Forecasting technical report series](reports/forecasting/README.md)

Five reports on the predictive-analytics subsystem, with the mathematics stated
explicitly. Start at the [series index](reports/forecasting/README.md).

| # | Report | Covers |
|---|---|---|
| 1 | [Architecture](reports/forecasting/01-architecture.md) | Pipeline position, LLM isolation, module boundaries, concurrency, persistence, failure containment |
| 2 | [Method Reference](reports/forecasting/02-method-reference.md) | Seven methods — equations, band derivations, assumptions, failure modes |
| 3 | [The Relevance Gate](reports/forecasting/03-relevance-gate.md) | Detection thresholds, date parsing, frequency inference, rejection messages |
| 4 | [Parameter Selection](reports/forecasting/04-parameter-selection.md) | Eligibility, horizon, confidence, defaults, what is fixed |
| 5 | [Backtesting and Accuracy](reports/forecasting/05-backtesting.md) | Holdout, MAE/RMSE/MAPE, auto-selection, worked example, gaps |

Also available as Word documents in
[`reports/forecasting/docx/`](reports/forecasting/docx/) — generated from the
Markdown by `docs/tools/build_reports_docx.py`, with Mermaid diagrams rendered
to images and LaTeX converted to native Word equations. Regenerate rather than
edit.

### Coursework (`reports/*.docx`)

EMBA deliverables — project proposal, interim report drafts, and the
predictive-analytics write-up. Not part of the build, and kept out of the
public repository (gitignored).

## Diagram conventions

Diagrams are [Mermaid](https://mermaid.js.org) fenced blocks, which GitHub, VS
Code (with the Markdown Preview Mermaid extension), and Obsidian render
natively. Types used:

- `graph` — component and data-flow maps
- `sequenceDiagram` — the request lifecycle
- `stateDiagram-v2` — connection lifecycle
- `flowchart` — the forecasting relevance gate
- `classDiagram` — dataclass model
- `erDiagram` — SQLite history schema

When you change the code, update the diagram in the same commit. A stale
diagram is worse than no diagram.
