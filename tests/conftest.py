"""Test fixtures.

IMPORTANT: the data generated here is a small, deterministic, SYNTHETIC test fixture
used only to verify code logic against hand-computed expectations. It is never
used for reported findings.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.aq import spark_pipeline as sp  # noqa: E402

STATIONS = [("S1", "Anand Vihar", "Delhi", "Delhi", 120, 28.65, 77.31),
            ("S2", "RK Puram", "Delhi", "Delhi", 80, 28.56, 77.17),
            ("S3", "Bandra", "Maharashtra", "Mumbai", 40, 19.06, 72.84),
            ("S4", "Alandur", "Tamil Nadu", "Chennai", 20, 13.00, 80.20)]
DAYS = 90
START = pd.Timestamp("2024-01-01")
SPIKE_DAY = 45


def _rows():
    rows = []
    for sid, name, state, city, base, *_ in STATIONS:
        for d in range(DAYS):
            for h in range(24):
                ts = START + pd.Timedelta(days=d, hours=h)
                pm25 = base + d % 5
                if sid == "S3" and d == SPIKE_DAY:
                    pm25 = 400
                for par, val in (("PM2.5", pm25), ("PM10", 2 * pm25), ("NO2", 30), ("SO2", 10)):
                    rows.append((sid, name, state, city, par, "µg/m³", ts, float(val), "cpcb_caaqm"))
        if sid == "S1":  # CO supplied in ug/m3 -> must become 1.5 mg/m3
            for d in range(DAYS):
                for h in range(24):
                    rows.append((sid, name, state, city, "CO", "µg/m³", START + pd.Timedelta(days=d, hours=h), 1500.0, "cpcb_caaqm"))
    # injected bad / duplicate rows
    t = pd.Timestamp("2024-04-05 10:00")
    bad = [("S1", "Anand Vihar", "Delhi", "Delhi", "PM2.5", "µg/m³", t, -5.0, "x"),          # invalid_value
           ("S1", "Anand Vihar", "Delhi", "Delhi", "PM2.5", "µg/m³", t, None, "x"),          # invalid_value
           ("S1", "Anand Vihar", "Delhi", "Delhi", "PM2.5", "µg/m³", t, 5000.0, "x"),        # above_physical_bound
           ("S1", "Anand Vihar", "Delhi", "Delhi", "PM2.5", "ppb", t, 40.0, "x"),            # unit_not_convertible
           ("S1", "Anand Vihar", "Delhi", "Delhi", "FOO", "µg/m³", t, 10.0, "x"),            # unknown_parameter
           (None, "?", "Delhi", "Delhi", "PM2.5", "µg/m³", t, 10.0, "x"),                    # null_key_field
           ("S1", "Anand Vihar", "Delhi", "Delhi", "PM2.5", "µg/m³", START, 120.0, "cpcb_caaqm"),                       # exact dup
           ("S4", "Alandur", "Tamil Nadu", "Chennai", "PM2.5", "µg/m³", START + pd.Timedelta(hours=1), 30.0, "cpcb_caaqm")]  # conflicting dup
    return rows + bad


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("raw")
    cols = ["station_id", "station_name", "city_name_", "city_name", "parameter_name", "unit", "collected_at", "value", "source"]
    df = pd.DataFrame(_rows(), columns=cols).rename(columns={"city_name_": "state_name"})
    df["year"], df["month"] = df.collected_at.dt.year, df.collected_at.dt.month
    meas = root / "measurements"
    for (y, m), g in df.groupby(["year", "month"]):
        d = meas / f"year={y}" / f"month={m:02d}"
        d.mkdir(parents=True)
        g.drop(columns=["year", "month"]).to_parquet(d / "data.parquet", index=False, coerce_timestamps="us",
                                                      allow_truncated_timestamps=True)
    st = pd.DataFrame([(s[0], s[1], s[2], s[3], s[5], s[6]) for s in STATIONS],
                      columns=["station_id", "station_name", "state_name", "city_name", "latitude", "longitude"])
    st.to_parquet(root / "stations.parquet", index=False)
    return root


@pytest.fixture(scope="session")
def spark():
    s = sp.build_spark("local[2]", 4, "1g")
    yield s
    s.stop()


@pytest.fixture(scope="session")
def results(dataset, tmp_path_factory, spark):
    out = tmp_path_factory.mktemp("results")
    summary = sp.run(str(dataset / "measurements"), str(out), years=[2024],
                     stations_path=str(dataset / "stations.parquet"), shuffle_partitions=4,
                     driver_memory="1g", min_station_days=60, stop_session=False)
    return out, summary
