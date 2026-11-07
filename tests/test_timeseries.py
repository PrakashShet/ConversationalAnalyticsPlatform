"""Tests for time-series relevance detection (the forecast gate)."""

from app.core.timeseries import (
    available_methods,
    detect_time_series,
    future_labels,
)


def _monthly_rows(n=36):
    return [
        {"order_month": f"{2019 + i // 12}-{i % 12 + 1:02d}", "sales": 100 + 3 * i}
        for i in range(n)
    ]


def test_detects_monthly_series():
    p = detect_time_series(_monthly_rows(36))
    assert p is not None
    assert p.freq == "M"
    assert p.n_points == 36
    assert p.seasonal_period == 12
    assert p.is_seasonal is True


def test_rejects_categorical_breakdown():
    rows = [
        {"region": r, "sales": v}
        for r, v in [
            ("West", 1), ("East", 2), ("South", 3), ("North", 4),
            ("A", 5), ("B", 6), ("C", 7),
        ]
    ]
    assert detect_time_series(rows) is None


def test_rejects_too_few_points():
    rows = [{"month": f"2022-{m:02d}", "v": m} for m in range(1, 4)]
    assert detect_time_series(rows) is None


def test_detects_yearly_integer_column():
    rows = [{"year": y, "revenue": (y - 2000) * 10} for y in range(2008, 2022)]
    p = detect_time_series(rows)
    assert p is not None
    assert p.freq == "Y"


def test_available_methods_filtered_by_series_length():
    long_p = detect_time_series(_monthly_rows(36))
    methods = available_methods(long_p)
    assert methods[0] == "auto"
    assert "holt_winters" in methods  # 3 seasonal cycles present
    assert "sarima" in methods

    short_p = detect_time_series(_monthly_rows(8))
    short_methods = available_methods(short_p)
    assert "sarima" not in short_methods  # too short for SARIMA
    assert "holt_winters" not in short_methods  # < 2 seasonal cycles


def test_future_labels_extend_period():
    p = detect_time_series(_monthly_rows(36))  # ends 2021-12
    labels = future_labels(p, 3)
    assert labels == ["2022-01", "2022-02", "2022-03"]
