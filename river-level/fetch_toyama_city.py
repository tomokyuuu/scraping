"""富山市 Toyama Smart City Square (tscs.city.toyama.lg.jp) の河川水位（10分値）を日別 CSV に保存する。

市管理の小河川（がめ川・中川・蜷川川など）が中心で、川の防災情報には無い観測所が多い。
CSV ダウンロードが日付指定でできる（約30日分）。

  一覧+最新値 : POST /map/listdata.ashx {'reqcmd':'1','panelid':'3','order':''}
  座標        : POST /map/mapdata.ashx  {'reqcmd':'1','panelid':'3'}
  10分値 CSV  : GET  /map/download.aspx?indiv_id={id}&meas=dt&sdate=YYYYMMDDHHmm&edate=YYYYMMDDHHmm

使い方:
  python fetch_toyama_city.py --days 1    昨日と今日（既定）
  python fetch_toyama_city.py --days 0    最新値だけ（地図更新用。CSV は書かない）

出力（毎回まるごと上書き）:
  data/toyama_city/{YYYY}/{YYYY-MM-DD}.csv
  data/toyama_city/stations.csv
  docs/latest_toyama_city.geojson
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = "https://tscs.city.toyama.lg.jp/map/"
UA = "Mozilla/5.0 (river-level logger; github actions)"
PANEL = "3"  # 河川水位情報
ROOT = Path(__file__).parent
DATA = ROOT / "data" / "toyama_city"
GEOJSON = ROOT / "docs" / "latest_toyama_city.geojson"
VALUE_FIELDS = ["obs_time", "obs_id", "obs_nm", "stg"]


def post_json(path: str, body: str) -> list | dict:
    req = urllib.request.Request(BASE + path, data=body.encode("utf-8"), method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/json; charset=utf-8",
                                          "Referer": BASE + "list.aspx?panel_id=" + PANEL})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get_csv(obs_id: str, start: datetime, end: datetime, retries: int = 3) -> list[tuple[str, float | None]]:
    url = (BASE + f"download.aspx?indiv_id={obs_id}&meas=dt"
           f"&sdate={start:%Y%m%d%H%M}&edate={end:%Y%m%d%H%M}")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE + "graph.aspx"})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            break
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"retry {obs_id}: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp932")
    rows = []
    for line in text.splitlines()[1:]:  # 1行目は "日時,水位"
        t, _, v = line.partition(",")
        if not t.strip():
            continue
        try:
            rows.append((t.strip(), float(v)))
        except ValueError:
            rows.append((t.strip(), None))
    return rows


def write_day_files(rows: list[dict], days: list[str]) -> None:
    by_day: dict[str, dict[tuple, dict]] = {d: {} for d in days}
    for r in rows:
        day = r["obs_time"][:10].replace("/", "-")
        if day in by_day:
            by_day[day][(r["obs_time"], r["obs_id"])] = r
    for day, m in by_day.items():
        if not m:
            continue
        path = DATA / day[:4] / f"{day}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=VALUE_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(m[k] for k in sorted(m))


def main(days_back: int) -> None:
    listing = post_json("listdata.ashx", f"{{'reqcmd':'1','panelid':'{PANEL}','order':''}}")[0]["detaildatas"]
    coords = {m["id"]: json.loads(m["center"]) for m in post_json("mapdata.ashx", f"{{'reqcmd':'1','panelid':'{PANEL}'}}")}
    now = datetime.now()
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_back, -1, -1)]
    start = (now - timedelta(days=days_back)).replace(hour=0, minute=0)
    print(f"toyama_city: {len(listing)} stations, days: {days[0]}..{days[-1]}")

    stations, rows, feats = [], [], []
    for d in listing:
        oid, name = d["individ"], d["indevname"]
        c = d["contents"][0] if d.get("contents") else {}
        latlon = coords.get(oid)
        stations.append({"obs_id": oid, "obs_nm": name, "lat": latlon[0] if latlon else None,
                         "lon": latlon[1] if latlon else None})
        if days_back > 0:
            try:
                for t, v in get_csv(oid, start, now):
                    if v is not None:
                        rows.append({"obs_time": t, "obs_id": oid, "obs_nm": name, "stg": v})
            except Exception as e:  # noqa: BLE001
                print(f"skip csv {oid} {name}: {e}", file=sys.stderr)
        if latlon:
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [latlon[1], latlon[0]]},
                          "properties": {"pref": "toyama_city", "kind": "city", "obs_id": oid, "obs_nm": name,
                                         "obs_time": d.get("getdate"), "stg": c.get("text_d"),
                                         "diff": d.get("icondata", {}).get("diff"),
                                         "url": BASE + f"graph.aspx?panel_id={PANEL}&indiv_id={oid}"}})

    if days_back > 0:
        write_day_files(rows, days)
        print(f"toyama_city: {len(rows)} values")

    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "stations.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["obs_id", "obs_nm", "lat", "lon"], lineterminator="\n")
        w.writeheader()
        w.writerows(stations)
    GEOJSON.parent.mkdir(exist_ok=True)
    GEOJSON.write_text(json.dumps({"type": "FeatureCollection", "updated": now.strftime("%Y/%m/%d %H:%M"),
                                   "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(int(args[args.index("--days") + 1]) if "--days" in args else 1)
