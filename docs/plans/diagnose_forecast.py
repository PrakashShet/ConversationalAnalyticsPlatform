"""Forecast feature self-check.

Run from the project root with your venv's Python:

    .venv\\Scripts\\python diagnose_forecast.py

It imports the SAME modules the app uses and reports whether the predictive
analytics code is present and working in this environment. Paste the output back.
"""

from __future__ import annotations

import sys

OK, BAD = "[ OK ]", "[FAIL]"


def line():
    print("-" * 64)


print("=" * 64)
print("PREDICTIVE ANALYTICS SELF-CHECK")
print("=" * 64)
print("Python      :", sys.version.split()[0])
print("Executable  :", sys.executable)
print("Frozen exe? :", getattr(sys, "frozen", False), "(True means you are running the OLD dist build)")

try:
    import statsmodels
    print("statsmodels :", statsmodels.__version__)
except Exception:
    print("statsmodels : NOT INSTALLED (numpy methods still work)")

line()
print("CODE VERSION MARKERS (all must be True / amber):")
problems = 0

try:
    import app.core.orchestrator as orch
    has = hasattr(orch.Orchestrator, "_attach_forecast")
    print(OK if has else BAD, "orchestrator._attach_forecast :", has)
    problems += not has
except Exception as e:
    print(BAD, "import orchestrator:", e); problems += 1

try:
    import app.core.forecasting as F
    print(OK, "forecasting.forecast_bundle  :", hasattr(F, "forecast_bundle"))
    print(OK, "forecasting.forecast_overlay :", hasattr(F, "forecast_overlay"))
except Exception as e:
    print(BAD, "import forecasting:", e); problems += 1

try:
    import app.core.timeseries as TS
    print(OK, "timeseries.detect_time_series:", hasattr(TS, "detect_time_series"))
except Exception as e:
    print(BAD, "import timeseries:", e); problems += 1

try:
    import app.ui.charts.web_chart as WC
    color = getattr(WC, "_FORECAST_COLOR", "MISSING")
    good = color == "#f59e0b"
    print(OK if good else BAD, "web_chart._FORECAST_COLOR     :", color)
    problems += not good
except Exception as e:
    print(BAD, "import web_chart:", e); problems += 1

try:
    import app.ui.widgets.canvas_panel as CP
    has = hasattr(CP.CanvasPanel, "_add_forecast_controls")
    print(OK if has else BAD, "canvas._add_forecast_controls :", has)
    problems += not has
except Exception as e:
    print(BAD, "import canvas_panel:", e); problems += 1

try:
    from app.config.settings import Settings
    s = Settings.load()
    print(OK, "settings.forecast_enabled    :", getattr(s, "forecast_enabled_by_default", "MISSING"))
    print(OK, "settings.forecast_method     :", getattr(s, "forecast_default_method", "MISSING"))
except Exception as e:
    print(BAD, "load settings:", e); problems += 1

line()
print("FUNCTIONAL TEST (sample weekly series):")
try:
    import datetime
    from app.data.models import ChartSpec
    d, rows = datetime.date(2010, 2, 5), []
    for i in range(143):
        rows.append({"date": d.isoformat(), "total_weekly_sales": 35_000_000 + 1e5 * i})
        d += datetime.timedelta(days=7)
    chart = ChartSpec(kind="line", title="t",
                      options={"x_column": "date", "y_column": "total_weekly_sales"})
    prof = TS.detect_time_series(rows, chart)
    print("  detect_time_series ->",
          None if prof is None else f"freq={prof.freq} n={prof.n_points} seasonal={prof.is_seasonal}")
    bundle = F.forecast_bundle(rows, chart, "auto", 12, 0.8)
    if bundle:
        _, methods, res = bundle
        print("  forecast_bundle    -> forecastable=True, methods:", methods)
        print("                        chosen:", res.method, "| horizon:", res.horizon)
    else:
        print("  forecast_bundle    -> None  (NOT forecastable)")
except Exception as e:
    import traceback
    traceback.print_exc()
    problems += 1

line()
print("VERDICT:")
if problems == 0 and bundle:
    print("  Forecast code is PRESENT and WORKING in this environment.")
    print("  If the app UI still shows no forecast, you are launching a DIFFERENT")
    print("  build than this Python sees -- most likely the frozen .exe in dist\\.")
    print("  Launch with:  run.bat   (NOT the exe in dist\\ConvAnalytics).")
else:
    print(f"  {problems} problem(s) above. The deployed code is missing pieces -")
    print("  paste this whole output back and I'll fix it.")
print("=" * 64)
