"""PySpark batch pipeline: ingest -> validate -> clean -> aggregate -> Parquet/CSV.

Run:  python -m src.aq.spark_pipeline --input data/raw --output results --years 2024
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window, functions as F
from pyspark.sql.types import DoubleType, StringType, TimestampType

from . import config as C
from .aqi import EIGHT_HOUR, PM_PARAMS, category_col, sub_index_col

log = logging.getLogger("aq.pipeline")


class SchemaError(ValueError):
    """Raised when the input lacks required columns."""


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #
def build_spark(master: str = "local[2]", shuffle_partitions: int = 8,
                driver_memory: str = "2g") -> SparkSession:
    spark = (SparkSession.builder.master(master).appName("IndiaAirQualityBDA")
             .config("spark.sql.session.timeZone", "Asia/Kolkata")  # data is naive IST
             .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
             .config("spark.driver.memory", driver_memory)
             .config("spark.sql.adaptive.enabled", "true")
             .config("spark.ui.showConsoleProgress", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    return spark


# --------------------------------------------------------------------------- #
# Ingestion + schema validation
# --------------------------------------------------------------------------- #
def read_raw(spark: SparkSession, path: str, years: list[int] | None = None) -> tuple[DataFrame, dict]:
    """Read monthly Parquet (hive layout year=/month=), validate and cast to the canonical schema."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input path not found: {p}. See README 'Get the data'.")
    raw = spark.read.option("mergeSchema", "false").parquet(str(p))
    found = {f.name: f.dataType.simpleString() for f in raw.schema.fields}
    missing = [c for c in C.REQUIRED_COLUMNS if c not in found]
    if missing:
        raise SchemaError(f"Missing required columns {missing}; found {sorted(found)}")
    if years and "year" in found:
        raw = raw.filter(F.col("year").isin([int(y) for y in years]))   # partition pruning
    cols = []
    for name, typ in {**C.REQUIRED_COLUMNS, **C.OPTIONAL_COLUMNS}.items():
        if name in found:
            col = F.col(name)
            if typ == "string":
                col = F.trim(col.cast(StringType()))
            elif typ == "double":
                col = col.cast(DoubleType())
            else:
                col = col.cast(TimestampType())
        else:
            col = F.lit(None).cast(StringType())
        cols.append(col.alias(name))
    df = raw.select(*cols)
    if years:
        df = df.filter(F.year("collected_at").isin([int(y) for y in years]) | F.col("collected_at").isNull())
    return df, {"physical_schema": found}


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def unit_code(col):
    u = F.translate(F.lower(F.trim(col)), "μ³ ", "µ3")  # Greek mu->micro, ³->3, drop spaces
    return (F.when(u.isNull(), F.lit(None))
            .when(u.isin("µg/m3", "ug/m3", "mcg/m3"), "ug/m3")
            .when(u == "mg/m3", "mg/m3").when(u == "ppb", "ppb").when(u == "ppm", "ppm")
            .otherwise("other"))


def flag_and_standardise(df: DataFrame) -> DataFrame:
    """Add unit_code, value_std (canonical units) and reject_reason (null = keep)."""
    is_co = F.col("parameter_name").isin(*C.MG_PARAMS)
    bound = F.lit(None).cast("double")
    for p, b in C.PHYSICAL_MAX.items():
        bound = F.when(F.col("parameter_name") == p, F.lit(float(b))).otherwise(bound)
    d = df.withColumn("unit_code", unit_code(F.col("unit")))
    d = d.withColumn(
        "value_std",
        F.when(F.col("unit_code") == "ug/m3", F.when(is_co, F.col("value") / 1000).otherwise(F.col("value")))
         .when(F.col("unit_code") == "mg/m3", F.when(is_co, F.col("value")).otherwise(F.col("value") * 1000)))
    d = d.withColumn("reject_reason",
        F.when(F.col("station_id").isNull() | (F.col("station_id") == "") |
               F.col("parameter_name").isNull() | F.col("collected_at").isNull(), "null_key_field")
         .when(~F.col("parameter_name").isin(*C.PARAMS), "unknown_parameter")
         .when(F.col("value").isNull() | F.isnan("value") | (F.col("value") < 0), "invalid_value")
         .when(F.col("value_std").isNull(), "unit_not_convertible")
         .when(F.col("value_std") > bound, "above_physical_bound"))
    return d


def deduplicate(good: DataFrame) -> DataFrame:
    """One row per (station, parameter, timestamp); conflicting duplicates are averaged."""
    return (good.groupBy("station_id", "parameter_name", "collected_at")
            .agg(F.count("*").alias("n_dup"),
                 F.avg("value_std").alias("value_std"),
                 (F.max("value_std") - F.min("value_std")).alias("dup_spread"),
                 F.max("station_name").alias("station_name"),
                 F.coalesce(F.max("state_name"), F.lit("Unknown")).alias("state_name"),
                 F.coalesce(F.max("city_name"), F.lit("Unknown")).alias("city_name"),
                 F.max("source").alias("source")))


def derive_time(df: DataFrame) -> DataFrame:
    season = F.lit(None).cast("string")
    for m, s in C.SEASONS.items():
        season = F.when(F.month("ts") == m, s).otherwise(season)
    df = df.withColumnRenamed("collected_at", "ts")
    return (df.withColumn("date", F.to_date("ts")).withColumn("year", F.year("ts"))
              .withColumn("month", F.month("ts")).withColumn("hour", F.hour("ts"))
              .withColumn("ym", F.date_format("ts", "yyyy-MM")).withColumn("season", season))


def clean_measurements(raw: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Returns (clean_hourly, flagged_all). flagged_all carries reject_reason for stats."""
    flagged = flag_and_standardise(raw)
    good = flagged.filter(F.col("reject_reason").isNull())
    return derive_time(deduplicate(good)), flagged


# --------------------------------------------------------------------------- #
# Aggregations
# --------------------------------------------------------------------------- #
def daily_means(clean: DataFrame, min_hours: int = C.MIN_HOURS_PER_DAY) -> DataFrame:
    d = (clean.groupBy("station_id", "parameter_name", "date")
         .agg(F.avg("value_std").alias("daily_mean"), F.max("value_std").alias("daily_max"),
              F.count("*").alias("n_hours"),
              F.max("station_name").alias("station_name"), F.max("state_name").alias("state_name"),
              F.max("city_name").alias("city_name"), F.max("season").alias("season"),
              F.max("ym").alias("ym")))
    return d.filter(F.col("n_hours") >= min_hours)


def _threshold_col():
    t = F.lit(None).cast("double")
    for p, v in C.NAAQS_24H.items():
        t = F.when(F.col("parameter_name") == p, F.lit(float(v))).otherwise(t)
    return t


def summarise(daily: DataFrame, keys: list[str]) -> DataFrame:
    d = daily.withColumn("naaqs", _threshold_col())
    return (d.groupBy(*keys, "parameter_name")
            .agg(F.round(F.avg("daily_mean"), 2).alias("mean_daily"),
                 F.round(F.percentile_approx("daily_mean", 0.5), 2).alias("median_daily"),
                 F.round(F.percentile_approx("daily_mean", 0.95), 2).alias("p95_daily"),
                 F.round(F.max("daily_mean"), 2).alias("max_daily"),
                 F.countDistinct("station_id").alias("n_stations"),
                 F.count("*").alias("n_station_days"),
                 F.sum("n_hours").alias("n_hourly_readings"),
                 F.round(100 * F.avg(F.when(F.col("naaqs").isNotNull(),
                                            (F.col("daily_mean") > F.col("naaqs")).cast("int"))), 2)
                  .alias("pct_days_above_naaqs")))


def hotspots(daily: DataFrame, stations: DataFrame | None, min_days: int, pct: float) -> DataFrame:
    d = daily.withColumn("naaqs", _threshold_col())
    st = (d.groupBy("station_id", "parameter_name")
          .agg(F.max("station_name").alias("station_name"), F.max("city_name").alias("city_name"),
               F.max("state_name").alias("state_name"),
               F.round(F.avg("daily_mean"), 2).alias("mean_daily"),
               F.round(F.percentile_approx("daily_mean", 0.95), 2).alias("p95_daily"),
               F.count("*").alias("n_days"),
               F.round(100 * F.avg(F.when(F.col("naaqs").isNotNull(),
                                          (F.col("daily_mean") > F.col("naaqs")).cast("int"))), 2)
                .alias("pct_days_above_naaqs"))
          .filter(F.col("n_days") >= min_days))
    w = Window.partitionBy("parameter_name").orderBy(F.col("mean_daily").desc(), "station_id")
    st = (st.withColumn("rank", F.row_number().over(w))
            .withColumn("pct_rank", F.round(F.percent_rank().over(
                Window.partitionBy("parameter_name").orderBy("mean_daily")), 4))
            .withColumn("is_hotspot", F.col("pct_rank") >= pct))
    if stations is not None:
        keep = [c for c in ("station_id", "latitude", "longitude") if c in stations.columns]
        st = st.join(stations.select(*keep).dropDuplicates(["station_id"]), "station_id", "left")
    return st


def anomalies(daily: DataFrame, z_cut: float, min_days: int) -> tuple[DataFrame, DataFrame]:
    """Modified z-score (median/MAD) per station-parameter; flags positive spikes."""
    key = ["station_id", "parameter_name"]
    med = (daily.groupBy(*key).agg(F.percentile_approx("daily_mean", 0.5).alias("med"),
                                   F.count("*").alias("n")).filter(F.col("n") >= min_days))
    j = daily.join(med, key).withColumn("absdev", F.abs(F.col("daily_mean") - F.col("med")))
    mad = j.groupBy(*key).agg(F.percentile_approx("absdev", 0.5).alias("mad"))
    z = (j.join(mad, key).filter(F.col("mad") > 0)
          .withColumn("robust_z", F.round(0.6745 * (F.col("daily_mean") - F.col("med")) / F.col("mad"), 2))
          .withColumn("is_anomaly", F.col("robust_z") > z_cut))
    flagged = (z.filter("is_anomaly")
                .select("station_id", "station_name", "city_name", "state_name", "parameter_name", "date",
                        F.round("daily_mean", 2).alias("daily_mean"), F.round("med", 2).alias("station_median"),
                        "robust_z"))
    summary = (z.groupBy("state_name", "city_name", "parameter_name")
                .agg(F.count("*").alias("n_station_days"), F.sum(F.col("is_anomaly").cast("int")).alias("n_anomalies"))
                .withColumn("pct_anomalous", F.round(100 * F.col("n_anomalies") / F.col("n_station_days"), 3)))
    return flagged, summary


def station_aqi_daily(clean: DataFrame, daily: DataFrame) -> DataFrame:
    """Daily CPCB AQI per station; rows exist only where the CPCB validity rules are met."""
    d24 = (daily.filter(F.col("parameter_name").isin("PM2.5", "PM10", "NO2", "SO2", "NH3"))
                .select("station_id", "parameter_name", "date", "daily_mean", "station_name", "city_name", "state_name",
                        "ym", "season").withColumnRenamed("daily_mean", "conc"))
    h = clean.filter(F.col("parameter_name").isin(*EIGHT_HOUR))
    w = (Window.partitionBy("station_id", "parameter_name").orderBy(F.col("ts").cast("long"))
         .rangeBetween(-7 * 3600, 0))
    r8 = (h.withColumn("avg8", F.avg("value_std").over(w)).withColumn("cnt8", F.count("value_std").over(w))
           .filter(F.col("cnt8") >= C.MIN_HOURS_8H_WINDOW)
           .groupBy("station_id", "parameter_name", "date").agg(F.max("avg8").alias("conc")))
    dv = daily.filter(F.col("parameter_name").isin(*EIGHT_HOUR)).select(
        "station_id", "parameter_name", "date", "station_name", "city_name", "state_name", "ym", "season")
    d8 = dv.join(r8, ["station_id", "parameter_name", "date"])
    subs = (d24.unionByName(d8.select(*d24.columns))
              .withColumn("sub_index", sub_index_col(F.col("conc"), F.col("parameter_name")))
              .filter(F.col("sub_index").isNotNull()))
    pm = F.max(F.col("parameter_name").isin(*PM_PARAMS).cast("int"))
    agg = (subs.groupBy("station_id", "date")
           .agg(F.max("sub_index").alias("aqi_raw"), F.count("*").alias("n_sub"), pm.alias("has_pm"),
                F.max_by("parameter_name", "sub_index").alias("dominant"),
                F.max("station_name").alias("station_name"), F.max("city_name").alias("city_name"),
                F.max("state_name").alias("state_name"), F.max("ym").alias("ym"), F.max("season").alias("season")))
    out = agg.filter((F.col("n_sub") >= 3) & (F.col("has_pm") == 1))
    out = out.withColumn("aqi", F.round("aqi_raw", 0)).drop("aqi_raw", "has_pm")
    return out.withColumn("aqi_category", category_col(F.col("aqi")))


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
def save(df: DataFrame, out: Path, name: str, csv: bool = True) -> int:
    path = out / "parquet" / name
    df.write.mode("overwrite").parquet(str(path))
    pdf = None
    if csv:
        pdf = spark_read_parquet_to_pandas(df.sparkSession, path)
        (out / "csv").mkdir(parents=True, exist_ok=True)
        pdf.to_csv(out / "csv" / f"{name}.csv", index=False)
    n = len(pdf) if pdf is not None else df.sparkSession.read.parquet(str(path)).count()
    log.info("saved %-22s rows=%d", name, n)
    return n


def spark_read_parquet_to_pandas(spark: SparkSession, path: Path):
    return spark.read.parquet(str(path)).toPandas()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(input_path: str, output: str, years: list[int] | None = None, stations_path: str | None = None,
        master: str = "local[2]", shuffle_partitions: int = 8, driver_memory: str = "2g",
        min_station_days: int = C.MIN_STATION_DAYS, stop_session: bool = True) -> dict:
    t0 = time.time()
    out = Path(output)
    (out / "parquet").mkdir(parents=True, exist_ok=True)
    spark = build_spark(master, shuffle_partitions, driver_memory)
    log.info("Spark %s master=%s tz=%s", spark.version, master, spark.conf.get("spark.sql.session.timeZone"))
    raw, meta = read_raw(spark, input_path, years)

    clean, flagged = clean_measurements(raw)
    flagged = flagged.cache()
    rej = {r["reject_reason"] or "kept": r["n"] for r in flagged.groupBy("reject_reason").agg(F.count("*").alias("n")).collect()}
    unit_mix = [r.asDict() for r in flagged.groupBy("parameter_name", "unit_code").agg(F.count("*").alias("n"))
                .orderBy("parameter_name", "unit_code").collect()]
    n_in = sum(rej.values())
    log.info("rows read=%d; rejection breakdown=%s", n_in, rej)
    if rej.get("kept", 0) == 0:
        raise ValueError("No valid rows after cleaning; check input path/years/units.")

    clean_path = out / "parquet" / "clean_hourly"
    clean.write.mode("overwrite").partitionBy("year", "month").parquet(str(clean_path))
    flagged.unpersist()
    clean = spark.read.parquet(str(clean_path))        # re-read: cuts lineage, prunes columns
    n_clean = clean.count()
    dup = clean.agg(F.sum(F.col("n_dup") - 1).alias("dups"), F.sum((F.col("dup_spread") > 0).cast("int")).alias("conf"),
                    F.countDistinct("station_id").alias("stations"), F.countDistinct("city_name").alias("cities"),
                    F.countDistinct("state_name").alias("states"), F.date_format(F.min("ts"), "yyyy-MM-dd HH:mm:ss").alias("t0"),   # formatted in Spark (IST) so the
                    F.date_format(F.max("ts"), "yyyy-MM-dd HH:mm:ss").alias("t1")).first()  # JVM/Python tz never shifts it

    daily = daily_means(clean).cache()
    n_daily = daily.count()
    tbl = {}
    tbl["city_summary"] = summarise(daily, ["state_name", "city_name"])
    tbl["state_summary"] = summarise(daily, ["state_name"])
    tbl["monthly_city"] = (daily.groupBy("state_name", "city_name", "parameter_name", "ym")
                           .agg(F.round(F.avg("daily_mean"), 2).alias("mean_daily"), F.count("*").alias("n_station_days")))
    tbl["monthly_national"] = (daily.groupBy("parameter_name", "ym")
                               .agg(F.round(F.avg("daily_mean"), 2).alias("mean_daily"),
                                    F.countDistinct("station_id").alias("n_stations")))
    tbl["seasonal_city"] = (daily.groupBy("state_name", "city_name", "parameter_name", "season")
                            .agg(F.round(F.avg("daily_mean"), 2).alias("mean_daily"), F.count("*").alias("n_station_days")))
    tbl["hourly_pattern"] = (clean.groupBy("state_name", "city_name", "parameter_name", "hour")
                             .agg(F.round(F.avg("value_std"), 2).alias("mean_value"), F.count("*").alias("n_readings")))
    stations = None
    if stations_path and Path(stations_path).exists():
        stations = spark.read.parquet(stations_path)
    tbl["hotspots"] = hotspots(daily, stations, min_station_days, C.HOTSPOT_PERCENTILE)
    flagged_an, an_sum = anomalies(daily, C.ANOMALY_Z, C.ANOMALY_MIN_DAYS)
    tbl["anomaly_days"] = flagged_an.orderBy(F.col("robust_z").desc()).limit(2000)
    tbl["anomaly_summary"] = an_sum
    aqi = station_aqi_daily(clean, daily).cache()
    tbl["aqi_station_daily"] = aqi
    tbl["aqi_city_monthly"] = (aqi.groupBy("state_name", "city_name", "ym")
                               .agg(F.round(F.avg("aqi"), 1).alias("mean_aqi"), F.count("*").alias("n_station_days")))
    tbl["aqi_category_city"] = aqi.groupBy("state_name", "city_name", "aqi_category").agg(F.count("*").alias("n_station_days"))
    tbl["aqi_dominant_city"] = aqi.groupBy("state_name", "city_name", "dominant").agg(F.count("*").alias("n_station_days"))
    tbl["data_coverage"] = (daily.groupBy("parameter_name")
                            .agg(F.countDistinct("station_id").alias("n_stations"), F.count("*").alias("n_station_days"),
                                 F.min("date").alias("first_date"), F.max("date").alias("last_date")))

    rows = {}
    for name, df in tbl.items():
        rows[name] = save(df, out, name, csv=name != "aqi_station_daily")
    n_aqi = rows["aqi_station_daily"]

    summary = {
        "run_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "spark_version": spark.version, "spark_master": master, "shuffle_partitions": shuffle_partitions,
        "driver_memory": driver_memory, "timezone": "Asia/Kolkata (source timestamps are naive IST)",
        "input_path": str(input_path), "years_filter": years, "physical_schema": meta["physical_schema"],
        "rows_read": n_in, "rows_rejected_by_reason": {k: v for k, v in rej.items() if k != "kept"},
        "rows_kept_before_dedup": rej.get("kept", 0), "rows_clean_unique": n_clean,
        "duplicates_removed": int(dup["dups"] or 0), "conflicting_duplicate_keys": int(dup["conf"] or 0),
        "stations": int(dup["stations"]), "cities": int(dup["cities"]), "states": int(dup["states"]),
        "first_timestamp_ist": str(dup["t0"]), "last_timestamp_ist": str(dup["t1"]),
        "station_days_valid": n_daily, "station_days_with_valid_aqi": n_aqi,
        "min_hours_per_day": C.MIN_HOURS_PER_DAY, "min_station_days": min_station_days,
        "anomaly_z_cut": C.ANOMALY_Z, "hotspot_percentile": C.HOTSPOT_PERCENTILE,
        "unit_mix": unit_mix, "table_rows": rows, "runtime_seconds": round(time.time() - t0, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    if stop_session:
        spark.stop()
    log.info("pipeline finished in %.1fs", summary["runtime_seconds"])
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default=str(C.DEFAULT_RAW / "measurements"))
    ap.add_argument("--stations", default=str(C.DEFAULT_RAW / "stations.parquet"))
    ap.add_argument("--output", default=str(C.DEFAULT_RESULTS))
    ap.add_argument("--years", type=int, nargs="*", default=None)
    ap.add_argument("--master", default="local[2]")
    ap.add_argument("--shuffle-partitions", type=int, default=8)
    ap.add_argument("--driver-memory", default="2g")
    ap.add_argument("--min-station-days", type=int, default=C.MIN_STATION_DAYS)
    a = ap.parse_args(argv)
    Path(a.output).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(Path(a.output) / "pipeline.log", mode="w")])
    try:
        run(a.input, a.output, a.years, a.stations, a.master, a.shuffle_partitions, a.driver_memory, a.min_station_days)
    except (FileNotFoundError, SchemaError, ValueError) as e:
        log.error("%s", e)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
