"""取得期間中の各観測所の最大水位を docs/peak.json にまとめる（「あとで、どこが危なかったか」を地図で見るため）。

data/series/*.json（取得したばかりの時系列）と docs/latest.geojson（基準水位）から作る。
  {"period": {"from": "...", "to": "..."}, "updated": "...",
   "peaks": {"<obs_id>": {"max": 2.15, "at": "2026/10/21 17:40", "lv": 2, "src": "ishikawa"}}}
lv: 0=基準未満 1=水防団待機 2=氾濫注意 3=避難判断 4=氾濫危険 5=氾濫開始/計画高水位（危機管理型は 4,5 のみ）。基準が無い地点は null
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
SERIES = ROOT / "data" / "series"
DOCS = ROOT / "docs"
FMT = "%Y/%m/%d %H:%M"


def level(p: dict, v: float) -> int | None:
    if p.get("kind") == "swstg":
        thr = [None, None, None, p.get("dng_stg"), p.get("fld_stg")]
    else:
        thr = [p.get("rsrv_stg"), p.get("warn_stg"), p.get("spcl_warn_stg"), p.get("dng_stg"), p.get("fld_stg")]
    if all(t is None for t in thr):
        return None
    lv = 0
    for i, t in enumerate(thr):
        if t is not None and v >= t:
            lv = i + 1
    return lv


def main() -> None:
    props = {f["properties"]["obs_id"]: f["properties"]
             for f in json.loads((DOCS / "latest.geojson").read_text(encoding="utf-8"))["features"]}
    peaks: dict[str, dict] = {}
    t_from, t_to = None, None
    for path in sorted(SERIES.glob("*.json")):
        src = path.stem
        if src == "jma_tide":
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        t0 = datetime.strptime(d["t0"], FMT)
        step = int(d["step"])
        for oid, s in d["series"].items():
            best = None
            for i, v in enumerate(s["v"]):
                if v is not None and (best is None or v > best[0]):
                    best = (v, i)
            if best is None:
                continue
            at = t0 + timedelta(minutes=best[1] * step)
            p = props.get(oid, {})
            peaks[oid] = {"max": best[0], "at": at.strftime(FMT), "src": src,
                          "lv": level(p, best[0]) if src in ("ishikawa", "toyama") else None}
            t_from = t0 if t_from is None or t0 < t_from else t_from
            t_end = t0 + timedelta(minutes=(len(s["v"]) - 1) * step)
            t_to = t_end if t_to is None or t_end > t_to else t_to
    out = {"updated": datetime.now().strftime(FMT),
           "period": {"from": t_from.strftime(FMT) if t_from else None, "to": t_to.strftime(FMT) if t_to else None},
           "peaks": peaks}
    (DOCS / "peak.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(1 for p in peaks.values() if (p["lv"] or 0) >= 2)
    print(f"peak: {len(peaks)} stations, {n} reached 氾濫注意 or above, period {out['period']}")


if __name__ == "__main__":
    main()
