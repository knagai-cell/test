const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY || '';
const FAL_KEY = process.env.FAL_KEY || '';

// ─── HTTPS helper ────────────────────────────────────────────────────────────
function makeHttpsRequest(options, body) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => {
        resolve({ statusCode: res.statusCode, body: Buffer.concat(chunks).toString() });
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });
    if (body) req.write(body);
    req.end();
  });
}

// ─── Claude API analysis (kept for reference) ────────────────────────────────
async function runClaudeAnalysis(imageBase64, imageMediaType, kimonoName, kimonoDescription, kimonoColor) {
  if (!ANTHROPIC_API_KEY) throw new Error('ANTHROPIC_API_KEY が設定されていません');

  const requestBody = JSON.stringify({
    model: 'claude-opus-4-6',
    max_tokens: 1024,
    messages: [{
      role: 'user',
      content: [
        { type: 'image', source: { type: 'base64', media_type: imageMediaType, data: imageBase64 } },
        {
          type: 'text',
          text: `この写真の人物が「${kimonoName}」（${kimonoDescription}）を着用したときの様子を描写してください。\n着物の特徴: 名前=${kimonoName}, 説明=${kimonoDescription}, 色=${kimonoColor}\n以下のJSONのみで回答してください:\n{"overall_impression":"全体印象","kimono_fit":"着こなし","color_harmony":"色調調和","style_advice":"アドバイス","scene_suggestion":"おすすめシーン"}`
        }
      ]
    }]
  });

  const res = await makeHttpsRequest({
    hostname: 'api.anthropic.com',
    path: '/v1/messages',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
      'Content-Length': Buffer.byteLength(requestBody)
    },
    timeout: 60000
  }, requestBody);

  const apiResponse = JSON.parse(res.body);
  if (apiResponse.error) throw new Error(apiResponse.error.message);
  const text = apiResponse.content?.find(b => b.type === 'text')?.text || '';
  const jsonMatch = text.match(/\{[\s\S]*\}/);
  return jsonMatch ? JSON.parse(jsonMatch[0]) : { overall_impression: text };
}

// ─── Request body reader ──────────────────────────────────────────────────────
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString()));
    req.on('error', reject);
  });
}

// ─── HTTP Server ──────────────────────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  function json(statusCode, data) {
    res.writeHead(statusCode, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(data));
  }

  // Serve kimono preset images from public/kimonos/
  if (req.method === 'GET' && req.url.startsWith('/kimonos/')) {
    const safePath = path.normalize(req.url.replace(/^\/kimonos\//, ''));
    if (safePath.startsWith('..')) { res.writeHead(403); res.end('Forbidden'); return; }
    const filePath = path.join(__dirname, 'public', 'kimonos', safePath);
    fs.readFile(filePath, (err, data) => {
      if (err) { res.writeHead(404); res.end('Not Found'); return; }
      const ext = path.extname(filePath).toLowerCase();
      const mime = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp' };
      res.writeHead(200, { 'Content-Type': mime[ext] || 'application/octet-stream' });
      res.end(data);
    });
    return;
  }

  // Serve HTML
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
    fs.readFile(path.join(__dirname, 'index.html'), (err, data) => {
      if (err) { res.writeHead(500); res.end('Error loading index.html'); return; }
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(data);
    });
    return;
  }

  // ── POST /api/tryon : fal.ai キューにジョブを送信 ─────────────────────────
  if (req.method === 'POST' && req.url === '/api/tryon') {
    if (!FAL_KEY) return json(500, { error: 'FAL_KEY が設定されていません。export FAL_KEY=your_key で設定してください。' });

    try {
      const body = await readBody(req);
      const { personBase64, personMediaType, kimonoBase64, kimonoMediaType } = JSON.parse(body);

      if (!personBase64 || !kimonoBase64) return json(400, { error: '人物写真と着物画像の両方が必要です' });

      const submitBody = JSON.stringify({
        human_image_url: `data:${personMediaType};base64,${personBase64}`,
        garment_image_url: `data:${kimonoMediaType};base64,${kimonoBase64}`,
        cloth_type: 'overall',
        num_inference_steps: 30,
        guidance_scale: 2.5,
        seed: -1
      });

      const submitRes = await makeHttpsRequest({
        hostname: 'queue.fal.run',
        path: '/fal-ai/cat-vton',
        method: 'POST',
        headers: {
          'Authorization': `Key ${FAL_KEY}`,
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(submitBody)
        },
        timeout: 30000
      }, submitBody);

      if (submitRes.statusCode !== 200 && submitRes.statusCode !== 201) {
        let detail = submitRes.body;
        try { detail = JSON.parse(submitRes.body).detail || detail; } catch (_) {}
        return json(500, { error: `fal.ai 送信エラー (${submitRes.statusCode}): ${detail}` });
      }

      const { request_id } = JSON.parse(submitRes.body);
      console.log(`[tryon] ジョブ送信完了: ${request_id}`);
      json(200, { requestId: request_id });
    } catch (e) {
      console.error('[tryon] エラー:', e.message);
      json(500, { error: e.message });
    }
    return;
  }

  // ── GET /api/tryon?id=... : ジョブのステータスを確認 ──────────────────────
  if (req.method === 'GET' && req.url.startsWith('/api/tryon')) {
    if (!FAL_KEY) return json(500, { error: 'FAL_KEY が設定されていません。' });

    const id = new URL(req.url, `http://localhost:${PORT}`).searchParams.get('id');
    if (!id) return json(400, { error: 'id パラメータが必要です' });

    try {
      const statusRes = await makeHttpsRequest({
        hostname: 'queue.fal.run',
        path: `/fal-ai/cat-vton/requests/${id}/status`,
        method: 'GET',
        headers: { 'Authorization': `Key ${FAL_KEY}` },
        timeout: 10000
      });

      const status = JSON.parse(statusRes.body);

      if (status.status === 'COMPLETED') {
        const resultRes = await makeHttpsRequest({
          hostname: 'queue.fal.run',
          path: `/fal-ai/cat-vton/requests/${id}`,
          method: 'GET',
          headers: { 'Authorization': `Key ${FAL_KEY}` },
          timeout: 10000
        });
        const result = JSON.parse(resultRes.body);
        return json(200, { status: 'COMPLETED', imageUrl: result.image?.url });
      }

      if (status.status === 'FAILED') {
        return json(200, { status: 'FAILED', error: status.error?.message || '処理に失敗しました' });
      }

      json(200, { status: status.status });
    } catch (e) {
      console.error('[tryon status] エラー:', e.message);
      json(500, { error: e.message });
    }
    return;
  }

  // ── POST /api/generate : Claude Vision analysis (legacy) ─────────────────
  if (req.method === 'POST' && req.url === '/api/generate') {
    try {
      const body = await readBody(req);
      const { imageBase64, imageMediaType, kimonoName, kimonoDescription, kimonoColor } = JSON.parse(body);
      const result = await runClaudeAnalysis(imageBase64, imageMediaType, kimonoName, kimonoDescription, kimonoColor);
      json(200, { result });
    } catch (e) {
      console.error('[generate] エラー:', e.message);
      json(500, { error: e.message });
    }
    return;
  }

  res.writeHead(404); res.end('Not Found');
});

server.listen(PORT, () => {
  console.log(`\n🎌 AI着物試着デモ起動中: http://localhost:${PORT}\n`);
  if (!FAL_KEY) console.warn('⚠️  FAL_KEY 未設定 → export FAL_KEY=your_fal_key');
  if (!ANTHROPIC_API_KEY) console.warn('⚠️  ANTHROPIC_API_KEY 未設定 (Claude分析には不要)');
});
