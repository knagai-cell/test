/**
 * LaBOLA 偵察ブックマークレット
 *
 * 使い方:
 *   1. 下の「ブックマーク用1行コード」をコピーする
 *   2. Chromeのブックマークバーを右クリック →「ページを追加」
 *   3. 名前: 「LaBOLA偵察」、URL欄に1行コードを貼り付けて保存
 *   4. LaBOLAの予約ページ(https://yoyaku.labola.jp/r/shop/3094/)を開く
 *   5. ブックマーク「LaBOLA偵察」をクリック
 *   6. F12 → Consoleタブ → 「LABOLA_INSPECT」と書かれた出力をコピーして渡す
 *
 * ブックマークへの登録方法（詳細）:
 *   Chrome右上「…」→ ブックマーク → ブックマークバーを表示（Ctrl+Shift+B）
 *   ブックマークバー上で右クリック →「ページを追加」
 *   名前: LaBOLA偵察
 *   URL: 下の「ブックマーク用1行コード」の内容をそのまま貼る
 */

// =========================================================
// 以下は開発用の読みやすい版（ブックマークには使わない）
// =========================================================
(function () {
  'use strict';

  const result = {
    url: location.href,
    timestamp: new Date().toISOString(),
    buttons: [],
    inputs: [],
    selects: [],
    calendarCells: [],
    reservationSlots: [],
    forms: [],
    dataAttributes: [],
    networkInterceptorInstalled: false,
    capturedRequests: [],
  };

  // ---- ボタン収集 ----
  document.querySelectorAll('button, input[type=button], input[type=submit], a[role=button]').forEach(el => {
    result.buttons.push({
      tag:     el.tagName.toLowerCase(),
      id:      el.id || null,
      classes: el.className || null,
      text:    (el.textContent || el.value || '').trim().slice(0, 80),
      type:    el.type || null,
      onclick: el.getAttribute('onclick') || null,
      href:    el.href || null,
      disabled: el.disabled,
      dataAttrs: Object.fromEntries(
        [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])
      ),
    });
  });

  // ---- input/select/textarea 収集 ----
  document.querySelectorAll('input:not([type=button]):not([type=submit]), select, textarea').forEach(el => {
    result.inputs.push({
      tag:     el.tagName.toLowerCase(),
      id:      el.id || null,
      name:    el.name || null,
      classes: el.className || null,
      type:    el.type || null,
      value:   (el.value || '').slice(0, 40),
      placeholder: el.placeholder || null,
      dataAttrs: Object.fromEntries(
        [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])
      ),
    });
  });

  // ---- カレンダーらしき要素を収集 ----
  const calendarSelectors = [
    '[class*="calendar"]', '[class*="Calendar"]',
    '[class*="datepicker"]', '[class*="date-picker"]',
    '[id*="calendar"]', '[id*="date"]',
    'td[data-date]', 'td[data-day]',
    '[class*="day"]', '[class*="cell"]',
  ];
  document.querySelectorAll(calendarSelectors.join(',')).forEach(el => {
    result.calendarCells.push({
      tag:      el.tagName.toLowerCase(),
      id:       el.id || null,
      classes:  el.className || null,
      text:     (el.textContent || '').trim().slice(0, 40),
      dataAttrs: Object.fromEntries(
        [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])
      ),
      onclick:  el.getAttribute('onclick') || null,
    });
  });

  // ---- 予約コマらしき要素を収集 ----
  const slotSelectors = [
    '[class*="slot"]', '[class*="frame"]', '[class*="reserve"]',
    '[class*="yoyaku"]', '[class*="koma"]', '[class*="time"]',
    '[class*="vacancy"]', '[class*="empty"]', '[class*="available"]',
  ];
  document.querySelectorAll(slotSelectors.join(',')).forEach(el => {
    const text = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    if (!text) return;
    result.reservationSlots.push({
      tag:      el.tagName.toLowerCase(),
      id:       el.id || null,
      classes:  el.className || null,
      text,
      dataAttrs: Object.fromEntries(
        [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])
      ),
    });
  });

  // ---- フォーム収集 ----
  document.querySelectorAll('form').forEach(el => {
    result.forms.push({
      id:     el.id || null,
      name:   el.name || null,
      action: el.action || null,
      method: el.method || null,
      classes: el.className || null,
    });
  });

  // ---- data-* 属性を持つ全要素（予約IDなどが埋まっていることが多い）----
  document.querySelectorAll('[data-id],[data-shop],[data-plan],[data-date],[data-slot],[data-frame],[data-course]').forEach(el => {
    result.dataAttributes.push({
      tag:      el.tagName.toLowerCase(),
      id:       el.id || null,
      classes:  el.className || null,
      text:     (el.textContent || '').trim().slice(0, 40),
      dataAttrs: Object.fromEntries(
        [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])
      ),
    });
  });

  // ---- ネットワーク通信インターセプター設置 ----
  try {
    // XHR インターセプト
    const origOpen  = XMLHttpRequest.prototype.open;
    const origSend  = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this._labola_method = method;
      this._labola_url    = url;
      return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
      const url = this._labola_url || '';
      if (url.includes('labola') || url.includes('yoyaku')) {
        const entry = { type: 'XHR', method: this._labola_method, url, requestBody: body || null, responseBody: null, status: null };
        result.capturedRequests.push(entry);
        this.addEventListener('load', function () {
          entry.status = this.status;
          try { entry.responseBody = JSON.parse(this.responseText); } catch (_) { entry.responseBody = this.responseText.slice(0, 500); }
          console.log('%c[LABOLA_INSPECT] XHR captured', 'color:orange;font-weight:bold', entry);
        });
      }
      return origSend.apply(this, arguments);
    };

    // Fetch インターセプト
    const origFetch = window.fetch;
    window.fetch = function (input, init) {
      const url = (typeof input === 'string' ? input : input.url) || '';
      if (url.includes('labola') || url.includes('yoyaku')) {
        return origFetch(input, init).then(res => {
          const clone = res.clone();
          clone.text().then(text => {
            let body = text;
            try { body = JSON.parse(text); } catch (_) {}
            const entry = { type: 'fetch', method: (init && init.method) || 'GET', url, requestBody: (init && init.body) || null, responseBody: body, status: res.status };
            result.capturedRequests.push(entry);
            console.log('%c[LABOLA_INSPECT] Fetch captured', 'color:cyan;font-weight:bold', entry);
          });
          return res;
        });
      }
      return origFetch(input, init);
    };

    result.networkInterceptorInstalled = true;
  } catch (e) {
    result.networkInterceptorInstalled = false;
    result.networkInterceptorError = e.message;
  }

  // ---- 最終出力 ----
  console.log('%c=== LABOLA_INSPECT RESULT ===', 'background:#1d4ed8;color:#fff;font-size:14px;padding:4px 8px;border-radius:4px');
  console.log('%c★ 以下のオブジェクト全体を右クリック → "Copy object" して渡してください', 'color:#f59e0b;font-weight:bold');
  console.log('LABOLA_INSPECT', result);
  console.log('%c=== ネットワーク通信はページ操作後に上に追記されます ===', 'background:#059669;color:#fff;padding:2px 6px;border-radius:4px');

  // 画面にも通知
  const banner = document.createElement('div');
  banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#1d4ed8;color:#fff;text-align:center;padding:10px;font-size:13px;font-family:sans-serif;';
  banner.textContent = '✅ LaBOLA偵察ツール起動済み｜DevTools(F12)→Consoleタブ→「LABOLA_INSPECT」を右クリック→Copy objectしてください';
  document.body.prepend(banner);
  setTimeout(() => banner.remove(), 8000);

  return result;
})();
