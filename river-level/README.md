# river-level

石川県・富山県の河川水位（10分値）と潮位を、**大雨のときだけ**自動で取得して Google Drive に保存するプロジェクト。GitHub Actions で動く。

- 地図: https://tomokyuuu.github.io/scraping/ （**合言葉が必要**。研究用の私的ページで、合言葉なしでは地図も出ない。防災目的の閲覧は公式の川の防災情報へ誘導する）
- 保存先: Google Drive（Apps Script 経由）。合言葉を入れた地図の「保存先（Drive）」から開ける。Drive の URL はページのソースには含めない（Apps Script が合言葉と引き換えに返す）

## 考え方

各サイトが過去分を持っているので、常時ためる必要はない。

| ソース | 観測所 | 過去分の保持 | 解像度 |
|---|---|---|---|
| [川の防災情報](https://www.river.go.jp/)（国交省） | 石川 280・富山 218（国・県管理の水位計＋危機管理型） | **約7日** | 10分値 |
| [Toyama Smart City Square](https://tscs.city.toyama.lg.jp/map/list.aspx?panel_id=3)（富山市） | 22（市管理の小河川） | 約30日 | 10分値 |
| [気象庁 潮位観測](https://www.jma.go.jp/bosai/tidelevel/) | 9（富山・伏木富山・新湊・生地・金沢・七尾・輪島港・能登・珠洲） | 約20日 | 15秒値 → 10分値に間引き |

だから「増水を検知したら、**遡って7日分**取る」で、降り始める前からの10分値が揃う。

## 動き（リポジトリ直下の .github/workflows/fetch.yml）

このフォルダは `scraping` リポジトリの中の1プロジェクト。GitHub はワークフローをリポジトリ直下からしか読まないので、ワークフローだけ `scraping/.github/workflows/` にあり、`working-directory: river-level` で動く。

毎時、次を行う。

1. 最新値だけ取って地図を更新（軽い。Git にコミットするのは `docs/*.geojson` と観測所一覧だけ）
2. `check_alert.py`: 通常の水位計のどこかが**氾濫注意水位以上**なら
3. 3ソースとも直近7日分（川の防災情報は保持上限）の10分値を日別 CSV にして **Drive に上書き保存**。超過が続く間は毎時更新されるので、出水の前後が途切れなく残る

晴れが続く日は 1 だけで終わり、CSV は作らない（捨てるものも無い）。
人手で取りたいときは Actions タブ → river level → Run workflow で「何日前から」を指定する（気づいてから7日以内なら間に合う）。

判定の基準は Actions の Variables `ALERT_FIELD` で変えられる（`rsrv_stg`=水防団待機, `warn_stg`=氾濫注意（既定）, `spcl_warn_stg`=避難判断, `dng_stg`=氾濫危険）。危機管理型は晴天でも基準超えのまま止まっている地点があるので判定には使わない（データは取る）。

## 地図でできること

- 現在値（白○。氾濫危険以上で赤、氾濫開始/計画高水位以上で紫）、「期間最大で色分け」で取得期間の最大水位による色分け
- 「危なかった地点」: 取得期間中に氾濫注意以上になった地点の一覧（段階・最大値・時刻）
- 地点クリック → 「グラフ」: Drive に保存中の時系列（Apps Script 経由で読む）
- 「出水記録」「Drive台帳」: 出水ごとの記録（`docs/events.json`。期間・最大水位の観測所・氾濫注意以上／氾濫開始超えの地点数・カメラ枚数）と Drive の中身のツリー。棚卸のとき、どの日付がどの出水かをここで見る
- 「📷 カメラ」: 川の防災情報の河川カメラ 597 台の位置。クリックで現在画像

## 氾濫の通知メール（notify.py）

毎時の監視で、観測所が**新たに氾濫開始水位／計画高水位以上**になったら 1 通メールする（複数同時は 1 通にまとめる）。同じ観測所で超え続けていても再送せず、氾濫危険水位を下回ったら解除（再び超えたらまた 1 通）。通知済みは `docs/notified.json`。送信は Apps Script の MailApp、宛先はスクリプトプロパティ `MAIL_TO`（省略時は Apps Script の所有者）。

## カメラ画像の保存（fetch_camera.py）

無差別には撮らない。**氾濫開始水位／計画高水位以上**になった観測所（通常・危機管理型とも）について、500 m 以内のカメラ（最大2台）＋**同じ川のカメラ全部**を、**10分おき**（`.github/workflows/camera.yml`）に Drive の `camera/{カメラID}/{撮影時刻}.jpg` に保存する。氾濫していなければ数秒で終わる。
基準は Variables `CAM_FIELD`（`fld_stg` 既定 / `dng_stg` / `spcl_warn_stg` / `warn_stg`）、半径は `CAM_RADIUS_M`、同じ川を含めるかは `CAM_SAME_RIVER`（既定 1）。
**過去にも遡れる**: 川の防災情報は履歴画像 `cam.river.go.jp/cam/history/{YYYYMMDDHHmm}/{カメラID}.jpg` を約30日分持っている（簡易型 5分刻み、CCTV 10分刻み）。カメラが初めて対象になったとき、過去 `CAM_BACKFILL_HOURS`（既定 48）時間を遡って取り、日ごとの zip（`backfill_{日付}.zip`）で Drive に置く。近くのカメラは10分刻み、同じ川の他のカメラは `CAM_BACKFILL_RIVER_STEP`（既定 30）分刻み。
カメラ一覧は `data/cameras.csv`（`python fetch_camera.py --build` で作り直し）。観測所→カメラの対応表は `docs/station_cameras.json`（near=近く、river=同じ川）。
`data/camera_check.json` は 2026-10-22 に全カメラを目視確認した結果で、取得不可（28台）・真っ白/真っ黒・メンテ中・海岸・川が見えない（計37台）は候補から外す。曇り・葉で遮られる（8台）は残す。

## ファイル

```
fetch_river_level.py   川の防災情報 → data/{ishikawa,toyama}/YYYY/YYYY-MM-DD.csv, data/stations.csv, docs/latest.geojson
fetch_toyama_city.py   富山市 → data/toyama_city/YYYY/YYYY-MM-DD.csv, data/toyama_city/stations.csv, docs/latest_toyama_city.geojson
fetch_jma_tide.py      気象庁潮位 → data/jma_tide/YYYY/YYYY-MM-DD.csv, data/jma_tide/stations.csv, docs/latest_jma_tide.geojson
check_alert.py         増水判定 → docs/alert.json
peak.py                取得期間の最大水位 → docs/peak.json
fetch_camera.py        氾濫中の観測所近くのカメラ画像 → data/camera/, docs/camera_index.json
update_status.py       取得状況 → docs/status.json
series.py              グラフ用の時系列 JSON（data/series/）
upload_drive.py        data/ の日別 CSV を Drive に送る（同名は上書き）
apps-script/Code.gs    Drive 側の受け口（Web App）
docs/index.html        地図ページ（MapLibre + 地理院タイル）
desktop/make_shortcut.ps1  デスクトップに丸いアイコン「河川水位」を作る
../.github/workflows/fetch.yml  定期実行（リポジトリ直下）
```

日別 CSV は毎回まるごと書き直す（追記しない）ので、何度取り直しても重複しない。
列: 川の防災情報 `obs_time,kind(stg=水位計/swstg=危機管理型),obs_id,obs_nm,stg(m),stg_ccd(欠測コード 0=正常),stg_ovlvl`、富山市 `obs_time,obs_id,obs_nm,stg`、潮位 `obs_time,obs_id,obs_nm,tide_cm,departure_cm(偏差)`。

## 手で動かす

```
python fetch_river_level.py --days 6     直近7日（0 で最新値のみ）
python fetch_toyama_city.py --days 30
python fetch_jma_tide.py --days 20
python check_alert.py
DRIVE_UPLOAD_URL=... DRIVE_TOKEN=... python upload_drive.py
```

Python 3.10 以上、追加ライブラリ不要。

## 初回設定

1. **Drive**: 保存先フォルダを作る。[apps-script/Code.gs](apps-script/Code.gs) 冒頭の手順で Web App をデプロイし、スクリプトプロパティ `ROOT_FOLDER_ID`・`UPLOAD_TOKEN`・`VIEW_PASSWORD`（地図の合言葉）を入れる
2. **GitHub Secrets**（Settings → Secrets and variables → Actions）: `DRIVE_UPLOAD_URL`（Web App の URL）, `DRIVE_TOKEN`（`UPLOAD_TOKEN` と同じ値）
3. **GitHub Variables**: `DATA_URL` に Drive フォルダの URL（地図の「保存データ」リンク先）。任意で `ALERT_FIELD`
4. Settings → Actions → General → Workflow permissions を **Read and write**
5. Settings → Pages → Source を **GitHub Actions**（リポジトリは Public にする必要がある。Private だと無料プランでは Pages が使えない）
6. Actions → river level → Run workflow で一度動かして、Drive にファイルができるのを確認

Secrets が無いときは Drive に送らず、ログに「Drive には送らない」と出て終わる（地図の更新だけ動く）。
