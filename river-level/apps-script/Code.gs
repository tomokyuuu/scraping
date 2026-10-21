/**
 * river-level: GitHub Actions から送られてくる CSV を Google Drive に保存する Web App。
 *
 * 設定手順
 * 1. Drive に保存先フォルダを作り、URL の末尾の ID を控える
 * 2. script.google.com で新規プロジェクトを作り、このファイルを貼り付ける
 * 3. プロジェクトの設定 → スクリプト プロパティ に次の2つを追加
 *      ROOT_FOLDER_ID : 1 のフォルダ ID
 *      UPLOAD_TOKEN   : 長いでたらめな文字列（GitHub の Secrets DRIVE_TOKEN と同じ値にする）
 * 4. デプロイ → 新しいデプロイ → 種類「ウェブアプリ」、実行ユーザー「自分」、アクセス「全員」→ デプロイ
 *    表示される URL（.../exec）を GitHub の Secrets DRIVE_UPLOAD_URL に入れる
 * 5. コードを直したら「デプロイを管理」→ 新しいバージョンで再デプロイ（URL は変わらない）
 *
 * 受け取る JSON: {token, path: "ishikawa/2026/2026-10-20.csv", content: "..."}
 * path のフォルダは無ければ作る。同名ファイルがあれば中身を上書きする（ファイル ID は変わらない）。
 */
function doPost(e) {
  try {
    var props = PropertiesService.getScriptProperties();
    var body = JSON.parse(e.postData.contents);
    if (!body.token || body.token !== props.getProperty("UPLOAD_TOKEN")) {
      return reply_({ ok: false, error: "bad token" });
    }
    var parts = String(body.path || "").split("/").filter(function (s) { return s && s !== ".." ; });
    if (!parts.length) return reply_({ ok: false, error: "bad path" });
    var name = parts.pop();
    var folder = DriveApp.getFolderById(props.getProperty("ROOT_FOLDER_ID"));
    parts.forEach(function (p) {
      var it = folder.getFoldersByName(p);
      folder = it.hasNext() ? it.next() : folder.createFolder(p);
    });
    var files = folder.getFilesByName(name);
    var file;
    if (files.hasNext()) {
      file = files.next();
      file.setContent(body.content);
    } else {
      file = folder.createFile(name, body.content, "text/csv");
    }
    return reply_({ ok: true, id: file.getId(), url: file.getUrl() });
  } catch (err) {
    return reply_({ ok: false, error: String(err) });
  }
}

function doGet() {
  return reply_({ ok: true, message: "river-level upload endpoint" });
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
