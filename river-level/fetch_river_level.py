"""川の防災情報 (river.go.jp) から石川県・富山県の河川水位（10分値）を取得して日別 CSV に保存する。

データソース（サイト内部の静的 JSON）:
  現在時刻          : /kawabou/file/system/tmCrntTime.json
  市町村一覧        : /kawabou/file/files/obslist/idx/pref/twn/{prefCd}.json
  観測所+座標+基準  : /kawabou/file/gjson/obs/{YYYYMMDD}/{HHmm}/stg/{twnCd}.json    (通常の水位計)
                      /kawabou/file/gjson/obs/{YYYYMMDD}/{HHmm}/swstg/{twnCd}.json  (危機管理型水位計)
  10分値            : /kawabou/file/files/tmlist/stg/{YYYYMMDD}/{HHmm}/{obsFcd}.json
                      指定時刻から遡って50個（8時間20分）の10分値。1週間ほど前まで指定できる
                      /kawabou/file/files/tmlist/swstg/{YYYYMMDD}/{HHmm}/{swobsCd}.json
                      危機管理型は送信があった時刻だけ（直近1週間）

使い方:
  python fetch_river_level.py --days 1    昨日と今日（既定）
  python fetch_river_level.py --days 6    1週間ぶん取り直す

出力（毎回まるごと上書き。追記はしない）:
  data/{pref}/{YYYY}/{YYYY-MM-DD}.csv   その日の10分値
  data/stations.csv                     観測所マスタ
  docs/latest.geojson                   地図表示用：観測所の座標・基準水位・最新値
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

BASE = "https://www.river.go.jp/kawabou/file"
UA = "Mozilla/5.0 (river-level logger; github actions)"
PREFS = {"1701": "ishikawa", "1601": "toyama"}
# 1日を 8時間20分 の窓3つで覆う時刻
DAY_TIMES = ["0810", "1620", "2350"]
ROOT = Path(__file__).parent
DATA = ROOT / "data"
GEOJSON = ROOT / "docs" / "latest.geojson"
DATA_URL = os.environ.get("DATA_URL", "https://github.com/tomokyuuu/scraping/tree/main/data")

STATION_FIELDS = ["pref", "twn_cd", "kind", "obs_id", "obs_nm", "rvr_cd", "lat", "lon",
                  "rsrv_stg", "warn_stg", "spcl_warn_stg", "dng_stg", "fld_stg"]
VALUE_FIELDS = ["obs_time", "kind", "obs_id", "obs_nm", "stg", "stg_ccd", "stg_ovlvl"]


def get_json(path: str, retries: int = 3) -> dict | None:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8")
            if body.lstrip().startswith("<"):
                return None  # 無いものは HTML の案内ページが返る
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == retries - 1:
                raise
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"retry {path}: {e}", file=sys.stderr)
        time.sleep(2 * (i + 1))
    return None


def fetch_town(pref: str, twn: int, kind: str, date_path: str) -> list[dict]:
    """1市町村・1種別の GeoJSON から観測所マスタ（最新値つき）を取り出す。"""
    d = get_json(f"/gjson/obs/{date_path}/{kind}/{twn}.json")
    if not d:
        print(f"skip {pref}/{twn}/{kind}", file=sys.stderr)
        return []
    # 通常水位計の GeoJSON には水位値そのものが無いので、一覧 JSON から取る
    tm: dict[str, dict] = {}
    if kind == "stg":
        lst = get_json(f"/files/obslist/tm/twnlist/{date_path}/{twn}.json") or {}
        tm = {v["obsFcd"]: v for v in lst.get("tmList", {}).get("tmStg", [])}
    out = []
    for f in d["features"]:
        p = f["properties"]
        if kind == "stg":
            oid, name, rvr = p["obs_fcd"], p["obs_nm"], p.get("rvr_cd")
            thr = (p.get("rsrv_stg"), p.get("warn_stg"), p.get("spcl_warn_stg"), p.get("dng_stg"), p.get("fld_stg"))
            v = tm.get(oid, {})
            p = {**p, "stg": v.get("stg"), "obs_time": v.get("obsTime", p.get("obs_time")),
                 "stg_ccd": v.get("stgCcd", p.get("stg_ccd")), "stg_ovlvl": v.get("stgOvlvl", p.get("stg_ovlvl"))}
            ccd, ovlvl = p.get("stg_ccd"), p.get("stg_ovlvl")
        else:
            oid, name, rvr = str(p["swobs_cd"]), p["swobs_nm"], p.get("swrvr_cd")
            thr = (p.get("strt_stg"), None, None, p.get("dng_stg"), p.get("fld_stg"))
            ccd, ovlvl = p.get("stg_qmflg"), p.get("swstg_ovlvl")
        out.append({"pref": pref, "twn_cd": twn, "kind": kind, "obs_id": oid, "obs_nm": name,
                    "rvr_cd": rvr, "lat": p["lat"], "lon": p["lon"],
                    "rsrv_stg": thr[0], "warn_stg": thr[1], "spcl_warn_stg": thr[2],
                    "dng_stg": thr[3], "fld_stg": thr[4],
                    "obs_time": p.get("obs_time"), "stg": p.get("stg"), "stg_ccd": ccd, "stg_ovlvl": ovlvl})
    return out


def fetch_min10(st: dict, date_path: str) -> list[dict]:
    d = get_json(f"/files/tmlist/{st['kind']}/{date_path}/{st['obs_id']}.json")
    if not d:
        return []
    rows = []
    for v in d.get("min10Values") or []:
        if not v.get("obsTime"):
            continue
        rows.append({"obs_time": v["obsTime"], "kind": st["kind"], "obs_id": st["obs_id"], "obs_nm": st["obs_nm"],
                     "stg": v.get("stg"), "stg_ccd": v.get("stgCcd", v.get("stgQmFlg")),
                     "stg_ovlvl": v.get("stgOvlvl", v.get("swstgOvlvl"))})
    return rows


def write_day_files(pref: str, rows: list[dict], days: list[str]) -> None:
    """日ごとに CSV をまるごと書き直す（対象日のうち、値が1つも無い日は書かない）。"""
    by_day: dict[str, dict[tuple, dict]] = {d: {} for d in days}
    for r in rows:
        day = r["obs_time"][:10].replace("/", "-")
        if day in by_day:
            by_day[day][(r["obs_time"], r["kind"], r["obs_id"])] = r
    for day, m in by_day.items():
        if not m:
            continue
        path = DATA / pref / day[:4] / f"{day}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=VALUE_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(m[k] for k in sorted(m))


def write_geojson(stations: list[dict], crnt: str) -> None:
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
              "properties": {k: v for k, v in s.items() if k not in ("lat", "lon")}} for s in stations]
    GEOJSON.parent.mkdir(exist_ok=True)
    GEOJSON.write_text(json.dumps({"type": "FeatureCollection", "updated": crnt, "data_url": DATA_URL,
                                   "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main(days_back: int) -> None:
    crnt = get_json("/system/tmCrntTime.json")["crntObsTime"]  # "2026/10/21 16:10"
    now = datetime.strptime(crnt, "%Y/%m/%d %H:%M")
    now_path = now.strftime("%Y%m%d/%H%M")
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_back, -1, -1)]
    print(f"current obs time: {crnt}, days: {days[0]}..{days[-1]}")

    # 取りに行く時刻: 過去日は3回、今日は now までの窓 + now
    paths: list[str] = []
    for d in days:
        ymd = d.replace("-", "")
        for t in DAY_TIMES:
            if ymd + t < now.strftime("%Y%m%d%H%M"):
                paths.append(f"{ymd}/{t}")
    paths.append(now_path)

    all_stations: list[dict] = []
    for pref_cd, pref in PREFS.items():
        towns = get_json(f"/files/obslist/idx/pref/twn/{pref_cd}.json")["twnInfo"]
        stations: list[dict] = []
        for t in towns:
            if t.get("stgExistFlg"):
                stations += fetch_town(pref, t["twnCd"], "stg", now_path)
            if t.get("swExistFlg"):
                stations += fetch_town(pref, t["twnCd"], "swstg", now_path)

        # 通常水位計は窓ごと、危機管理型は1週間ぶんが1回で返るので now だけ
        jobs = [(s, p) for s in stations for p in (paths if s["kind"] == "stg" else [now_path])]
        rows: list[dict] = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            for r in ex.map(lambda j: fetch_min10(*j), jobs):
                rows += r
        write_day_files(pref, rows, days)
        print(f"{pref}: {len(stations)} stations, {len(jobs)} requests, {len(rows)} values")
        all_stations += stations

    DATA.mkdir(exist_ok=True)
    with (DATA / "stations.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STATION_FIELDS, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(all_stations)
    write_geojson(all_stations, crnt)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(int(args[args.index("--days") + 1]) if "--days" in args else 1)
