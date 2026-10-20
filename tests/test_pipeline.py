"""End-to-end checks against hand-computed expectations on the synthetic fixture."""
import json

import pandas as pd
import pytest

from src.aq import insights


def t(results, name):
    return pd.read_parquet(results[0] / "parquet" / name)


def test_summary_counts(results):
    s = results[1]
    assert s["rows_read"] == 4 * 90 * 24 * 4 + 90 * 24 + 8
    assert s["rows_rejected_by_reason"] == {"invalid_value": 2, "above_physical_bound": 1, "unit_not_convertible": 1,
                                            "unknown_parameter": 1, "null_key_field": 1}
    assert s["duplicates_removed"] == 2 and s["conflicting_duplicate_keys"] == 1
    assert (s["stations"], s["cities"], s["states"]) == (4, 3, 3)
    assert s["first_timestamp_ist"].startswith("2024-01-01 00:00") and s["spark_version"].startswith("4.")


def test_city_means(results):
    cs = t(results, "city_summary")
    g = cs[cs.parameter_name == "PM2.5"].set_index("city_name")
    assert g.loc["Delhi", "mean_daily"] == pytest.approx(102.0)     # (122 + 82) / 2
    assert g.loc["Mumbai", "mean_daily"] == pytest.approx(46.0)     # spike day included
    assert g.loc["Delhi", "pct_days_above_naaqs"] == pytest.approx(100.0)  # both Delhi stations always > 60
    assert g.loc["Chennai", "pct_days_above_naaqs"] == pytest.approx(0.0)
    mum = g.loc["Mumbai", "pct_days_above_naaqs"]
    assert mum == pytest.approx(100 / 90, abs=0.01)                        # only the spike day exceeds 60


def test_state_summary_and_coverage(results):
    ss = t(results, "state_summary")
    assert set(ss.state_name) == {"Delhi", "Maharashtra", "Tamil Nadu"}
    cov = t(results, "data_coverage").set_index("parameter_name")
    assert cov.loc["PM2.5", "n_stations"] == 4 and cov.loc["CO", "n_stations"] == 1


def test_seasons_and_months(results):
    sc = t(results, "seasonal_city")
    assert set(sc.season) == {"Winter", "Summer"}                  # Jan-Mar only
    mn = t(results, "monthly_national")
    assert sorted(mn.ym.unique()) == ["2024-01", "2024-02", "2024-03"]


def test_hourly_pattern(results):
    hp = t(results, "hourly_pattern")
    x = hp[(hp.city_name == "Delhi") & (hp.parameter_name == "NO2")]
    assert sorted(x.hour) == list(range(24)) and (x.mean_value == 30).all()


def test_hotspots(results):
    h = t(results, "hotspots")
    h = h[h.parameter_name == "PM2.5"].sort_values("rank")
    assert list(h.station_id)[:2] == ["S1", "S2"]
    assert h.iloc[0].is_hotspot and not h.iloc[1].is_hotspot
    assert h.iloc[0].latitude == pytest.approx(28.65)


def test_anomaly_detected(results):
    a = t(results, "anomaly_days")
    a = a[a.parameter_name == "PM2.5"]
    assert len(a) == 1
    r = a.iloc[0]
    assert (r.station_id, str(r.date)) == ("S3", "2024-02-15") and r.daily_mean == pytest.approx(400)


def test_aqi_rules_and_values(results):
    aqi = t(results, "aqi_station_daily")
    d0 = aqi[(aqi.station_id == "S1") & (aqi.date.astype(str) == "2024-01-01")].iloc[0]
    assert d0.aqi == 300 and d0.dominant == "PM2.5" and d0.aqi_category == "Poor"
    assert d0.n_sub >= 4                                            # PM2.5, PM10, NO2, SO2 (+CO)
    assert aqi.aqi.between(0, 500).all()
    assert results[1]["station_days_with_valid_aqi"] == len(aqi) == 4 * 90


def test_outputs_written(results):
    out = results[0]
    for n in ("city_summary", "hotspots", "anomaly_days", "aqi_city_monthly"):
        assert (out / "csv" / f"{n}.csv").exists()
    assert json.loads((out / "summary.json").read_text())["rows_clean_unique"] > 0


def test_insights_from_results(results):
    res = insights.write(results[0])
    assert (results[0] / "insights.md").exists()
    txt = " ".join(res["findings"])
    assert "Delhi" in txt and "Hotspots" in txt and "Anomalies" in txt and "AQI" in txt
    assert res["limitations"]
