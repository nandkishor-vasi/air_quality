import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dl():
    spec = importlib.util.spec_from_file_location("download_data", ROOT / "scripts" / "download_data.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_download_plan_filters_and_maps():
    dl = _load_dl()
    keys = ["v1/stations.parquet", "v1/parameters.parquet",
            "v1/measurements/year=2024/month=01/data.parquet",
            "v1/measurements/year=2024/month=02/data.parquet",
            "v1/measurements/year=2023/month=02/data.parquet", "v1/other.txt"]
    p = dl.plan(keys, [2024], [2])
    assert set(p) == {("v1/stations.parquet", "stations.parquet"),
                      ("v1/measurements/year=2024/month=02/data.parquet", "measurements/year=2024/month=02/data.parquet")}
    assert len(dl.plan(keys, [2023, 2024], None)) == 4


def test_dashboard_runs_without_exception(results, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("AQ_RESULTS_DIR", str(results[0]))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.metric) >= 9 and len(at.tabs) == 8
    at.selectbox[0].select("PM10").run()           # change a filter
    assert not at.exception


def test_dashboard_shows_helpful_error_without_results(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("AQ_RESULTS_DIR", str(tmp_path))
    at = AppTest.from_file(str(ROOT / "app.py")).run()
    assert at.error and "No pipeline results" in at.error[0].value
