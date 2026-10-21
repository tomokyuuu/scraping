"""docs/latest.geojson を見て、基準水位を超えている観測所があるか調べる。

GitHub Actions の毎時ジョブが、本格的な取得（直近1週間の10分値 → Drive）を走らせるかどうかの判定に使う。
終了コード 0 = 超過あり、1 = なし。超過した観測所名を表示する。

判定は通常の水位計 (stg) の水位と基準水位の比較で行う（既定 warn_stg = 氾濫注意水位）。
サイトの stg_ovlvl は欠測でも 30 が入るなど意味が種別で違うので使わない。
危機管理型は晴天時でも基準超えのまま止まっている地点があるので判定には使わない（取得はする）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ALERT_FIELD = os.environ.get("ALERT_FIELD", "warn_stg")  # rsrv_stg / warn_stg / spcl_warn_stg / dng_stg


def over(p: dict) -> bool:
    stg = p.get("stg")
    if stg is None or p.get("stg_ccd"):
        return False
    if p["kind"] != "stg":
        # 危機管理型は晴天時でも基準超えのまま止まっている地点が複数あり、判定には使えない
        return False
    thr = p.get(ALERT_FIELD)
    return thr is not None and stg >= thr


def main() -> int:
    d = json.loads((Path(__file__).parent / "docs" / "latest.geojson").read_text(encoding="utf-8"))
    hits = [p for p in (f["properties"] for f in d["features"]) if over(p)]
    for p in hits:
        print(f"ALERT {p['pref']} {p['kind']} {p['obs_nm']} stg={p['stg']} ({p.get('obs_time')})")
    print(f"{len(hits)} stations over threshold ({ALERT_FIELD})")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
