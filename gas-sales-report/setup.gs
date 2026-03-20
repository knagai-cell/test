/**
 * 営業日報管理システム — スプレッドシート初期セットアップ
 * このスクリプトを一度実行してシート構造を作成する
 */

function setupSheets() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // ===== 1. マスタシート =====
  var master = getOrCreateSheet(ss, 'マスタ');
  master.clear();
  master.getRange('A1:C1').setValues([['社員ID', '氏名', '部署']]);
  master.getRange('A1:C1').setFontWeight('bold').setBackground('#4472C4').setFontColor('#FFFFFF');

  // サンプルデータ（20名）
  var sampleMembers = [];
  for (var i = 1; i <= 20; i++) {
    sampleMembers.push(['EMP' + ('000' + i).slice(-3), '営業担当' + i, '営業部']);
  }
  master.getRange(2, 1, sampleMembers.length, 3).setValues(sampleMembers);
  master.setColumnWidth(1, 100);
  master.setColumnWidth(2, 150);
  master.setColumnWidth(3, 100);

  // ===== 2. 日報データシート =====
  var data = getOrCreateSheet(ss, '日報データ');
  data.clear();
  var headers = [
    'タイムスタンプ',    // A
    '報告日',           // B
    '社員ID',           // C
    '氏名',            // D
    '当日接触数',       // E
    'アポ数',           // F
    '商談数',           // G
    '申込数',           // H
    '成約数',           // I
    'アポ率(%)',        // J
    '商談化率(%)',      // K
    '申込率(%)',        // L
    '成約率(%)',        // M
    '今日の成功',       // N
    '今日の失敗',       // O
    '明日の改善',       // P
    '明日の行動予定',    // Q
    'ボトルネック',      // R
    '理由',            // S
    '上長コメント'      // T
  ];
  data.getRange(1, 1, 1, headers.length).setValues([headers]);
  data.getRange(1, 1, 1, headers.length).setFontWeight('bold').setBackground('#4472C4').setFontColor('#FFFFFF');
  data.setFrozenRows(1);

  // 列幅調整
  data.setColumnWidth(1, 160); // タイムスタンプ
  data.setColumnWidth(2, 110); // 報告日
  for (var c = 5; c <= 13; c++) {
    data.setColumnWidth(c, 100);
  }
  for (var c = 14; c <= 20; c++) {
    data.setColumnWidth(c, 200);
  }

  SpreadsheetApp.getUi().alert('セットアップが完了しました！\nマスタシートに担当者情報を入力してください。');
}

/**
 * シートを取得、なければ作成
 */
function getOrCreateSheet(ss, name) {
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
  }
  return sheet;
}
