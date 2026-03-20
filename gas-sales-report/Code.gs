/**
 * 営業日報管理システム — メインスクリプト
 * GAS Web App として公開して使用する
 */

// ===== スプレッドシートID（デプロイ前に設定） =====
var SPREADSHEET_ID = '★ここにスプレッドシートIDを貼り付け★';

/**
 * Web App エントリーポイント (GET)
 */
function doGet(e) {
  var page = e.parameter.page || 'index';
  var template;

  if (page === 'dashboard') {
    template = HtmlService.createTemplateFromFile('dashboard');
  } else {
    template = HtmlService.createTemplateFromFile('index');
  }

  return template.evaluate()
    .setTitle('営業日報管理システム')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/**
 * HTML内で他のファイルをインクルードするヘルパー
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

// ===== データ操作関数 =====

/**
 * スプレッドシートを取得
 */
function getSpreadsheet() {
  if (SPREADSHEET_ID === '★ここにスプレッドシートIDを貼り付け★') {
    return SpreadsheetApp.getActiveSpreadsheet();
  }
  return SpreadsheetApp.openById(SPREADSHEET_ID);
}

/**
 * 担当者リストを取得
 */
function getMembers() {
  var ss = getSpreadsheet();
  var sheet = ss.getSheetByName('マスタ');
  if (!sheet) return [];

  var data = sheet.getDataRange().getValues();
  var members = [];
  for (var i = 1; i < data.length; i++) {
    if (data[i][0]) {
      members.push({
        id: data[i][0],
        name: data[i][1],
        department: data[i][2]
      });
    }
  }
  return members;
}

/**
 * 日報を保存
 * @param {Object} report - 日報データ
 * @return {Object} 結果
 */
function saveReport(report) {
  try {
    var ss = getSpreadsheet();
    var sheet = ss.getSheetByName('日報データ');
    if (!sheet) {
      return { success: false, message: '日報データシートが見つかりません。setupSheets()を実行してください。' };
    }

    // パーセント計算
    var contactCount = Number(report.contactCount) || 0;
    var appoCount = Number(report.appoCount) || 0;
    var meetingCount = Number(report.meetingCount) || 0;
    var applicationCount = Number(report.applicationCount) || 0;
    var contractCount = Number(report.contractCount) || 0;

    var appoRate = contactCount > 0 ? Math.round((appoCount / contactCount) * 1000) / 10 : 0;
    var meetingRate = appoCount > 0 ? Math.round((meetingCount / appoCount) * 1000) / 10 : 0;
    var applicationRate = meetingCount > 0 ? Math.round((applicationCount / meetingCount) * 1000) / 10 : 0;
    var contractRate = applicationCount > 0 ? Math.round((contractCount / applicationCount) * 1000) / 10 : 0;

    var row = [
      new Date(),                    // タイムスタンプ
      report.reportDate,             // 報告日
      report.employeeId,             // 社員ID
      report.employeeName,           // 氏名
      contactCount,                  // 当日接触数
      appoCount,                     // アポ数
      meetingCount,                  // 商談数
      applicationCount,              // 申込数
      contractCount,                 // 成約数
      appoRate,                      // アポ率
      meetingRate,                   // 商談化率
      applicationRate,               // 申込率
      contractRate,                  // 成約率
      report.todaySuccess || '',     // 今日の成功
      report.todayFailure || '',     // 今日の失敗
      report.tomorrowImprovement || '', // 明日の改善
      report.tomorrowPlan || '',     // 明日の行動予定
      report.bottleneck || '',       // ボトルネック
      report.reason || '',           // 理由
      ''                             // 上長コメント（後で記入）
    ];

    sheet.appendRow(row);

    return { success: true, message: '日報を保存しました。' };
  } catch (e) {
    return { success: false, message: 'エラー: ' + e.message };
  }
}

/**
 * 指定日の日報一覧を取得（ダッシュボード用）
 * @param {string} date - 日付文字列 (yyyy-MM-dd)
 * @return {Array} 日報リスト
 */
function getReportsByDate(date) {
  var ss = getSpreadsheet();
  var sheet = ss.getSheetByName('日報データ');
  if (!sheet) return [];

  var data = sheet.getDataRange().getValues();
  var reports = [];

  for (var i = 1; i < data.length; i++) {
    var reportDate = data[i][1];
    if (reportDate === date) {
      reports.push({
        rowIndex: i + 1,
        timestamp: data[i][0],
        reportDate: data[i][1],
        employeeId: data[i][2],
        employeeName: data[i][3],
        contactCount: data[i][4],
        appoCount: data[i][5],
        meetingCount: data[i][6],
        applicationCount: data[i][7],
        contractCount: data[i][8],
        appoRate: data[i][9],
        meetingRate: data[i][10],
        applicationRate: data[i][11],
        contractRate: data[i][12],
        todaySuccess: data[i][13],
        todayFailure: data[i][14],
        tomorrowImprovement: data[i][15],
        tomorrowPlan: data[i][16],
        bottleneck: data[i][17],
        reason: data[i][18],
        managerComment: data[i][19]
      });
    }
  }
  return reports;
}

/**
 * 上長コメントを保存
 * @param {number} rowIndex - 行番号
 * @param {string} comment - コメント
 * @return {Object} 結果
 */
function saveManagerComment(rowIndex, comment) {
  try {
    var ss = getSpreadsheet();
    var sheet = ss.getSheetByName('日報データ');
    sheet.getRange(rowIndex, 20).setValue(comment); // T列 = 20列目
    return { success: true, message: 'コメントを保存しました。' };
  } catch (e) {
    return { success: false, message: 'エラー: ' + e.message };
  }
}

/**
 * チームサマリーを取得（指定日）
 * @param {string} date - 日付文字列
 * @return {Object} サマリーデータ
 */
function getTeamSummary(date) {
  var reports = getReportsByDate(date);
  if (reports.length === 0) {
    return { reportCount: 0, totalContact: 0, totalAppo: 0, totalMeeting: 0, totalApplication: 0, totalContract: 0 };
  }

  var summary = {
    reportCount: reports.length,
    totalContact: 0,
    totalAppo: 0,
    totalMeeting: 0,
    totalApplication: 0,
    totalContract: 0
  };

  for (var i = 0; i < reports.length; i++) {
    summary.totalContact += Number(reports[i].contactCount) || 0;
    summary.totalAppo += Number(reports[i].appoCount) || 0;
    summary.totalMeeting += Number(reports[i].meetingCount) || 0;
    summary.totalApplication += Number(reports[i].applicationCount) || 0;
    summary.totalContract += Number(reports[i].contractCount) || 0;
  }

  summary.avgAppoRate = summary.totalContact > 0 ? Math.round((summary.totalAppo / summary.totalContact) * 1000) / 10 : 0;
  summary.avgMeetingRate = summary.totalAppo > 0 ? Math.round((summary.totalMeeting / summary.totalAppo) * 1000) / 10 : 0;
  summary.avgApplicationRate = summary.totalMeeting > 0 ? Math.round((summary.totalApplication / summary.totalMeeting) * 1000) / 10 : 0;
  summary.avgContractRate = summary.totalApplication > 0 ? Math.round((summary.totalContract / summary.totalApplication) * 1000) / 10 : 0;

  return summary;
}
