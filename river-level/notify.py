"""氾濫開始水位／計画高水位（fld_stg）以上になった観測所が新たに出たら、1通だけメールを送る。

- 判定は docs/latest.geojson（毎時の最新値）。通常の水位計・危機管理型とも対象
- docs/notified.json に「通知済みの観測所」を持ち、載っている観測所は再送しない
- 水位が氾濫危険水位（dng_stg。無ければ fld_stg - 0.3 m）を下回ったら通知済みから外す（また超えたら再通知）
- 送信は Apps Script（DRIVE_UPLOAD_URL）に {token, mail: {subject, body}} を POST。宛先はスクリプトプロパティ MAIL_TO
  （無ければ Apps Script の所有者）。環境変数が無ければ送らずに表示だけ
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

DOCS = Path(__file__).parent / "docs"
NOTIFIED = DOCS / "notified.json"
MAP_URL = "https://tomokyuuu.github.io/scraping/"


def station_url(p: dict) -> str:
    return (f"https://www.river.go.jp/kawabou/pc/tm?zm=15&ofcCd={p.get('ofc_cd', '')}"
            f"&itmkndCd={p.get('itmknd_cd', 4)}&obsCd={p.get('obs_cd', '')}")


def send_mail(subject: str, body: str) -> None:
    url, token = os.environ.get("DRIVE_UPLOAD_URL"), os.environ.get("DRIVE_TOKEN")
    if not url or not token:
        print("(DRIVE_UPLOAD_URL / DRIVE_TOKEN が無いので送信しない)\n" + subject + "\n" + body)
        return
    req = urllib.request.Request(url, data=json.dumps({"token": token, "mail": {"subject": subject, "body": body}}).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        print("mail:", r.read().decode("utf-8")[:200])


def main() -> None:
    geo = json.loads((DOCS / "latest.geojson").read_text(encoding="utf-8"))
    notified: dict[str, dict] = json.loads(NOTIFIED.read_text(encoding="utf-8")) if NOTIFIED.exists() else {}
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    new: list[dict] = []
    for f in geo["features"]:
        p = f["properties"]
        stg, fld = p.get("stg"), p.get("fld_stg")
        if stg is None or p.get("stg_ccd") or fld is None:
            continue
        oid = p["obs_id"]
        if stg >= fld:
            if oid not in notified:
                notified[oid] = {"obs_nm": p["obs_nm"], "since": p.get("obs_time") or now, "stg": stg}
                new.append(p)
        else:
            clear = p.get("dng_stg") if p.get("dng_stg") is not None else fld - 0.3
            if oid in notified and stg < clear:
                del notified[oid]
    NOTIFIED.write_text(json.dumps(notified, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"flooding now: {len(notified)}, new: {len(new)}")
    if not new:
        return
    lines = []
    for p in sorted(new, key=lambda q: (q["pref"], q["obs_nm"])):
        kind = "危機管理型" if p["kind"] == "swstg" else "水位計"
        lines.append(f"・{p['obs_nm']}（{'石川' if p['pref'] == 'ishikawa' else '富山'}・{kind}）"
                     f" 水位 {p['stg']:.2f} m ／ 氾濫開始・計画高水位 {p['fld_stg']:.2f} m（{p.get('obs_time')}）\n  {station_url(p)}")
    subject = f"【河川水位】氾濫開始水位を超過: {new[0]['obs_nm']}" + (f" ほか{len(new) - 1}件" if len(new) > 1 else "")
    body = (f"新たに氾濫開始水位／計画高水位を超えた観測所（{now} 判定）\n\n" + "\n".join(lines) +
            f"\n\n現在超過中: {len(notified)} 地点\n地図: {MAP_URL}\n\n"
            "※この観測所については落ち着くまで再送しません。別の観測所が超えたらまた1通送ります。")
    send_mail(subject, body)


if __name__ == "__main__":
    main()
