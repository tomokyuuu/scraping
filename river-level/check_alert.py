"""docs/latest.geojson を見て、基準水位を超えている観測所があるか調べ、docs/alert.json に書く。

GitHub Actions の毎時ジョブが、本格的な取得（直近1週間の10分値 → Drive）を走らせるかどうかの判定に使う。
終了コード 0 = 超過あり、1 = なし。

判定は通常の水位計 (stg) の水位と基準水位の比較で行う（既定 warn_stg = 氾濫注意水位。環境変数 ALERT_FIELD で変更）。
サイトの stg_ovlvl は欠測でも 30 が入るなど意味が種別で違うので使わない。
危機管理型は晴天時でも基準超えのまま止まっている地点があるので判定には使わない（取得はする）。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ALERT_FIELD = os.environ.get("ALERT_FIELD", "warn_stg")  # rsrv_stg / warn_stg / spcl_warn_stg / dng_stg
DOCS = Path(__file__).parent / "docs"


def over(p: dict) -> bool:
    stg = p.get("stg")
    if stg is None or p.get("stg_ccd") or p["kind"] != "stg":
        return False
    thr = p.get(ALERT_FIELD)
    return thr is not None and stg >= thr


def main() -> int:
    d = json.loads((DOCS / "latest.geojson").read_text(encoding="utf-8"))
    hits = [p for p in (f["properties"] for f in d["features"]) if over(p)]
    for p in hits:
        print(f"ALERT {p['pref']} {p['obs_nm']} stg={p['stg']} {ALERT_FIELD}={p[ALERT_FIELD]} ({p.get('obs_time')})")
    print(f"{len(hits)} stations over threshold ({ALERT_FIELD})")
    (DOCS / "alert.json").write_text(json.dumps({
        "checked": datetime.now().strftime("%Y/%m/%d %H:%M"), "field": ALERT_FIELD,
        "over": [{"kind": p["kind"], "obs_id": p["obs_id"], "obs_nm": p["obs_nm"], "pref": p["pref"],
                  "stg": p["stg"], "thr": p[ALERT_FIELD], "obs_time": p.get("obs_time")} for p in hits],
    }, ensure_ascii=False), encoding="utf-8")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
