"""data/ 配下の日別 CSV を Google Drive に送る（Apps Script Web App 経由。apps-script/Code.gs を参照）。

環境変数:
  DRIVE_UPLOAD_URL  Apps Script Web App の URL（.../exec）
  DRIVE_TOKEN       スクリプトプロパティ UPLOAD_TOKEN と同じ値

使い方:
  python upload_drive.py                 data/ 配下の *.csv を全部送る（同名は上書き）
  python upload_drive.py --since 2026-10-19   ファイル名の日付がこの日以降のものだけ

Drive 側のフォルダ構成は data/ と同じ（ishikawa/2026/2026-10-20.csv など）。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def upload(url: str, token: str, rel: str, content: str | bytes, retries: int = 3) -> dict:
    payload = {"token": token, "path": rel}
    if isinstance(content, bytes):
        payload["content_b64"] = base64.b64encode(content).decode("ascii")
    else:
        payload["content"] = content
    body = json.dumps(payload).encode("utf-8")
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:  # Apps Script は 302 → 自動で追従
                res = json.loads(r.read().decode("utf-8"))
            if not res.get("ok"):
                raise RuntimeError(res.get("error", res))
            return res
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            print(f"retry {rel}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    raise RuntimeError("unreachable")


def main() -> None:
    url, token = os.environ.get("DRIVE_UPLOAD_URL"), os.environ.get("DRIVE_TOKEN")
    if not url or not token:
        print("DRIVE_UPLOAD_URL / DRIVE_TOKEN が無いので Drive には送らない")
        return
    args = sys.argv[1:]
    since = args[args.index("--since") + 1] if "--since" in args else ""
    files = sorted(p for p in DATA.rglob("*.csv") if p.name not in ("stations.csv", "cameras.csv") and p.stem >= since)
    files += sorted(DATA.glob("series/*.json"))  # 地図のグラフ用
    files += sorted(DATA.glob("camera/*/*.jpg")) + sorted(DATA.glob("camera/*/*.zip"))  # カメラ画像（送ったら消す）
    for p in files:
        rel = p.relative_to(DATA).as_posix()
        if p.suffix in (".jpg", ".zip"):
            res = upload(url, token, rel, p.read_bytes())
            p.unlink()
        else:
            res = upload(url, token, rel, p.read_text(encoding="utf-8"))
        print(f"uploaded {rel} ({p.stat().st_size // 1024 if p.exists() else '-'} KB) -> {res.get('id', '')}")
    for p in DATA.rglob("stations.csv"):
        rel = p.relative_to(DATA).as_posix()
        upload(url, token, rel, p.read_text(encoding="utf-8"))
        print(f"uploaded {rel}")
    print(f"done: {len(files)} files")


if __name__ == "__main__":
    main()
