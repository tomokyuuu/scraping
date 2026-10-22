"""増水している観測所の近くの河川カメラ画像を保存する（川の防災情報の簡易型河川監視カメラ・CCTV）。

無差別には撮らない。対象は docs/latest.geojson で **氾濫開始水位／計画高水位（fld_stg）以上** になっている観測所
（通常の水位計・危機管理型とも。氾濫注意・氾濫危険程度では撮らない）から CAM_RADIUS_M（既定 500 m）以内にあるカメラ。
1観測所につき近い順に最大 2 台。基準は環境変数 CAM_FIELD で変えられる（fld_stg / dng_stg / spcl_warn_stg / warn_stg）。

カメラ一覧（座標・URL）は data/cameras.csv に置く（無ければ作る。--build で作り直す）。
  一覧  : /kawabou/file/files/obslist/obs/twnlist/{twnCd}.json の scam / cctv
  詳細  : /kawabou/file/files/master/obs/scam/{scamId}.json（lat/lon, currProvUrl, currDateProvUrl）
画像  : https://cam.river.go.jp/cam/now/{scamId}.jpg  時刻: 同 .json の get_time（約10分ごと更新）

出力:
  data/camera/{scamId}/{YYYYMMDD_HHMM}.jpg   画像（同じ get_time のものは撮り直さない）
  docs/camera_index.json                     どのカメラを何枚撮ったか（地図のポップアップ用）
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "https://www.river.go.jp/kawabou/file"
CAM = "https://cam.river.go.jp/cam/now/"
UA = "Mozilla/5.0 (river-level logger; github actions)"
PREFS = {"1701": "ishikawa", "1601": "toyama"}
RADIUS = float(os.environ.get("CAM_RADIUS_M", "500"))
CAM_FIELD = os.environ.get("CAM_FIELD", "fld_stg")
MAX_PER_STATION = 2
ROOT = Path(__file__).parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
CAMERAS = DATA / "cameras.csv"
INDEX = DOCS / "camera_index.json"
CAM_FIELDS = ["scam_id", "name", "kind", "pref", "twn_cd", "rvr_cd", "lat", "lon", "img_url", "time_url"]


def get(url: str, retries: int = 3) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == retries - 1:
                raise
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"retry {url}: {e}", file=sys.stderr)
        time.sleep(2 * (i + 1))
    return None


def get_json(path: str) -> dict | None:
    b = get(BASE + path)
    if not b or b.lstrip().startswith(b"<"):
        return None
    return json.loads(b.decode("utf-8"))


def build_cameras() -> list[dict]:
    cams: list[dict] = []
    for pref_cd, pref in PREFS.items():
        for t in get_json(f"/files/obslist/idx/pref/twn/{pref_cd}.json")["twnInfo"]:
            lst = get_json(f"/files/obslist/obs/twnlist/{t['twnCd']}.json") or {}
            for kind in ("scam", "cctv"):
                for c in lst.get("obsList", {}).get(kind, []):
                    m = get_json(f"/files/master/obs/scam/{c['scamId']}.json")
                    o = (m or {}).get("obsInfo") or {}
                    if not o.get("lat") or not o.get("currProvUrl"):
                        continue
                    cams.append({"scam_id": c["scamId"], "name": c["name"], "kind": kind, "pref": pref,
                                 "twn_cd": t["twnCd"], "rvr_cd": c.get("rvrCd"), "lat": o["lat"], "lon": o["lon"],
                                 "img_url": o["currProvUrl"], "time_url": o.get("currDateProvUrl") or ""})
    CAMERAS.parent.mkdir(exist_ok=True)
    with CAMERAS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAM_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(cams)
    # 地図のカメラ位置表示用
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
              "properties": {k: c[k] for k in ("scam_id", "name", "kind", "pref", "img_url")}} for c in cams]
    (DOCS / "cameras.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                     ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"cameras: {len(cams)}")
    return cams


def load_cameras() -> list[dict]:
    if not CAMERAS.exists():
        return build_cameras()
    with CAMERAS.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["lat"], r["lon"] = float(r["lat"]), float(r["lon"])
    return rows


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    k = math.cos(math.radians(lat1))
    return math.hypot((lat2 - lat1) * 111_000, (lon2 - lon1) * 111_000 * k)


def target_stations() -> list[dict]:
    geo = json.loads((DOCS / "latest.geojson").read_text(encoding="utf-8"))
    out = []
    for f in geo["features"]:
        p = f["properties"]
        stg, thr = p.get("stg"), p.get(CAM_FIELD)
        if stg is not None and not p.get("stg_ccd") and thr is not None and stg >= thr:
            out.append({**p, "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]})
    return out


def main(build: bool) -> None:
    cams = build_cameras() if build else load_cameras()
    stations = target_stations()
    picked: dict[str, dict] = {}
    for s in stations:
        near = sorted(((dist_m(s["lat"], s["lon"], c["lat"], c["lon"]), c) for c in cams), key=lambda x: x[0])
        for d, c in near[:MAX_PER_STATION]:
            if d <= RADIUS:
                e = picked.setdefault(str(c["scam_id"]), {**c, "stations": []})
                e["stations"].append({"obs_id": s["obs_id"], "obs_nm": s["obs_nm"], "dist_m": round(d)})
    print(f"camera: {len(stations)} target stations -> {len(picked)} cameras")

    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    saved = 0
    for sid, c in picked.items():
        tinfo = {}
        if c.get("time_url"):
            b = get(c["time_url"])
            if b:
                try:
                    tinfo = json.loads(b.decode("utf-8"))
                except ValueError:
                    tinfo = {}
        get_time = (tinfo.get("get_time") or datetime.now().isoformat())[:16]  # "2026-10-22T09:25"
        stamp = get_time.replace("-", "").replace("T", "_").replace(":", "")
        entry = index.setdefault(sid, {"name": c["name"], "kind": c["kind"], "lat": c["lat"], "lon": c["lon"],
                                       "img_url": c["img_url"], "count": 0, "shots": []})
        entry["stations"] = c["stations"]
        if entry.get("last_time") == get_time:
            continue  # 画像が更新されていない
        img = get(c["img_url"])
        if not img or len(img) < 1000:
            continue
        path = DATA / "camera" / sid / f"{stamp}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(img)
        entry["last_time"] = get_time
        entry["count"] = entry.get("count", 0) + 1
        entry["shots"] = (entry.get("shots") or [])[-47:] + [stamp]  # 直近48枚ぶんの名前だけ持つ
        saved += 1
    index["_updated"] = datetime.now().strftime("%Y/%m/%d %H:%M")
    INDEX.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"camera: {saved} images saved")


if __name__ == "__main__":
    main("--build" in sys.argv[1:])
