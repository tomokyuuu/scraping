# デスクトップに「河川水位」の丸いアイコンのショートカットを作る（公開ページを既定ブラウザで開く）
$url  = "https://tomokyuuu.github.io/scraping/"
$icon = Join-Path $PSScriptRoot "..\docs\icon.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "河川水位.lnk"
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = $url
$s.IconLocation = (Resolve-Path $icon).Path + ",0"
$s.Description = "石川・富山 河川水位（リアルタイム）"
$s.Save()
Write-Host "created: $lnk"
