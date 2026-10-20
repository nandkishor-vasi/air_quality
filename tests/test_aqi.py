import pytest
from pyspark.sql import functions as F

from src.aq.aqi import BANDS, category, overall_aqi, sub_index, sub_index_col


def test_sub_index_known_values():
    assert sub_index("PM2.5", 45) == pytest.approx(75.0)      # 50 + 15*50/30
    assert sub_index("PM2.5", 120) == pytest.approx(300.0)    # band edge
    assert sub_index("PM10", 240) == pytest.approx(100 + 140 * 100 / 150)
    assert sub_index("CO", 1.5) == pytest.approx(75.0)
    assert sub_index("PM2.5", 0) == 0


def test_sub_index_invalid_and_cap():
    assert sub_index("PM2.5", -1) is None
    assert sub_index("PM2.5", None) is None
    assert sub_index("PM2.5", float("nan")) is None
    assert sub_index("Benzene", 10) is None
    assert sub_index("PM2.5", 10_000) == 500.0


def test_bands_monotonic():
    for p, bands in BANDS.items():
        cs = [c for c, _ in bands]
        assert cs == sorted(cs) and [i for _, i in bands] == [50, 100, 200, 300, 400, 500], p


def test_categories():
    assert [category(x) for x in (0, 50, 51, 200, 201, 300, 301, 400, 401, 500)] == [
        "Good", "Good", "Satisfactory", "Moderate", "Poor", "Poor", "Very Poor", "Very Poor", "Severe", "Severe"]


def test_overall_rules():
    ok = {"PM2.5": 100.0, "NO2": 50.0, "SO2": 20.0}
    assert overall_aqi(ok) == (100.0, "PM2.5")
    assert overall_aqi({"PM2.5": 100.0, "NO2": 50.0}) == (None, None)              # <3 pollutants
    assert overall_aqi({"NO2": 50.0, "SO2": 20.0, "CO": 30.0}) == (None, None)     # no PM
    assert overall_aqi({"PM10": 80.0, "NO2": None, "SO2": 20.0, "CO": 30.0}) == (80.0, "PM10")


def test_spark_matches_python(spark):
    vals = [(p, c) for p in BANDS for c in (0.0, 1.0, 29.0, 45.0, 120.0, 250.0, 700.0, 5000.0)]
    df = spark.createDataFrame(vals, ["p", "c"]).withColumn("si", sub_index_col(F.col("c"), F.col("p")))
    for r in df.collect():
        assert r.si == pytest.approx(sub_index(r.p, r.c)), (r.p, r.c)
