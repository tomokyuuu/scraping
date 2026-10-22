/**
 * river-level: GitHub Actions から送られてくる CSV/JSON を Google Drive に保存し、地図ページに読み取りを提供する Web App。
 *
 * 設定手順
 * 1. Drive に保存先フォルダを作り、URL の末尾の ID を控える
 * 2. script.google.com で新規プロジェクトを作り、このファイルを貼り付ける（または clasp push）
 * 3. プロジェクトの設定 → スクリプト プロパティ に次の2つを追加
 *      ROOT_FOLDER_ID : 1 のフォルダ ID
 *      UPLOAD_TOKEN   : 長いでたらめな文字列（GitHub の Secrets DRIVE_TOKEN と同じ値にする）
 *      VIEW_PASSWORD  : 地図ページの合言葉
 *      MAIL_TO        : 氾濫通知メールの宛先（省略時はこのスクリプトの所有者）
 * 4. デプロイ → 新しいデプロイ → 種類「ウェブアプリ」、実行ユーザー「自分」、アクセス「全員」→ デプロイ
 *    表示される URL（.../exec）を GitHub の Secrets DRIVE_UPLOAD_URL と docs/index.html の API_URL に入れる
 * 5. コードを直したら「デプロイを管理」→ 新しいバージョンで再デプロイ（URL は変わらない）。clasp なら deploy.ps1
 *
 * POST（書き込み。トークン必須）: {token, path: "ishikawa/2026/2026-10-20.csv", content: "..."}
 *   path のフォルダは無ければ作る。同名ファイルがあれば中身を上書きする（ファイル ID は変わらない）。
 *   画像は {token, path: "camera/104353011/20261022_0925.jpg", content_b64: "..."}（同名があれば何もしない）
 * GET（読み取り。pw=合言葉 が必要）:
 *   ?auth=1&pw=...                        合言葉の確認
 *   ?tree=1&pw=...                        フォルダ構成（データ台帳）
 *   ?series=<src>&id=<obs_id>&pw=...      1観測所の時系列（series/<src>.json から切り出す）
 */
function doPost(e) {
  try {
    var props = PropertiesService.getScriptProperties();
    var body = JSON.parse(e.postData.contents);
    if (!body.token || body.token !== props.getProperty("UPLOAD_TOKEN")) {
      return reply_({ ok: false, error: "bad token" });
    }
    if (body.mail) {
      // 氾濫通知メール。宛先はスクリプトプロパティ MAIL_TO
      var to = props.getProperty("MAIL_TO");
      if (!to) return reply_({ ok: false, error: "MAIL_TO not set" });
      MailApp.sendEmail({ to: to, subject: String(body.mail.subject || "river-level"), body: String(body.mail.body || "") });
      return reply_({ ok: true, to: to });
    }
    var parts = String(body.path || "").split("/").filter(function (s) { return s && s !== ".."; });
    if (!parts.length) return reply_({ ok: false, error: "bad path" });
    var name = parts.pop();
    var folder = subfolder_(root_(), parts, true);
    var files = folder.getFilesByName(name);
    var file;
    if (body.content_b64) {
      // 画像などのバイナリ（base64）。同名があれば置き換えずそのまま（撮影時刻がファイル名なので同じ中身）
      if (files.hasNext()) {
        file = files.next();
      } else {
        var mimeB = /\.png$/i.test(name) ? "image/png" : /\.zip$/i.test(name) ? "application/zip" : "image/jpeg";
        file = folder.createFile(Utilities.newBlob(Utilities.base64Decode(body.content_b64), mimeB, name));
      }
    } else if (files.hasNext()) {
      file = files.next();
      file.setContent(body.content);
    } else {
      var mime = /\.json$/i.test(name) ? "application/json" : "text/csv";
      file = folder.createFile(name, body.content, mime);
    }
    return reply_({ ok: true, id: file.getId(), url: file.getUrl() });
  } catch (err) {
    return reply_({ ok: false, error: String(err) });
  }
}

/**
 * メール送信の権限を承認するために、エディタから一度だけ手で実行する（▶ 実行）。
 * 承認後は MAIL_TO 宛にテストメールが 1 通届く。
 */
function testMail() {
  var to = PropertiesService.getScriptProperties().getProperty("MAIL_TO");
  if (!to) throw new Error("スクリプトプロパティ MAIL_TO を先に設定してください");
  MailApp.sendEmail({ to: to, subject: "【河川水位】テスト通知", body: "river-level の氾濫通知メールのテストです。本番では、観測所が新たに氾濫開始水位／計画高水位を超えたときだけ 1 通届きます。" });
  Logger.log("sent to " + to);
}

function doGet(e) {
  try {
    var p = (e && e.parameter) || {};
    if (p.auth || p.tree || p.series) {
      // 合言葉（スクリプトプロパティ VIEW_PASSWORD）。運用情報は合言葉を知っている人だけに返す
      var want = PropertiesService.getScriptProperties().getProperty("VIEW_PASSWORD");
      if (!want || String(p.pw || "") !== want) return reply_({ ok: false, error: "bad password" });
    }
    if (p.auth) return reply_({ ok: true, root: root_().getUrl() });
    if (p.tree) return reply_({ ok: true, root: root_().getUrl(), tree: tree_(root_(), 0) });
    if (p.ls !== undefined) {
      // 1階層だけ（データ台帳を段階的に開くため）。ls=ishikawa/2026 のようにパス指定。空ならルート
      var parts = String(p.ls || "").split("/").filter(function (s) { return s && s !== ".."; });
      var folder = subfolder_(root_(), parts, false);
      if (!folder) return reply_({ ok: false, error: "no folder " + p.ls });
      return reply_({ ok: true, root: root_().getUrl(), tree: tree_(folder, 3) });
    }
    if (p.series) return reply_(series_(String(p.series), String(p.id || "")));
    return reply_({ ok: true, message: "river-level endpoint" });
  } catch (err) {
    return reply_({ ok: false, error: String(err) });
  }
}

function root_() {
  return DriveApp.getFolderById(PropertiesService.getScriptProperties().getProperty("ROOT_FOLDER_ID"));
}

function subfolder_(folder, parts, create) {
  for (var i = 0; i < parts.length; i++) {
    var it = folder.getFoldersByName(parts[i]);
    if (it.hasNext()) folder = it.next();
    else if (create) folder = folder.createFolder(parts[i]);
    else return null;
  }
  return folder;
}

// フォルダを再帰的に並べる（3階層まで）。ファイルは名前・サイズ・更新時刻・リンク
function tree_(folder, depth) {
  var out = { name: folder.getName(), url: folder.getUrl(), folders: [], files: [] };
  var fs = folder.getFiles();
  while (fs.hasNext()) {
    var f = fs.next();
    out.files.push({ name: f.getName(), size: f.getSize(), updated: f.getLastUpdated().toISOString(), url: f.getUrl() });
  }
  out.files.sort(function (a, b) { return a.name < b.name ? -1 : 1; });
  var it = folder.getFolders();
  while (it.hasNext()) {
    var sub = it.next();
    // depth 3 以上は中身を読まず名前だけ（段階表示用）
    out.folders.push(depth < 3 ? tree_(sub, depth + 1) : { name: sub.getName(), url: sub.getUrl(), folders: null, files: null });
  }
  out.folders.sort(function (a, b) { return a.name < b.name ? -1 : 1; });
  return out;
}

function series_(src, id) {
  if (!/^[a-z_]+$/.test(src) || !/^[0-9A-Za-z_-]+$/.test(id)) return { ok: false, error: "bad params" };
  var folder = subfolder_(root_(), ["series"], false);
  if (!folder) return { ok: false, error: "no series folder" };
  var files = folder.getFilesByName(src + ".json");
  if (!files.hasNext()) return { ok: false, error: "no series for " + src };
  var all = JSON.parse(files.next().getBlob().getDataAsString("UTF-8"));
  var s = all.series[id];
  if (!s) return { ok: false, error: "no station " + id };
  return { ok: true, src: src, id: id, updated: all.updated, t0: all.t0, step: all.step, name: s.name, kind: s.kind, v: s.v };
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
