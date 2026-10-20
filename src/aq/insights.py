"""Rule-based insights and recommendations computed only from pipeline outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config as C


def load(results: Path | str) -> dict[str, pd.DataFrame]:
    p = Path(results) / "parquet"
    out = {}
    for d in sorted(p.iterdir()):
        if d.is_dir() and d.name not in ("clean_hourly",):
            out[d.name] = pd.read_parquet(d)
    return out


def _wavg(df: pd.DataFrame, val: str, w: str, by: str) -> pd.Series:
    g = df.assign(_x=df[val] * df[w]).groupby(by)
    return g["_x"].sum() / g[w].sum()


def generate(results: Path | str, param: str = "PM2.5") -> dict:
    results = Path(results)
    t = load(results)
    s = json.loads((results / "summary.json").read_text())
    f, rec, lim = [], [], []

    f.append(f"Coverage: {s['rows_clean_unique']:,} cleaned hourly readings from {s['stations']} stations in "
             f"{s['cities']} cities / {s['states']} states, {s['first_timestamp_ist'][:10]} to {s['last_timestamp_ist'][:10]} (IST).")
    rej = sum(s["rows_rejected_by_reason"].values())
    f.append(f"Data quality: {rej:,} of {s['rows_read']:,} rows ({100 * rej / max(s['rows_read'], 1):.2f}%) were rejected and "
             f"{s['duplicates_removed']:,} duplicate keys removed.")

    cs = t["city_summary"]
    c = cs[(cs.parameter_name == param) & (cs.n_station_days >= 30)].sort_values("mean_daily", ascending=False)
    if len(c):
        top = c.head(5)
        f.append(f"Most polluted cities by mean daily {param}: " +
                 "; ".join(f"{r.city_name} ({r.mean_daily:.1f} µg/m³)" for r in top.itertuples()) +
                 f". Cleanest of {len(c)} ranked cities: {c.iloc[-1].city_name} ({c.iloc[-1].mean_daily:.1f}).")
    ss = t["state_summary"]
    st = ss[(ss.parameter_name == param) & (ss.n_station_days >= 30)].sort_values("mean_daily", ascending=False)
    if len(st):
        f.append(f"Highest-{param} states: " + "; ".join(f"{r.state_name} ({r.mean_daily:.1f})" for r in st.head(3).itertuples()) + ".")

    for p in ("PM2.5", "PM10"):
        x = cs[(cs.parameter_name == p) & cs.pct_days_above_naaqs.notna()]
        if len(x):
            pct = (x.pct_days_above_naaqs * x.n_station_days).sum() / x.n_station_days.sum()
            f.append(f"{p}: {pct:.1f}% of valid station-days exceeded the NAAQS 24-hour limit of {C.NAAQS_24H[p]} µg/m³.")
            if p == "PM2.5" and pct > 25:
                rec.append(f"Prioritise PM2.5 control: {pct:.0f}% of station-days breach the 24-hour standard.")

    sc = t["seasonal_city"]
    sc = sc[sc.parameter_name == param]
    if len(sc):
        sea = _wavg(sc, "mean_daily", "n_station_days", "season").reindex(C.SEASON_ORDER).dropna()
        if len(sea) >= 2:
            f.append(f"Seasonality of {param} (station-day weighted): " + ", ".join(f"{k} {v:.1f}" for k, v in sea.items()) +
                     f". Peak season is {sea.idxmax()}, {sea.max() / sea.min():.1f}x the lowest ({sea.idxmin()}).")
            rec.append(f"Time interventions and public advisories for the {sea.idxmax()} season, when {param} peaks in this sample.")
    hp = t["hourly_pattern"]
    hp = hp[hp.parameter_name == param]
    if len(hp):
        h = _wavg(hp, "mean_value", "n_readings", "hour")
        f.append(f"Daily cycle of {param} (IST): highest around {int(h.idxmax()):02d}:00 ({h.max():.1f} µg/m³), "
                 f"lowest around {int(h.idxmin()):02d}:00 ({h.min():.1f}).")

    hs = t["hotspots"]
    hh = hs[(hs.parameter_name == param) & hs.is_hotspot].sort_values("rank")
    n_elig = int((hs.parameter_name == param).sum())
    if len(hh):
        f.append(f"Hotspots: {len(hh)} of {n_elig} eligible stations are in the top {int((1 - C.HOTSPOT_PERCENTILE) * 100)}% "
                 f"for mean {param}; the highest are " +
                 "; ".join(f"{r.station_name or r.station_id}, {r.city_name} ({r.mean_daily:.1f})" for r in hh.head(3).itertuples()) + ".")
        by_state = hh.groupby("state_name").size().sort_values(ascending=False)
        f.append("States hosting most hotspots: " + ", ".join(f"{k} ({v})" for k, v in by_state.head(3).items()) + ".")
        rec.append(f"Deploy source-apportionment studies first at hotspot stations in {by_state.index[0]}.")

    an = t["anomaly_summary"]
    an = an[an.parameter_name == param]
    if len(an):
        tot = int(an.n_anomalies.sum())
        top = an.sort_values("n_anomalies", ascending=False).head(3)
        f.append(f"Anomalies: {tot:,} station-days ({100 * tot / an.n_station_days.sum():.2f}%) had {param} spikes with "
                 f"modified z-score > {C.ANOMALY_Z}; most in " + ", ".join(f"{r.city_name} ({r.n_anomalies})" for r in top.itertuples()) + ".")
        rec.append("Review flagged spike days against local events (biomass burning, festivals, dust) before treating them as sensor faults.")

    cat = t.get("aqi_category_city")
    if cat is not None and len(cat):
        tot = cat.groupby("aqi_category").n_station_days.sum()
        n = tot.sum()
        order = [k for k in ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"] if k in tot.index]
        f.append(f"Computed CPCB AQI on {int(n):,} station-days: " + ", ".join(f"{k} {100 * tot[k] / n:.1f}%" for k in order) + ".")
        dom = t["aqi_dominant_city"].groupby("dominant").n_station_days.sum().sort_values(ascending=False)
        f.append(f"Dominant pollutant behind the AQI: {dom.index[0]} ({100 * dom.iloc[0] / dom.sum():.1f}% of station-days).")
    else:
        lim.append("No station-day met the CPCB AQI validity rules in this run.")

    lim += [
        "Values are as received from CPCB/US Embassy monitors: no calibration or gap-filling by the source.",
        "Aggregates describe monitored stations, which are not uniformly distributed; they are not population-weighted.",
        f"Results cover {s['first_timestamp_ist'][:10]} to {s['last_timestamp_ist'][:10]} only; seasonal claims need full-year coverage.",
        "Hotspot and anomaly rules are statistical definitions (top decile; modified z-score), not regulatory designations.",
    ]
    return {"findings": f, "recommendations": rec, "limitations": lim}


def write(results: Path | str) -> dict:
    res = generate(results)
    r = Path(results)
    (r / "insights.json").write_text(json.dumps(res, indent=2))
    md = ["# Insights (computed from pipeline output)\n", "## Findings"] + [f"- {x}" for x in res["findings"]]
    md += ["\n## Recommendations"] + [f"- {x}" for x in res["recommendations"]]
    md += ["\n## Limitations"] + [f"- {x}" for x in res["limitations"]]
    (r / "insights.md").write_text("\n".join(md) + "\n")
    return res


if __name__ == "__main__":
    import sys
    print("\n".join(write(sys.argv[1] if len(sys.argv) > 1 else C.DEFAULT_RESULTS)["findings"]))
