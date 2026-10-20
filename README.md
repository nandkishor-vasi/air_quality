# Analysis of Air Pollution Patterns and Pollution Hotspots Across India (PySpark + Streamlit)

Apache Spark is the analytics engine: schema validation, cleaning, deduplication, 8-hour rolling windows,
rankings, percentiles, hotspot/anomaly detection and CPCB AQI all run as Spark DataFrame jobs.
Storage is Parquet. Apache Cassandra is **not** implemented (optional; see report §6).

## Status (read this first)

| Item | State |
|---|---|
| Spark pipeline, dashboard, insights, report builder | Implemented |
| Automated tests | 29 tests pass on a small **synthetic test fixture** (`tests/conftest.py`), verifying code logic against hand-computed values |
| Run on the **real** dataset | **Not done in the build environment** (its network policy blocked `airquality.xkdr.org`). You run the commands below on your laptop; every number in the report is then generated from your real run |
| Dashboard screenshots | Not captured (none exist without real results). Save your own to `docs/screenshots/` (names in `report/build_report.py`, `SHOTS`) and rebuild the report |
| Downloader | Written from the published API docs; only its file-selection logic is unit-tested (not run against the live API) |
| Windows | Untested. Spark on native Windows needs Hadoop `winutils`; WSL2/Linux/macOS recommended |

## Dataset

India Air Quality Database, XKDR Forum — <https://airquality.xkdr.org/> (hourly CPCB CAAQM + US Embassy readings,
Jan 2009 – Mar 2026, 558 stations, 15 pollutants; one Parquet per month). Licence **CC BY 4.0**: credit
"India Air Quality Database, XKDR Forum" and the sources (CPCB CAAQM; US Department of State via AirNow).
Data are as received from the networks (preliminary, no gap-filling/calibration).
Schema: `station_id, station_name, state_name, city_name, parameter_name, unit, collected_at (naive IST), value, source` (+ hive `year`, `month`).

**Laptop strategy:** download one year (tens of MB). The public demo key built into the downloader reads **2024 only**.
For other years get a free key at <https://airquality.xkdr.org/signup> and `export AQI_API_KEY=aqi_...`.

## Setup (Python 3.10–3.13, Java 17+)

```bash
cd airquality_bda
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                         # tested versions: requirements.lock.txt
java -version                                           # must be 17 or newer
```

## Run

```bash
python scripts/download_data.py --years 2024                    # add --months 10 11 12 to limit; --dry-run to preview
python -m src.aq.spark_pipeline --years 2024 --master local[4] --driver-memory 4g
python -m src.aq.insights results                               # writes results/insights.md
streamlit run app.py                                            # dashboard at http://localhost:8501
pytest --junitxml=docs/pytest_report.xml                        # automated tests
python report/build_report.py --results results                 # report/output/*.docx and *.pdf
```

Spark settings (flags): `--master local[N]` (default `local[2]`), `--shuffle-partitions 8`, `--driver-memory 2g`,
`--min-station-days 60`. If you run out of memory, download fewer months or lower `--shuffle-partitions`.
Edit student/college details in `report/report_config.json` (set `logo_path` for the logo).
`python report/build_report.py --template` builds a skeleton with result sections marked pending (a copy is in `report/output/`).

## Outputs (`results/`)

`parquet/<table>/` and `csv/<table>.csv` for: `city_summary, state_summary, monthly_city, monthly_national, seasonal_city,
hourly_pattern, hotspots, anomaly_days, anomaly_summary, aqi_city_monthly, aqi_category_city, aqi_dominant_city, data_coverage`
(+ `aqi_station_daily`, `clean_hourly` in Parquet only), `summary.json` (run metadata, data-quality counts), `pipeline.log`, `insights.md/json`.

## Method notes and assumptions

* Cleaning: reject null keys, unknown parameters, null/NaN/negative values, ppb/ppm rows (not converted), values above plausibility bounds
  (`src/aq/config.py`, **my assumptions**); CO normalised to mg/m³, others µg/m³; dedupe on (station, parameter, timestamp).
* Valid day ≥ 16 hourly readings. City/state figures = mean of valid station-day means (not population-weighted).
* NAAQS 24-h limits (PM2.5 60, PM10 100, NO2 80, SO2 80, NH3 400 µg/m³) and CPCB AQI bands were checked against ies.gov.in summaries; confirm with official CPCB notifications before formal use.
* AQI: the database has no AQI column, so CPCB NAQI is computed (≥16 h/day, ≥3 pollutants incl. PM2.5/PM10, 8-hour means for CO and ozone). CPCB gives no upper bound for the top band; it is extended by the previous band's width and capped at 500 (assumption).
* Hotspot = top 10% of stations (≥ 60 valid days) by mean daily value. Anomaly = modified z-score > 3.5 (median/MAD) on daily means. These are screening definitions, not official designations.
* Timestamps are naive IST; Spark session timezone is `Asia/Kolkata`. Bounds in `summary.json` are formatted inside Spark (a test guards against a 5 h 30 min shift).

## Layout

```
src/aq/{config,aqi,spark_pipeline,insights}.py   scripts/download_data.py   app.py
tests/   report/{build_report,diagrams}.py + report_config.json   docs/pytest_report.xml
```
