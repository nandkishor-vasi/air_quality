"""Architecture and pipeline diagrams drawn with matplotlib (real diagrams of this codebase)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

BLUE, ORANGE, GREY, GREEN = "#dbe9f6", "#fde4c8", "#eeeeee", "#dff0d8"


def _box(ax, x, y, w, h, text, fc=BLUE, fs=8):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec="#444", lw=1))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, wrap=True)


def _arrow(ax, x0, y0, x1, y1):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="->", lw=1.3, color="#333"))


def architecture(path):
    fig, ax = plt.subplots(figsize=(7.4, 5.2))
    ax.set_xlim(0, 7.4); ax.set_ylim(0, 5.2); ax.axis("off")
    w, h = 2.2, 1.0
    X = [0.1, 2.6, 5.1]
    r1, r2, r3 = 3.9, 2.3, 0.7
    fs = 7.8
    _box(ax, X[0], r1, w, h, "India Air Quality Database\n(xKDR, CC BY 4.0)\nmonthly Parquet files", GREY, fs)
    _box(ax, X[1], r1, w, h, "scripts/download_data.py\n(API key, year/month filter)", BLUE, fs)
    _box(ax, X[2], r1, w, h, "data/raw/measurements\nyear=/month=/data.parquet\n+ stations.parquet", GREY, fs)
    _arrow(ax, X[0] + w, r1 + h / 2, X[1], r1 + h / 2); _arrow(ax, X[1] + w, r1 + h / 2, X[2], r1 + h / 2)
    _box(ax, X[2], r2, w, h, "Spark 1: read + validate\nschema, casts, IST time", ORANGE, fs)
    _box(ax, X[1], r2, w, h, "Spark 2: clean\nunits, bounds, rejects,\ndeduplication", ORANGE, fs)
    _box(ax, X[0], r2, w, h, "Spark 3: aggregate\ncity/state, month, season,\nhour, hotspot, anomaly, AQI", ORANGE, fs)
    _arrow(ax, X[2] + w / 2, r1, X[2] + w / 2, r2 + h)
    _arrow(ax, X[2], r2 + h / 2, X[1] + w, r2 + h / 2); _arrow(ax, X[1], r2 + h / 2, X[0] + w, r2 + h / 2)
    _box(ax, X[0], r3, w, h, "results/parquet, results/csv\nsummary.json, pipeline.log", GREEN, fs)
    _box(ax, X[1], r3, w, h, "src/aq/insights.py\nfindings from computed\ntables only", BLUE, fs)
    _box(ax, X[2], r3, w, h, "Streamlit + Plotly dashboard\nreport/build_report.py\n(DOCX / PDF)", BLUE, fs)
    _arrow(ax, X[0] + w / 2, r2, X[0] + w / 2, r3 + h)
    _arrow(ax, X[0] + w, r3 + h / 2, X[1], r3 + h / 2); _arrow(ax, X[1] + w, r3 + h / 2, X[2], r3 + h / 2)
    ax.text(3.7, 0.2, "Apache Cassandra is not used in this implementation (Section 6); Parquet is the storage layer.",
            ha="center", fontsize=7.5, style="italic")
    fig.savefig(path, dpi=200, bbox_inches="tight"); plt.close(fig)


def pipeline(path):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.set_xlim(0, 8); ax.set_ylim(0, 4.2); ax.axis("off")
    steps = ["Read Parquet\n(partition pruning\nby year)", "Validate schema\n+ cast types", "Flag rejects\n(null key, unknown\nparameter, invalid,\nunit, bound)",
             "Standardise units\n(CO mg/m³,\nothers µg/m³)", "Deduplicate\n(station, parameter,\ntimestamp)", "Daily means\n(≥ 16 h per day)", "Aggregate,\nrank and flag"]
    w, gap, h = 1.75, 0.3, 1.3
    pos = [(0.1 + i * (w + gap), 2.7) for i in range(4)] + [(0.1 + i * (w + gap), 0.9) for i in range(3)]
    for i, (s, (x, y)) in enumerate(zip(steps, pos)):
        _box(ax, x, y, w, h, s, ORANGE if i in (2, 3, 4) else BLUE, fs=8.5)
        if i and i != 4:
            _arrow(ax, x - gap, y + h / 2, x, y + h / 2)
    x3, x4, ymid = pos[3][0] + w / 2, pos[4][0] + w / 2, 2.45                    # elbow connector to second row
    ax.plot([x3, x3, x4], [pos[3][1], ymid, ymid], color="#333", lw=1.3)
    _arrow(ax, x4, ymid, x4, pos[4][1] + h)
    ax.text(4, 0.45, "Rejected-row counts per reason, duplicates and unit mix are written to summary.json.", ha="center", fontsize=8, style="italic")
    ax.text(4, 0.1, "Orange = data-quality stages", ha="center", fontsize=8)
    fig.savefig(path, dpi=200, bbox_inches="tight"); plt.close(fig)
