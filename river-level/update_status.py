"""docs/status.json（地図ヘッダに出す取得状況）を更新する。

  python update_status.py fetched <days> <alert|manual>   取得して Drive に送った直後
  python update_status.py idle                           取得しなかった毎時ジョブの最後

取得が24時間以内に続いているあいだは同じ「取得期間」とみなし、since（開始時刻）を引き継ぐ。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PATH = Path(__file__).parent / "docs" / "status.json"
FMT = "%Y/%m/%d %H:%M"


def main() -> None:
    now = datetime.now()
    st = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}
    mode = sys.argv[1] if len(sys.argv) > 1 else "idle"
    if mode == "fetched":
        last = st.get("last_fetch")
        cont = last and now - datetime.strptime(last, FMT) < timedelta(hours=24)
        st.update({"active": True, "since": st.get("since") if cont and st.get("since") else now.strftime(FMT),
                   "last_fetch": now.strftime(FMT), "days": int(sys.argv[2]) if len(sys.argv) > 2 else None,
                   "trigger": sys.argv[3] if len(sys.argv) > 3 else "alert"})
    else:
        last = st.get("last_fetch")
        st["active"] = bool(last and now - datetime.strptime(last, FMT) < timedelta(hours=24))
    st["checked"] = now.strftime(FMT)
    PATH.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    print(st)


if __name__ == "__main__":
    main()
