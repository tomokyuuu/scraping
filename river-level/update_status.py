"""docs/status.json（地図ヘッダに出す取得状況）と docs/events.json（出水ごとの記録）を更新する。

  python update_status.py fetched <days> <alert|manual>   取得して Drive に送った直後
  python update_status.py idle                           取得しなかった毎時ジョブの最後

取得が24時間以内に続いているあいだは同じ「取得期間（＝1つの出水）」とみなし、since（開始時刻）を引き継ぐ。
events.json には出水ごとに 開始・終了・最大水位の観測所・氾濫注意以上の地点数・氾濫開始超えの地点数・カメラ画像枚数 を残す
（棚卸のとき、Drive のどの日付がどの出水かを見るため）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

DOCS = Path(__file__).parent / "docs"
STATUS = DOCS / "status.json"
EVENTS = DOCS / "events.json"
FMT = "%Y/%m/%d %H:%M"
LV_NAME = ["基準未満", "水防団待機", "氾濫注意", "避難判断", "氾濫危険", "氾濫開始/計画高水位"]


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except ValueError:
        return default


def summarize(since: str) -> dict:
    """peak.json / camera_index.json / latest.geojson から、この出水の要約を作る。"""
    peak = load(DOCS / "peak.json", {})
    geo = load(DOCS / "latest.geojson", {"features": []})
    names = {f["properties"]["obs_id"]: f["properties"] for f in geo["features"]}
    peaks = [(oid, p) for oid, p in peak.get("peaks", {}).items() if p.get("lv") is not None]
    top = max(peaks, key=lambda x: (x[1]["lv"], x[1]["max"]), default=None)
    cams = load(DOCS / "camera_index.json", {})
    cam_list = [(sid, c) for sid, c in cams.items() if not sid.startswith("_") and (c.get("count") or c.get("backfill_images"))]
    # この出水で撮ったカメラ: backfilled（初回取得）が since 以降のもの
    cam_list = [(sid, c) for sid, c in cam_list if (c.get("backfilled") or "") >= since]
    return {
        "max_station": None if not top else {
            "obs_id": top[0], "obs_nm": names.get(top[0], {}).get("obs_nm", ""),
            "pref": names.get(top[0], {}).get("pref", ""), "max": top[1]["max"], "at": top[1]["at"],
            "lv": top[1]["lv"], "lv_name": LV_NAME[top[1]["lv"]]},
        "over_warn": sum(1 for _, p in peaks if p["lv"] >= 2),
        "over_danger": sum(1 for _, p in peaks if p["lv"] >= 4),
        "flooded": sum(1 for _, p in peaks if p["lv"] >= 5),
        "flooded_names": [names.get(oid, {}).get("obs_nm", oid) for oid, p in peaks if p["lv"] >= 5][:20],
        "cameras": len(cam_list),
        "camera_images": sum((c.get("count") or 0) + (c.get("backfill_images") or 0) for _, c in cam_list),
        "period": peak.get("period"),
    }


def main() -> None:
    now = datetime.now()
    st = load(STATUS, {})
    events = load(EVENTS, [])
    mode = sys.argv[1] if len(sys.argv) > 1 else "idle"
    last = st.get("last_fetch")
    cont = bool(last and now - datetime.strptime(last, FMT) < timedelta(hours=24))

    if mode == "fetched":
        since = st.get("since") if cont and st.get("since") else now.strftime(FMT)
        st.update({"active": True, "since": since, "last_fetch": now.strftime(FMT),
                   "days": int(sys.argv[2]) if len(sys.argv) > 2 else None,
                   "trigger": sys.argv[3] if len(sys.argv) > 3 else "alert"})
        # 出水の記録を作る／更新する（since が同じものが同じ出水）
        ev = next((e for e in events if e["since"] == since), None)
        if ev is None:
            ev = {"since": since, "trigger": st["trigger"]}
            events.append(ev)
        ev.update({"until": None, "last_fetch": st["last_fetch"], **summarize(since)})
    else:
        st["active"] = cont
        if not cont and st.get("since"):
            ev = next((e for e in events if e["since"] == st["since"]), None)
            if ev and ev.get("until") is None:
                ev["until"] = last  # 最後に取得した時刻を終了とする
    st["checked"] = now.strftime(FMT)
    STATUS.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    EVENTS.write_text(json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")
    print(st)
    if events:
        e = events[-1]
        print(f"event: {e['since']} - {e.get('until') or '継続中'} | 最大 {e.get('max_station')} | 氾濫注意以上 {e.get('over_warn')} "
              f"| 氾濫開始超え {e.get('flooded')} | カメラ {e.get('cameras')} 台 {e.get('camera_images')} 枚")


if __name__ == "__main__":
    main()
