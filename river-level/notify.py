"""氾濫開始水位／計画高水位（fld_stg）以上になった観測所が新たに出たら、1通だけメールを送る。

- 判定は docs/latest.geojson（最新値）と docs/peak.json（直近の最大水位）。通常の水位計・危機管理型とも対象。
  ジョブの実行が数時間空くことがあるので、走った時点で下がっていても直近48時間に超えていれば通知する
- docs/notified.json に「通知済みの観測所」を持ち、載っている観測所は再送しない
- 水位が氾濫危険水位（dng_stg。無ければ fld_stg - 0.3 m）を下回ったら通知済みから外す（また超えたら再通知）
- 送信は Apps Script（DRIVE_UPLOAD_URL）に {token, mail: {subject, body}} を POST。宛先はスクリプトプロパティ MAIL_TO。
  環境変数が無ければ送らずに表示だけ
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

DOCS = Path(__file__).parent / "docs"
NOTIFIED = DOCS / "notified.json"
MAP_URL = "https://tomokyuuu.github.io/scraping/"
RECENT_HOURS = 48  # 直近この時間内の最大水位が超えていれば、今は下がっていても通知する
FMT = "%Y/%m/%d %H:%M"
NL = "\n"


def station_url(p: dict) -> str:
    return (f"https://www.river.go.jp/kawabou/pc/tm?zm=15&ofcCd={p.get('ofc_cd', '')}"
            f"&itmkndCd={p.get('itmknd_cd', 4)}&obsCd={p.get('obs_cd', '')}")


def send_mail(subject: str, body: str) -> None:
    url, token = os.environ.get("DRIVE_UPLOAD_URL"), os.environ.get("DRIVE_TOKEN")
    if not url or not token:
        print("(DRIVE_UPLOAD_URL / DRIVE_TOKEN が無いので送信しない)" + NL + subject + NL + body)
        return
    payload = json.dumps({"token": token, "mail": {"subject": subject, "body": body}}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        print("mail:", r.read().decode("utf-8")[:200])


def recent_peak_over(pk: dict | None, thr: float, recent: datetime) -> bool:
    if not pk or pk.get("max") is None or pk["max"] < thr:
        return False
    try:
        return datetime.strptime(pk["at"], FMT) >= recent
    except (ValueError, KeyError):
        return False


def describe(p: dict) -> str:
    kind = "危機管理型" if p["kind"] == "swstg" else "水位計"
    pref = "石川" if p["pref"] == "ishikawa" else "富山"
    head = f"・{p['obs_nm']}（{pref}・{kind}）"
    if p["_past"]:
        pk = p["_peak"]
        now_txt = f"{p['stg']:.2f} m" if p.get("stg") is not None else "--"
        text = (f"最大 {pk['max']:.2f} m（{pk['at']}）／ 氾濫開始・計画高水位 {p['fld_stg']:.2f} m"
                f"　※すでに低下（現在 {now_txt}）")
    else:
        text = f"水位 {p['stg']:.2f} m ／ 氾濫開始・計画高水位 {p['fld_stg']:.2f} m（{p.get('obs_time')}）"
    return head + text + NL + "  " + station_url(p)


def main() -> None:
    geo = json.loads((DOCS / "latest.geojson").read_text(encoding="utf-8"))
    notified: dict[str, dict] = json.loads(NOTIFIED.read_text(encoding="utf-8")) if NOTIFIED.exists() else {}
    peak_path = DOCS / "peak.json"
    peaks = json.loads(peak_path.read_text(encoding="utf-8")).get("peaks", {}) if peak_path.exists() else {}
    now_dt = datetime.now()
    now = now_dt.strftime(FMT)
    recent = now_dt - timedelta(hours=RECENT_HOURS)
    new: list[dict] = []
    for f in geo["features"]:
        p = f["properties"]
        stg, fld = p.get("stg"), p.get("fld_stg")
        if fld is None:
            continue
        oid = p["obs_id"]
        valid = stg is not None and not p.get("stg_ccd")
        now_over = valid and stg >= fld
        # ジョブの実行間隔が空くことがあるので、今の値だけでなく直近の最大水位（peak.json）でも判定する
        pk = peaks.get(oid)
        peak_over = recent_peak_over(pk, fld, recent)
        if now_over or peak_over:
            if oid not in notified:
                notified[oid] = {"obs_nm": p["obs_nm"], "stg": stg,
                                 "since": (p.get("obs_time") or now) if now_over else pk["at"]}
                new.append({**p, "_past": not now_over, "_peak": pk})
        elif valid:
            clear = p.get("dng_stg") if p.get("dng_stg") is not None else fld - 0.3
            if oid in notified and stg < clear:
                del notified[oid]
    NOTIFIED.write_text(json.dumps(notified, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"flooding now/recent: {len(notified)}, new: {len(new)}")
    if not new:
        return
    new.sort(key=lambda q: (q["pref"], q["obs_nm"]))
    subject = f"【河川水位】氾濫開始水位を超過: {new[0]['obs_nm']}" + (f" ほか{len(new) - 1}件" if len(new) > 1 else "")
    body = NL.join([
        f"新たに氾濫開始水位／計画高水位を超えた観測所（{now} 判定）",
        "",
        NL.join(describe(p) for p in new),
        "",
        f"超過中または直近{RECENT_HOURS}時間に超過: {len(notified)} 地点",
        f"地図: {MAP_URL}",
        "",
        "※この観測所については落ち着くまで再送しません。別の観測所が超えたらまた1通送ります。",
        "※監視は数時間おきになることがあります（GitHub の定時実行の遅れ）。画像と水位は遡って保存されます。",
    ])
    send_mail(subject, body)


if __name__ == "__main__":
    main()
