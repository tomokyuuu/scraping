"""地図のグラフ用に、観測所ごとの時系列を等間隔の配列にまとめて JSON に書く。

出力 data/series/{src}.json:
  {"updated": "...", "t0": "2026/10/15 00:00", "step": 10,
   "series": {"<obs_id>": {"name": "...", "kind": "stg", "v": [0.81, null, ...]}}}
v は t0 から step 分ごとの値。無い時刻は null。Drive に置き、Apps Script の doGet が地点ごとに切り出して返す。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

SERIES_DIR = Path(__file__).parent / "data" / "series"
FMT = "%Y/%m/%d %H:%M"


def write_series(src: str, rows: list[dict], value_key: str, t0: datetime, t_end: datetime,
                 step_min: int = 10, name_key: str = "obs_nm", kind_key: str | None = "kind") -> None:
    n = int((t_end - t0).total_seconds() // (step_min * 60)) + 1
    if n <= 0:
        return
    series: dict[str, dict] = {}
    for r in rows:
        v = r.get(value_key)
        if v is None:
            continue
        try:
            t = datetime.strptime(r["obs_time"], FMT)
        except ValueError:
            continue
        i = int((t - t0).total_seconds() // (step_min * 60))
        if not (0 <= i < n):
            continue
        s = series.get(r["obs_id"])
        if s is None:
            s = series[r["obs_id"]] = {"name": r.get(name_key, ""), "kind": r.get(kind_key, "") if kind_key else src,
                                        "v": [None] * n}
        s["v"][i] = v
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    (SERIES_DIR / f"{src}.json").write_text(
        json.dumps({"updated": datetime.now().strftime(FMT), "t0": t0.strftime(FMT), "step": step_min, "series": series},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
