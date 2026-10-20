import pytest
from pyspark.sql import functions as F

from src.aq import spark_pipeline as sp


def test_unit_code(spark):
    rows = [("µg/m³",), ("μg/m3",), ("ug/m3",), ("mg/m³",), ("PPB",), ("ppm",), ("bar",), (None,)]
    out = [r.u for r in spark.createDataFrame(rows, "unit string").select(sp.unit_code(F.col("unit")).alias("u")).collect()]
    assert out == ["ug/m3", "ug/m3", "ug/m3", "mg/m3", "ppb", "ppm", "other", None]


def test_reject_reasons_and_dedup(dataset, spark):
    raw, meta = sp.read_raw(spark, str(dataset / "measurements"), [2024])
    clean, flagged = sp.clean_measurements(raw)
    rej = {r["reject_reason"]: r["n"] for r in flagged.groupBy("reject_reason").agg(F.count("*").alias("n")).collect()}
    assert rej["invalid_value"] == 2
    for k in ("above_physical_bound", "unit_not_convertible", "unknown_parameter", "null_key_field"):
        assert rej[k] == 1, k
    c = clean.agg(F.sum(F.col("n_dup") - 1).alias("d"), F.sum((F.col("dup_spread") > 0).cast("int")).alias("conf")).first()
    assert (c.d, c.conf) == (2, 1)
    assert "year" in meta["physical_schema"]  # hive partition column discovered


def test_co_converted_to_mg(dataset, spark):
    raw, _ = sp.read_raw(spark, str(dataset / "measurements"), [2024])
    clean, _ = sp.clean_measurements(raw)
    vals = [r.v for r in clean.filter("parameter_name='CO'").select(F.round("value_std", 6).alias("v")).distinct().collect()]
    assert vals == [1.5]


def test_year_filter(dataset, spark):
    raw, _ = sp.read_raw(spark, str(dataset / "measurements"), [2023])
    assert raw.count() == 0


def test_schema_error(tmp_path, spark):
    import pandas as pd
    pd.DataFrame({"station_id": ["a"], "value": [1.0]}).to_parquet(tmp_path / "x.parquet")
    with pytest.raises(sp.SchemaError, match="parameter_name"):
        sp.read_raw(spark, str(tmp_path))


def test_missing_path(spark):
    with pytest.raises(FileNotFoundError):
        sp.read_raw(spark, "/no/such/path")


def test_cli_returns_error_code_on_bad_input(tmp_path):
    assert sp.main(["--input", str(tmp_path / "nope"), "--output", str(tmp_path / "o")]) == 2
