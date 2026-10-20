"""Central configuration: schema, units, thresholds, seasons.

Reference values (NAAQS 2009 and CPCB National AQI) were checked against
ies.gov.in summaries on 2026-10-20; confirm with the CPCB notifications before
any regulatory use. Values here are editable.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW = ROOT / "data" / "raw"
DEFAULT_RESULTS = ROOT / "results"

# ---- Source schema (xKDR docs/PUBLIC_API.md, bulk Parquet files) -------------
REQUIRED_COLUMNS = {
    "station_id": "string",
    "parameter_name": "string",
    "unit": "string",
    "collected_at": "timestamp",
    "value": "double",
}
OPTIONAL_COLUMNS = {
    "station_name": "string",
    "state_name": "string",
    "city_name": "string",
    "source": "string",
}

PARAMS = ["PM2.5", "PM10", "NO", "NO2", "NOx", "NH3", "SO2", "CO", "Ozone",
          "Benzene", "Toluene", "Xylene", "O_Xylene", "MP-Xylene", "Eth-Benzene"]

# Canonical unit: CO in mg/m3, everything else in ug/m3.  ppb/ppm rows are
# quarantined (conversion needs temperature/pressure assumptions).
MG_PARAMS = {"CO"}

# Physical plausibility upper bounds in canonical units (assumptions; editable).
PHYSICAL_MAX = {
    "PM2.5": 2000, "PM10": 3000, "NO": 1500, "NO2": 1000, "NOx": 2000,
    "NH3": 2000, "SO2": 1000, "CO": 100, "Ozone": 1000,
    "Benzene": 500, "Toluene": 1000, "Xylene": 1000, "O_Xylene": 1000,
    "MP-Xylene": 1000, "Eth-Benzene": 1000,
}

# NAAQS 2009 24-hour standards (ug/m3), applied to valid daily means.
NAAQS_24H = {"PM2.5": 60, "PM10": 100, "NO2": 80, "SO2": 80, "NH3": 400}

MIN_HOURS_PER_DAY = 16        # CPCB: >=16 h for a valid daily average
MIN_HOURS_8H_WINDOW = 6       # 75% of an 8-hour window
MIN_STATION_DAYS = 60         # station must have this many valid days to be ranked
HOTSPOT_PERCENTILE = 0.90     # top decile of eligible stations
ANOMALY_Z = 3.5               # Iglewicz-Hoaglin modified z-score cut-off
ANOMALY_MIN_DAYS = 30

SEASONS = {  # month -> season (IMD-style grouping)
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Summer", 4: "Summer", 5: "Summer",
    6: "Monsoon", 7: "Monsoon", 8: "Monsoon", 9: "Monsoon",
    10: "Post-monsoon", 11: "Post-monsoon",
}
SEASON_ORDER = ["Winter", "Summer", "Monsoon", "Post-monsoon"]
