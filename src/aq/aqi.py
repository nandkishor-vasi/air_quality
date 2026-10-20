"""CPCB National AQI sub-index calculation (pure Python + Spark column form).

Rules implemented (CPCB NAQI): sub-index linear within each band, overall AQI =
max sub-index, needs >=3 pollutants incl. PM2.5 or PM10, >=16 h data per day.
CO and O3 use 8-hour averages; the others use 24-hour averages.

Each band is (upper_concentration, upper_aqi), starting from (0, 0).  The final
band's upper concentration is NOT published by CPCB; we extend it by the width of
the previous band (assumption, e.g. PM2.5 250 -> 380) and cap AQI at 500.
"""
from pyspark.sql import Column, functions as F

BANDS = {
    "PM2.5": [(30, 50), (60, 100), (90, 200), (120, 300), (250, 400), (380, 500)],
    "PM10":  [(50, 50), (100, 100), (250, 200), (350, 300), (430, 400), (510, 500)],
    "NO2":   [(40, 50), (80, 100), (180, 200), (280, 300), (400, 400), (520, 500)],
    "Ozone": [(50, 50), (100, 100), (168, 200), (208, 300), (748, 400), (1288, 500)],
    "CO":    [(1, 50), (2, 100), (10, 200), (17, 300), (34, 400), (51, 500)],
    "SO2":   [(40, 50), (80, 100), (380, 200), (800, 300), (1600, 400), (2400, 500)],
    "NH3":   [(200, 50), (400, 100), (800, 200), (1200, 300), (1800, 400), (2400, 500)],
}
EIGHT_HOUR = {"CO", "Ozone"}
PM_PARAMS = {"PM2.5", "PM10"}
CATEGORIES = [(50, "Good"), (100, "Satisfactory"), (200, "Moderate"),
              (300, "Poor"), (400, "Very Poor"), (500, "Severe")]
CATEGORY_ORDER = [c for _, c in CATEGORIES]


def sub_index(param: str, conc):
    """Sub-index for one concentration; None if unsupported/invalid."""
    if param not in BANDS or conc is None or conc != conc or conc < 0:
        return None
    lo_c, lo_i = 0.0, 0.0
    for hi_c, hi_i in BANDS[param]:
        if conc <= hi_c:
            return lo_i + (conc - lo_c) * (hi_i - lo_i) / (hi_c - lo_c)
        lo_c, lo_i = hi_c, hi_i
    return 500.0


def category(aqi):
    if aqi is None or aqi != aqi:
        return None
    for hi, name in CATEGORIES:
        if aqi <= hi:
            return name
    return "Severe"


def overall_aqi(subs: dict):
    """subs: {param: sub_index or None}. Returns (aqi, dominant) or (None, None)."""
    valid = {p: v for p, v in subs.items() if v is not None}
    if len(valid) < 3 or not (PM_PARAMS & valid.keys()):
        return None, None
    p = max(valid, key=valid.get)
    return valid[p], p


def sub_index_col(conc: Column, param: Column) -> Column:
    """Spark expression equivalent of sub_index()."""
    out = F.lit(None).cast("double")
    for p, bands in BANDS.items():
        e = F.lit(500.0)
        # build nested when from the top band down
        segs, lo_c, lo_i = [], 0.0, 0.0
        for hi_c, hi_i in bands:
            segs.append((lo_c, lo_i, hi_c, hi_i))
            lo_c, lo_i = hi_c, hi_i
        chain = None
        for lo_c, lo_i, hi_c, hi_i in segs:
            val = F.lit(lo_i) + (conc - F.lit(lo_c)) * F.lit((hi_i - lo_i) / (hi_c - lo_c))
            chain = F.when(conc <= hi_c, val) if chain is None else chain.when(conc <= hi_c, val)
        e = chain.otherwise(F.lit(500.0))
        out = F.when((param == p) & (conc >= 0), e).otherwise(out)
    return out


def category_col(aqi: Column) -> Column:
    chain = None
    for hi, name in CATEGORIES:
        chain = F.when(aqi <= hi, name) if chain is None else chain.when(aqi <= hi, name)
    return F.when(aqi.isNull(), F.lit(None)).otherwise(chain.otherwise("Severe"))
