
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://airquality.xkdr.org"
DEMO_KEY = "aqi_pJvE7C8lvKe2NVG7xprhK6LCWksa0OteBv7QY4UnQ14"   
KEY_RE = re.compile(r"^v1/measurements/year=(\d{4})/month=(\d{2})/data\.parquet$")


def plan(keys: list[str], years: list[int] | None, months: list[int] | None) -> list[tuple[str, str]]:
    """Map API file keys -> relative local paths, keeping stations + the requested year/months."""
    out = []
    for k in keys:
        if k == "v1/stations.parquet":
            out.append((k, "stations.parquet"))
            continue
        m = KEY_RE.match(k)
        if not m:
            continue
        y, mo = int(m.group(1)), int(m.group(2))
        if (not years or y in years) and (not months or mo in months):
            out.append((k, k[len("v1/"):]))
    return sorted(out, key=lambda t: t[1])


def _get(url: str, key: str, retries: int = 3):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "india-aq-bda/1.0"})
    for i in range(retries):
        try:
            return urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(f"HTTP {e.code}: key rejected or file not allowed for this key (demo key = 2024 only).")
            if e.code < 500 and e.code != 429:
                raise
        except urllib.error.URLError:
            pass
        time.sleep(2 ** i)
    raise SystemExit(f"Failed to fetch {url} after {retries} attempts")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="*", default=[2024])
    ap.add_argument("--months", type=int, nargs="*", default=None)
    ap.add_argument("--dest", default=str(Path(__file__).resolve().parents[1] / "data" / "raw"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    key = os.environ.get("AQI_API_KEY", DEMO_KEY)

    meta = json.load(_get(f"{BASE}/v1/files", key))
    files = {f["key"]: f for f in meta["files"]}
    todo = plan(list(files), a.years, a.months)
    if not todo:
        print("No matching files for the requested years/months.", file=sys.stderr)
        return 1
    for k, rel in todo:
        dest = Path(a.dest) / rel
        size = files[k].get("size")
        if a.dry_run:
            print("would fetch", k, "->", dest)
            continue
        if dest.exists() and size and dest.stat().st_size == size:
            print("skip (exists)", rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        with _get(f"{BASE}/v1/files/{k}", key) as r, open(tmp, "wb") as fh:
            while chunk := r.read(1 << 20):
                fh.write(chunk)
        tmp.replace(dest)
        print("downloaded", rel, f"{dest.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
