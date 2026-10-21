# Apps Script を clasp で push して、既存のウェブアプリ デプロイを新バージョンに差し替える（URL は変わらない）。
#
# 初回だけ（9zemicontact@gmail.com で）:
#   1. https://script.google.com/home/usersettings で「Google Apps Script API」をオン
#   2. clasp login   （clasp 3 系。npm i -g @google/clasp。ブラウザが開くのでログイン）
#   3. .clasp.json に scriptId を書く（Apps Script エディタ → プロジェクトの設定 → スクリプト ID）
#
# 以後:  powershell -ExecutionPolicy Bypass -File deploy.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$deploymentId = "AKfycbz45llyadCop21B1jEulhERWJw13LyrJMVpZvgzt5v26xK5uqBaE-QWsibhmldYyAS5"
clasp push -f
if ($LASTEXITCODE -ne 0) { throw "clasp push failed" }
$desc = "river-level " + (Get-Date -Format "yyyy-MM-dd HH:mm")
clasp deploy -i $deploymentId -d $desc
if ($LASTEXITCODE -ne 0) { throw "clasp deploy failed" }
Write-Host "deployed: $desc"
