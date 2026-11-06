"""増水している観測所の近くの河川カメラ画像を保存する（川の防災情報の簡易型河川監視カメラ・CCTV）。

無差別には撮らない。対象は docs/latest.geojson で **氾濫開始水位／計画高水位（fld_stg）以上** になっている観測所
（通常の水位計・危機管理型とも。氾濫注意・氾濫危険程度では撮らない）から CAM_RADIUS_M（既定 500 m）以内にあるカメラ。
1観測所につき近い順に最大 2 台。基準は環境変数 CAM_FIELD で変えられる（fld_stg / dng_stg / spcl_warn_stg / warn_stg）。
同じ河川コードのカメラ全部も対象に加える（既定。CAM_SAME_RIVER=0 で近くの2台だけにする）。
data/camera_check.json（目視確認の結果）で「取得不可・メンテ・海岸・川が見えない」とされたカメラは候補から外す。

カメラ一覧（座標・URL）は data/cameras.csv に置く（無ければ作る。--build で作り直す）。
  一覧  : /kawabou/file/files/obslist/obs/twnlist/{twnCd}.json の scam / cctv
  詳細  : /kawabou/file/files/master/obs/scam/{scamId}.json（lat/lon, currProvUrl, currDateProvUrl）
画像  : https://cam.river.go.jp/cam/now/{scamId}.jpg  時刻: 同 .json の get_time（約10分ごと更新）

画像はリアルタイムではなく履歴 https://cam.river.go.jp/cam/history/{YYYYMMDDHHmm}/{scamId}.jpg（約30日保持）から取る。
初回は過去 CAM_BACKFILL_HOURS 時間（既定48）、以後は実行のたびに「前回取ったところから今まで」を埋めるので、
ジョブの実行間隔が何時間空いても画像は途切れない（GitHub の定時実行は数時間遅れることがある）。
近くのカメラは10分刻み、同じ川の他は CAM_BACKFILL_RIVER_STEP 分刻み（既定30）。日ごとの zip（hist_{YYYYMMDD}_{実行時刻}.zip）にまとめる。
対象は「今 超えている」か「直近 CAM_BACKFILL_HOURS 時間の最大水位が超えていた」観測所（走った時点で下がっていても拾う）。

出力:
  data/camera/{scamId}/hist_{YYYYMMDD}_{HHMM}.zip  画像（中身は {YYYYMMDD_HHMM}.jpg）
  docs/camera_index.json                     どのカメラを何枚撮ったか（地図のポップアップ用）
  docs/station_cameras.json                  観測所 → 近くのカメラ の対応表（--build で作り直し。地図にも使う）
"""
from __future__ import annotations

import csv
import json
import math
import re
import os
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

BASE = "https://www.river.go.jp/kawabou/file"
CAM = "https://cam.river.go.jp/cam/now/"
CAM_HISTORY = "https://cam.river.go.jp/cam/history/"
BACKFILL_HOURS = int(os.environ.get("CAM_BACKFILL_HOURS", "48"))   # 初めて対象になったとき何時間遡るか
BACKFILL_RIVER_STEP = int(os.environ.get("CAM_BACKFILL_RIVER_STEP", "30"))  # 同じ川の他のカメラの刻み（分）
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


def river_name(s: str) -> str:
    """名前から川の名前を取り出す（例: "親司川 広上"→"親司川", "羽咋土木　子浦川　吉野屋橋"→"子浦川", "日用川（ほうえい橋）"→"日用川"）。"""
    m = re.findall(r"[^\s　（()]+?(?:川|潟|湖|放水路|承水路)", s)
    return m[0] if m else ""


def camera_status() -> tuple[dict[str, str], set[str]]:
    """data/camera_check.json（目視確認の結果）。戻り値は (カメラID→状態, 候補から外す状態の集合)。"""
    path = DATA / "camera_check.json"
    if not path.exists():
        return {}, set()
    d = json.loads(path.read_text(encoding="utf-8"))
    return d.get("status", {}), set(d.get("exclude", []))


def build_mapping(cams: list[dict]) -> dict[str, dict]:
    """観測所 → カメラ の対応表を docs/station_cameras.json に書く。
      near : RADIUS 以内で近い順に MAX_PER_STATION 台（取得不可・海岸などは除く）
      river: 同じ河川コードのカメラ全部（CAM_SAME_RIVER=1 のときだけ取得対象に加える）
    地図のポップアップ（近くのカメラ／なし）と、増水時のカメラ取得に使う。"""
    geo = json.loads((DOCS / "latest.geojson").read_text(encoding="utf-8"))
    status, exclude = camera_status()
    usable = [c for c in cams if status.get(str(c["scam_id"])) not in exclude]
    mapping: dict[str, dict] = {}
    for f in geo["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        near = sorted(((dist_m(lat, lon, c["lat"], c["lon"]), c) for c in usable), key=lambda x: x[0])
        pack = lambda c, d: {"scam_id": str(c["scam_id"]), "name": c["name"], "kind": c["kind"],  # noqa: E731
                             "dist_m": round(d), "img_url": c["img_url"], "status": status.get(str(c["scam_id"]), "ok")}
        # 同じ川: 河川コードが一致（通常の水位計）か、川の名前が一致（危機管理型はコード体系が違うので名前で）
        rn = river_name(p.get("obs_nm", ""))
        river = [pack(c, dist_m(lat, lon, c["lat"], c["lon"])) for c in usable
                 if (p.get("rvr_cd") and str(c.get("rvr_cd") or "") == str(p["rvr_cd"]))
                 or (rn and river_name(c["name"]) == rn)]
        mapping[p["obs_id"]] = {"near": [pack(c, d) for d, c in near[:MAX_PER_STATION] if d <= RADIUS],
                                "river": sorted(river, key=lambda x: x["dist_m"])}
    (DOCS / "station_cameras.json").write_text(json.dumps(mapping, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(1 for v in mapping.values() if v["near"])
    print(f"station->camera: {n} / {len(mapping)} stations have a usable camera within {RADIUS:.0f} m "
          f"({len(cams) - len(usable)} cameras excluded by check)")
    return mapping


def load_mapping(cams: list[dict]) -> dict[str, dict]:
    path = DOCS / "station_cameras.json"
    if path.exists():
        m = json.loads(path.read_text(encoding="utf-8"))
        if m and isinstance(next(iter(m.values())), dict):
            return m
    return build_mapping(cams)


def target_stations() -> list[dict]:
    """カメラを撮る対象の観測所。今 CAM_FIELD 以上のもの、または直近 BACKFILL_HOURS 時間の最大水位が超えていたもの
    （ジョブの実行間隔が空いて、走った時点ではもう水位が下がっている場合の見逃し防止。peak.json を使う）。"""
    geo = json.loads((DOCS / "latest.geojson").read_text(encoding="utf-8"))
    peak_path = DOCS / "peak.json"
    peaks = json.loads(peak_path.read_text(encoding="utf-8")).get("peaks", {}) if peak_path.exists() else {}
    recent = datetime.now() - timedelta(hours=BACKFILL_HOURS)
    out = []
    for f in geo["features"]:
        p = f["properties"]
        stg, thr = p.get("stg"), p.get(CAM_FIELD)
        if thr is None:
            continue
        now_over = stg is not None and not p.get("stg_ccd") and stg >= thr
        pk = peaks.get(p["obs_id"])
        peak_over = False
        if pk and pk.get("max") is not None and pk["max"] >= thr:
            try:
                peak_over = datetime.strptime(pk["at"], "%Y/%m/%d %H:%M") >= recent
            except (ValueError, KeyError):
                peak_over = False
        if now_over or peak_over:
            out.append({**p, "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]})
    return out


def fill_history(sid: str, c: dict, step_min: int, since: datetime | None) -> tuple[int, datetime]:
    """履歴画像を「前回取ったところ（since）から今まで」埋める。初回は過去 BACKFILL_HOURS 時間。
    ジョブの実行間隔が何時間空いても、step_min 刻みの画像が途切れなく揃う。
    履歴: https://cam.river.go.jp/cam/history/{YYYYMMDDHHmm}/{scamId}.jpg（約30日保持。簡易型は5分、CCTV は10分刻み）
    戻り値は (取れた枚数, ここまで取った時刻)。zip は実行ごとに別名（Drive 側は同名を上書きしないため）。"""
    now = datetime.now().replace(second=0, microsecond=0)
    end = now - timedelta(minutes=now.minute % 10)
    oldest = end - timedelta(hours=BACKFILL_HOURS)
    start = max(since, oldest) if since else oldest
    out_dir = DATA / "camera" / sid
    out_dir.mkdir(parents=True, exist_ok=True)
    zips: dict[str, zipfile.ZipFile] = {}
    n = 0
    t = start
    last_ok = None
    # 履歴のファイル名は現在画像と同じ（簡易型は {scamId}.jpg、国の CCTV は cctv_xxx.jpg）
    fname = c["img_url"].rsplit("/", 1)[-1]
    while t < end:
        t += timedelta(minutes=step_min)
        img = get(f"{CAM_HISTORY}{t:%Y%m%d%H%M}/{fname}")
        if img and len(img) >= 1000 and img[:2] == bytes([0xFF, 0xD8]):  # JPEG のみ（取得不可のときは PNG の定型画像が返る）
            last_ok = t
            day = t.strftime("%Y%m%d")
            if day not in zips:
                zips[day] = zipfile.ZipFile(out_dir / f"hist_{day}_{now:%H%M}.zip", "a", zipfile.ZIP_STORED)
            zips[day].writestr(f"{t:%Y%m%d_%H%M}.jpg", img)
            n += 1
    for z in zips.values():
        z.close()
    print(f"camera {sid} {c['name']}: {n} images ({start:%m/%d %H:%M} -> {end:%m/%d %H:%M}, {step_min}min step)")
    # 最新の枠はまだ履歴に出ていないことがあるので、「最後に取れた時刻」までを取得済みとする。
    # 1枚も取れないカメラは2時間ぶんだけ次回やり直す（毎回48時間を取り直さないため）
    floor = end - timedelta(hours=2)
    until = max(last_ok, floor) if last_ok else max(start, floor)
    return n, min(until, end)


def main(build: bool) -> None:
    cams = build_cameras() if build else load_cameras()
    mapping = build_mapping(cams) if build else load_mapping(cams)
    by_id = {str(c["scam_id"]): c for c in cams}
    stations = target_stations()
    picked: dict[str, dict] = {}
    same_river = os.environ.get("CAM_SAME_RIVER", "1") == "1"
    for s in stations:
        entry = mapping.get(s["obs_id"], {"near": [], "river": []})
        targets = entry["near"] + (entry["river"] if same_river else [])
        for m in targets:
            c = by_id.get(m["scam_id"])
            if not c:
                continue
            e = picked.setdefault(m["scam_id"], {**c, "stations": [], "near": False})
            if not any(x["obs_id"] == s["obs_id"] for x in e["stations"]):  # near と river の両方に載ることがある
                e["stations"].append({"obs_id": s["obs_id"], "obs_nm": s["obs_nm"], "dist_m": m["dist_m"]})
            e["near"] = e["near"] or m in entry["near"]
    print(f"camera: {len(stations)} target stations -> {len(picked)} cameras")

    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    saved = 0
    for sid, c in picked.items():
        entry = index.setdefault(sid, {"name": c["name"], "kind": c["kind"], "lat": c["lat"], "lon": c["lon"],
                                       "img_url": c["img_url"], "count": 0})
        entry["stations"] = c["stations"]
        since = None
        if entry.get("covered_until"):
            try:
                since = datetime.strptime(entry["covered_until"], "%Y/%m/%d %H:%M")
            except ValueError:
                since = None
        if not entry.get("backfilled"):
            entry["backfilled"] = datetime.now().strftime("%Y/%m/%d %H:%M")  # この出水で最初に取った時刻（出水記録用）
        n, until = fill_history(sid, c, 10 if c["near"] else BACKFILL_RIVER_STEP, since)
        entry["covered_until"] = until.strftime("%Y/%m/%d %H:%M")
        entry["last_time"] = entry["covered_until"]
        entry["count"] = (entry.get("count") or 0) + n
        saved += n
    index["_updated"] = datetime.now().strftime("%Y/%m/%d %H:%M")
    INDEX.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"camera: {saved} images saved")


if __name__ == "__main__":
    main("--build" in sys.argv[1:])
