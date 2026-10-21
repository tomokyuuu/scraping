"""気象庁 潮位観測データ (jma.go.jp/bosai/tidelevel) から石川県・富山県の潮位を日別 CSV に保存する。

  地点一覧 : /bosai/tidelevel/const/tide_area.json  （class20 コードが 16/17 で始まるものが富山/石川）
  日別観測 : /bosai/tidelevel/data/tide/tide_obs_{YYYYMMDD}_{地点コード}.json
             {"time": "...T00:00:00+09:00", "interval": 15(秒), "tide": [cm...], "departure": [cm...]}  約3週間分

元データは15秒間隔なので、保存は10分ごとの値に間引く。単位は cm（基準面は地点ごと。stations.csv の reference）。

使い方:
  python fetch_jma_tide.py --days 1    昨日と今日（既定）
  python fetch_jma_tide.py --days 0    今日だけ（地図更新用）

出力（毎回まるごと上書き）:
  data/jma_tide/{YYYY}/{YYYY-MM-DD}.csv
  data/jma_tide/stations.csv
  docs/latest_jma_tide.geojson
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = "https://www.jma.go.jp/bosai/tidelevel/"
UA = "Mozilla/5.0 (river-level logger; github actions)"
PREF_PREFIX = {"16": "toyama", "17": "ishikawa"}
STEP_SEC = 600  # 10分
ROOT = Path(__file__).parent
DATA = ROOT / "data" / "jma_tide"
GEOJSON = ROOT / "docs" / "latest_jma_tide.geojson"
VALUE_FIELDS = ["obs_time", "obs_id", "obs_nm", "tide_cm", "departure_cm"]


def get_json(path: str, retries: int = 3) -> dict | None:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8")
            if body.lstrip().startswith("<"):
                return None  # 無い日付は HTML のエラーページが返る
            return json.loads(body)
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"retry {path}: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))
    return None


def stations() -> list[dict]:
    area = get_json("const/tide_area.json") or {}
    out = []
    for c20, v in area.items():
        pref = PREF_PREFIX.get(c20[:2])
        if not pref:
            continue
        for c30 in v.get("class30s", []):
            for s in c30.get("stations", []):
                out.append({"pref": pref, "obs_id": s["code"], "obs_nm": s["name"], "city": v["name"],
                            "operator": s.get("typeName"), "reference": s.get("reference"),
                            "lat": s["lat"], "lon": s["lon"]})
    return out


def day_values(st: dict, day: datetime) -> tuple[list[dict], dict | None]:
    """1地点1日分を10分値に間引く。戻り値は (値リスト, その日の最後の有効値)。"""
    d = get_json(f"data/tide/tide_obs_{day:%Y%m%d}_{st['obs_id']}.json")
    if not d:
        return [], None
    t0 = datetime.fromisoformat(d["time"]).replace(tzinfo=None)
    interval = int(d.get("interval") or 15)
    step = max(1, STEP_SEC // interval)
    tide = d.get("tide") or []
    dep = d.get("departure") or []  # 潮位偏差（実測 - 天文潮）cm
    rows, last = [], None
    for i, v in enumerate(tide):
        if v is None:
            continue
        ts = t0 + timedelta(seconds=i * interval)
        dv = dep[i] if i < len(dep) else None
        last = {"obs_time": ts.strftime("%Y/%m/%d %H:%M"), "tide_cm": v, "departure_cm": dv}
        if i % step == 0:
            rows.append({"obs_time": last["obs_time"], "obs_id": st["obs_id"], "obs_nm": st["obs_nm"],
                         "tide_cm": v, "departure_cm": dv})
    return rows, last


def main(days_back: int) -> None:
    sts = stations()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"jma_tide: {len(sts)} stations, days back: {days_back}")
    by_day: dict[str, list[dict]] = {}
    feats = []
    for st in sts:
        latest = None
        for back in range(days_back, -1, -1):
            day = today - timedelta(days=back)
            rows, last = day_values(st, day)
            by_day.setdefault(day.strftime("%Y-%m-%d"), []).extend(rows)
            if last:
                latest = last
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [st["lon"], st["lat"]]},
                      "properties": {"pref": st["pref"], "kind": "tide", "obs_id": st["obs_id"], "obs_nm": st["obs_nm"],
                                     "operator": st["operator"], "reference": st["reference"],
                                     "obs_time": latest["obs_time"] if latest else None,
                                     "tide_cm": latest["tide_cm"] if latest else None,
                                     "departure_cm": latest["departure_cm"] if latest else None,
                                     "url": BASE + f"#area_type=class20s&point_code={st['obs_id']}"}})
    n = 0
    for day, rows in by_day.items():
        if not rows:
            continue
        path = DATA / day[:4] / f"{day}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=VALUE_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: (r["obs_time"], r["obs_id"])))
        n += len(rows)
    print(f"jma_tide: {n} values")

    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "stations.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sts[0].keys()) if sts else ["obs_id"], lineterminator="\n")
        w.writeheader()
        w.writerows(sts)
    GEOJSON.parent.mkdir(exist_ok=True)
    GEOJSON.write_text(json.dumps({"type": "FeatureCollection", "updated": datetime.now().strftime("%Y/%m/%d %H:%M"),
                                   "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(int(args[args.index("--days") + 1]) if "--days" in args else 1)
