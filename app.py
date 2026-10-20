"""Streamlit dashboard over the Spark outputs.  Run: streamlit run app.py"""
import json
import importlib
import os
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    px = importlib.import_module("plotly.express")
except ModuleNotFoundError as exc:
    if exc.name != "plotly" and not (exc.name or "").startswith("plotly."):
        raise
    st.error("Plotly is required to display dashboard charts. Install it with: pip install plotly")
    st.stop()

from src.aq import config as C
from src.aq.aqi import CATEGORY_ORDER
from src.aq.insights import generate

RESULTS = Path(os.environ.get("AQ_RESULTS_DIR", C.DEFAULT_RESULTS))
UNIT = lambda p: "mg/m³" if p == "CO" else "µg/m³"  # noqa: E731

st.set_page_config(page_title="Air Atlas — India Air Quality", page_icon="◌", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { --paper:#f5f5f1; --ink:#202925; --muted:#727b75; --line:#dedfd8; --green:#456b5a; --mint:#dce8df; }
.stApp { background:var(--paper); color:var(--ink); font-family:'DM Sans',sans-serif; }
[data-testid="stHeader"] { background:rgba(245,245,241,.92); }
.block-container { max-width:1440px; padding-top:2.1rem; padding-bottom:4rem; }
h1,h2,h3 { font-family:'Manrope','DM Sans',sans-serif !important; letter-spacing:-.045em; color:var(--ink); }
h1 { font-size:clamp(2.25rem,4vw,4.2rem) !important; line-height:1.02 !important; font-weight:600 !important; }
h2 { font-size:1.7rem !important; font-weight:600 !important; }
h3 { font-size:1.15rem !important; font-weight:600 !important; }
p, label, [data-testid="stCaptionContainer"] { color:var(--muted); }
p {color: #4B514D !important;}
[data-testid="stSidebar"] { background:#eceee8; border-right:1px solid var(--line); }
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { letter-spacing:-.025em; }
[data-testid="stMetric"] { background:#fbfbf8; border:1px solid var(--line); border-radius:16px; padding:18px 18px 15px; min-height:112px; }
[data-testid="stMetricLabel"] p { font-size:.78rem; text-transform:uppercase; letter-spacing:.075em; color:#707a72; }
[data-testid="stMetricValue"] { font-family:'Manrope',sans-serif; font-weight:600; letter-spacing:-.04em; font-size:1.8rem; }
[data-testid="stMetricDelta"] { font-size:.8rem; }
[data-testid="stTabs"] [role="tablist"] { gap:6px; border-bottom:1px solid var(--line); }
[data-testid="stTabs"] button[role="tab"] { border-radius:9px 9px 0 0; padding:12px 15px; color:#707a72; font-size:.9rem; }
[data-testid="stTabs"] button[aria-selected="true"] { color:var(--green); border-bottom:2px solid var(--green); background:#e9eee8; }
[data-testid="stPlotlyChart"] { background:#fbfbf8; border:1px solid var(--line); border-radius:16px; padding:10px 10px 2px; }
.stButton button, .stDownloadButton button { border-radius:999px; border:1px solid #cdd2c9; background:#fbfbf8; color:var(--ink); padding:.45rem 1rem; }
.stButton button:hover, .stDownloadButton button:hover { border-color:var(--green); color:var(--green); }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
hr { border-color:var(--line); }
.eyebrow { font-size:.72rem; text-transform:uppercase; letter-spacing:.16em; color:var(--green); font-weight:700; margin-bottom:.7rem; }
.hero { padding:1.6rem 0 1.1rem; border-bottom:1px solid var(--line); margin-bottom:1.2rem; }
.hero-copy { max-width:800px; color:#626c65; font-size:1.05rem; line-height:1.65; }
.pill { display:inline-block; border:1px solid #cbd8cd; background:#e6eee6; color:#456b5a; border-radius:999px; padding:5px 10px; font-size:.75rem; margin-bottom:1rem; }
@media (max-width: 760px) { .block-container { padding:1.2rem 1rem 3rem; } [data-testid="stMetric"] { padding:12px; } }
[data-testid="stSidebar"] h2 {color: #202925 !important;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #626C65 !important;}
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load(results: str):
    p = Path(results) / "parquet"
    tables = {d.name: pd.read_parquet(d) for d in p.iterdir() if d.is_dir() and d.name != "clean_hourly"}
    summary = json.loads((Path(results) / "summary.json").read_text())
    return tables, summary


def wavg(df, val, w):
    return float((df[val] * df[w]).sum() / df[w].sum()) if len(df) and df[w].sum() else float("nan")


def dl(df, name, key):
    st.download_button("⬇ Download CSV", df.to_csv(index=False).encode(), f"{name}.csv", "text/csv", key=key)


def table(df, name):
    st.dataframe(df, use_container_width=True, hide_index=True)
    dl(df, name, f"dl_{name}")


if not (RESULTS / "summary.json").exists():
    st.markdown('<div class="eyebrow">AIR ATLAS · INDIA</div>', unsafe_allow_html=True)
    st.title("Understand the air we breathe.")
    st.markdown('<p class="hero-copy">A data-led exploration of air pollution patterns, seasonal change and monitoring hotspots across India.</p>', unsafe_allow_html=True)
    st.error(f"No pipeline results in {RESULTS}. Run: python -m src.aq.spark_pipeline --years 2024  (see README).")
    st.stop()

T, S = load(str(RESULTS))
st.title("Understand the air we breathe.")
st.markdown('<p class="hero-copy">Explore pollution patterns, compare cities and states, and identify air-quality hotspots across India — grounded in monitoring data, not guesswork.</p>', unsafe_allow_html=True)
st.caption(f"Analysis period  {S['first_timestamp_ist'][:10]} — {S['last_timestamp_ist'][:10]} IST  ·  Spark {S['spark_version']}")
st.markdown('</div>', unsafe_allow_html=True)
st.caption("SOURCE  ·  India Air Quality Database, XKDR Forum (CC BY 4.0), CPCB CAAQM + US Embassy monitors")

# ---------------- sidebar filters ----------------
cs_all = T["city_summary"]
params = [p for p in C.PARAMS if p in set(cs_all.parameter_name)]
with st.sidebar:
    st.markdown("## Explore the data")
    st.caption("Adjust the view across pollutant, geography and time.")
    param = st.selectbox("Pollutant", params, index=params.index("PM2.5") if "PM2.5" in params else 0)
    states = st.multiselect("State", sorted(cs_all.state_name.unique()))
    city_pool = cs_all[cs_all.state_name.isin(states)] if states else cs_all
    cities = st.multiselect("City", sorted(city_pool.city_name.unique()))
    months = sorted(T["monthly_national"].ym.unique())
    m0, m1 = st.select_slider("Month range", options=months, value=(months[0], months[-1])) if len(months) > 1 else (months[0], months[0])
    seasons = st.multiselect("Season", C.SEASON_ORDER, default=C.SEASON_ORDER)
    top_n = st.slider("Top-N rows in rankings", 5, 30, 10)
    min_days = st.slider("Min. station-days to rank a city/state", 1, 500, 30)


def f(df, by_state=True, by_city=True):
    if by_state and states and "state_name" in df:
        df = df[df.state_name.isin(states)]
    if by_city and cities and "city_name" in df:
        df = df[df.city_name.isin(cities)]
    return df


cs = f(cs_all[(cs_all.parameter_name == param)])
ranked = cs[cs.n_station_days >= min_days].sort_values("mean_daily", ascending=False)
hs = f(T["hotspots"][T["hotspots"].parameter_name == param])
an = f(T["anomaly_summary"][T["anomaly_summary"].parameter_name == param])
naaqs = C.NAAQS_24H.get(param)

# ---------------- metric cards ----------------
c = st.columns(6)
c[0].metric("Stations", f"{S['stations']:,}")
c[1].metric("Cities / States", f"{S['cities']} / {S['states']}")
c[2].metric("Clean hourly readings", f"{S['rows_clean_unique']:,}")
c[3].metric(f"Mean daily {param}", f"{wavg(cs, 'mean_daily', 'n_station_days'):.1f} {UNIT(param)}")
c[4].metric("Most polluted city", ranked.iloc[0].city_name if len(ranked) else "–",
            f"{ranked.iloc[0].mean_daily:.1f}" if len(ranked) else None, delta_color="off")
c[5].metric("Days above NAAQS", f"{wavg(cs.dropna(subset=['pct_days_above_naaqs']), 'pct_days_above_naaqs', 'n_station_days'):.1f}%" if naaqs else "n/a")
c = st.columns(3)
c[0].metric("Hotspot stations", f"{int(hs.is_hotspot.sum()) if len(hs) else 0} of {len(hs)}")
c[1].metric("Anomalous station-days", f"{int(an.n_anomalies.sum()):,}" if len(an) else "0")
c[2].metric("Station-days with valid AQI", f"{S['station_days_with_valid_aqi']:,}")

st.markdown("## Analysis workspace")
st.caption(f"Current view · {param} · {m0} to {m1}")
tabs = st.tabs(["Places", "Trends", "By hour", "Hotspots", "Anomalies", "AQI", "Findings", "Data quality"])

with tabs[0]:
    a, b = st.columns(2)
    with a:
        top = ranked.head(top_n)
        fig = px.bar(top.iloc[::-1], x="mean_daily", y="city_name", orientation="h", color="mean_daily",
                     color_continuous_scale="YlOrRd", hover_data=["state_name", "n_stations", "n_station_days"],
                     labels={"mean_daily": f"Mean daily {param} ({UNIT(param)})", "city_name": ""}, title=f"Top {top_n} cities")
        if naaqs:
            fig.add_vline(x=naaqs, line_dash="dash", annotation_text=f"NAAQS {naaqs}")
        st.plotly_chart(fig, use_container_width=True)
    with b:
        sr = f(T["state_summary"][T["state_summary"].parameter_name == param], by_city=False)
        sr = sr[sr.n_station_days >= min_days].sort_values("mean_daily", ascending=False).head(top_n)
        fig = px.bar(sr.iloc[::-1], x="mean_daily", y="state_name", orientation="h", color="mean_daily",
                     color_continuous_scale="YlOrRd", labels={"mean_daily": f"Mean daily {param}", "state_name": ""},
                     title=f"Top {top_n} states")
        st.plotly_chart(fig, use_container_width=True)
    table(ranked.head(max(top_n, 25)), f"city_summary_{param}")
    st.caption("Cross-parameter comparison (all cities in filter):")
    cmp_ = f(cs_all).groupby("parameter_name").apply(lambda d: pd.Series({"mean_daily": wavg(d, "mean_daily", "n_station_days"),
                                                                           "p95_daily": d.p95_daily.max(), "stations": d.n_stations.sum()}),
                                                     include_groups=False).reset_index()
    table(cmp_.round(2), "pollutant_comparison")

with tabs[1]:
    nat = T["monthly_national"]
    nat = nat[(nat.parameter_name == param) & nat.ym.between(m0, m1)]
    mc = f(T["monthly_city"])
    mc = mc[(mc.parameter_name == param) & mc.ym.between(m0, m1)]
    fig = px.line(nat, x="ym", y="mean_daily", markers=True, title=f"National mean daily {param} by month",
                  labels={"ym": "Month", "mean_daily": UNIT(param)})
    if len(mc) and (cities or states):
        for (ci,), d in mc.groupby(["city_name"]):
            fig.add_scatter(x=d.ym, y=d.mean_daily, name=ci, mode="lines+markers")
    st.plotly_chart(fig, use_container_width=True)
    sc = f(T["seasonal_city"])
    sc = sc[(sc.parameter_name == param) & sc.season.isin(seasons)]
    if len(sc):
        sea = sc.groupby("season").apply(lambda d: wavg(d, "mean_daily", "n_station_days"), include_groups=False).reindex(C.SEASON_ORDER).dropna().reset_index(name="mean_daily")
        st.plotly_chart(px.bar(sea, x="season", y="mean_daily", color="season", title=f"Seasonal mean {param} (filtered cities)"),
                        use_container_width=True)
        top_c = ranked.head(8).city_name
        heat = sc[sc.city_name.isin(top_c)].pivot_table(index="city_name", columns="season", values="mean_daily").reindex(columns=[s for s in C.SEASON_ORDER if s in seasons])
        st.plotly_chart(px.imshow(heat, color_continuous_scale="YlOrRd", aspect="auto", text_auto=".0f",
                                  title="Season × city (top cities)"), use_container_width=True)
    table(nat, f"monthly_national_{param}")

with tabs[2]:
    hp = f(T["hourly_pattern"])
    hp = hp[hp.parameter_name == param]
    if len(hp):
        pick = cities or list(ranked.head(5).city_name)
        d = hp[hp.city_name.isin(pick)]
        st.plotly_chart(px.line(d, x="hour", y="mean_value", color="city_name", markers=True,
                                labels={"hour": "Hour of day (IST)", "mean_value": f"{param} ({UNIT(param)})"},
                                title=f"Diurnal pattern of {param}"), use_container_width=True)
        table(d, f"hourly_{param}")
    else:
        st.info("No hourly data for this selection.")

with tabs[3]:
    if len(hs):
        hs_top = hs.sort_values("rank").head(max(top_n, 50))
        geo = hs.dropna(subset=["latitude", "longitude"]) if "latitude" in hs else hs.iloc[0:0]
        if len(geo):
            fig = px.scatter_map(geo, lat="latitude", lon="longitude", color="mean_daily", size="mean_daily",
                                 hover_name="station_name", hover_data=["city_name", "state_name", "n_days", "is_hotspot"],
                                 color_continuous_scale="YlOrRd", zoom=3.6, height=560, map_style="open-street-map",
                                 title=f"Stations by mean daily {param}")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Stations have no coordinates in this run (stations.parquet missing).")
        st.caption(f"Hotspot = top {int((1 - C.HOTSPOT_PERCENTILE) * 100)}% of stations by mean daily {param}, with ≥ {S['min_station_days']} valid days.")
        table(hs_top, f"hotspots_{param}")
    else:
        st.info("No eligible stations for this selection.")

with tabs[4]:
    ad = f(T["anomaly_days"])
    ad = ad[ad.parameter_name == param]
    if len(an):
        t = an.sort_values("n_anomalies", ascending=False).head(top_n)
        st.plotly_chart(px.bar(t, x="city_name", y="n_anomalies", hover_data=["pct_anomalous", "n_station_days"],
                               title=f"Cities with most {param} spikes (modified z > {S['anomaly_z_cut']})"), use_container_width=True)
    st.caption("Largest spike days (top 2,000 stored overall, filtered here).")
    table(ad.head(500), f"anomalies_{param}")

with tabs[5]:
    cat = f(T["aqi_category_city"])
    if len(cat):
        tot = cat.groupby("aqi_category").n_station_days.sum().reindex(CATEGORY_ORDER).dropna().reset_index()
        a, b = st.columns(2)
        a.plotly_chart(px.bar(tot, x="aqi_category", y="n_station_days", color="aqi_category", title="Station-days by CPCB AQI category"),
                       use_container_width=True)
        dom = f(T["aqi_dominant_city"]).groupby("dominant").n_station_days.sum().reset_index()
        b.plotly_chart(px.pie(dom, names="dominant", values="n_station_days", hole=.45, title="Dominant pollutant"), use_container_width=True)
        am = f(T["aqi_city_monthly"])
        am = am[am.ym.between(m0, m1)]
        pick = cities or list(am.groupby("city_name").mean_aqi.mean().sort_values(ascending=False).head(5).index)
        st.plotly_chart(px.line(am[am.city_name.isin(pick)], x="ym", y="mean_aqi", color="city_name", markers=True,
                                title="Monthly mean AQI"), use_container_width=True)
        table(am, "aqi_city_monthly")
        st.caption("AQI computed from hourly data by CPCB rules (≥16 h/day, ≥3 pollutants incl. PM2.5 or PM10); the source supplies no AQI column.")
    else:
        st.info("No station-day satisfied the AQI validity rules.")

with tabs[6]:
    ins = generate(RESULTS, param)
    st.subheader("Findings")
    for x in ins["findings"]:
        st.markdown(f"- {x}")
    st.subheader("Recommendations")
    for x in ins["recommendations"] or ["No rule-based recommendation triggered for this selection."]:
        st.markdown(f"- {x}")
    st.subheader("Limitations")
    for x in ins["limitations"]:
        st.markdown(f"- {x}")

with tabs[7]:
    rej = pd.DataFrame(list(S["rows_rejected_by_reason"].items()), columns=["reason", "rows"])
    a, b = st.columns(2)
    a.metric("Rows read", f"{S['rows_read']:,}")
    b.metric("Duplicates removed", f"{S['duplicates_removed']:,}")
    st.write("Rejected rows by reason"); table(rej, "rejections")
    st.write("Units seen per parameter"); table(pd.DataFrame(S["unit_mix"]), "unit_mix")
    st.write("Coverage per parameter"); table(T["data_coverage"], "data_coverage")
    st.download_button("⬇ summary.json", json.dumps(S, indent=2), "summary.json", key="dl_summary")
