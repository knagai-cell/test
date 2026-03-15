// Vercel serverless function: /api/tryon
// POST → submit job to fal.ai queue, return { requestId }
// GET  → check status, return { status, imageUrl? }

const https = require('https');

const FAL_KEY = process.env.FAL_KEY || '';

function makeHttpsRequest(options, body) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({
        statusCode: res.statusCode,
        body: Buffer.concat(chunks).toString()
      }));
    });
    req.on('error', reject);
    req.setTimeout(8000, () => { req.destroy(); reject(new Error('Request timeout')); });
    if (body) req.write(body);
    req.end();
  });
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(204).end(); return; }

  if (!FAL_KEY) {
    return res.status(500).json({ error: 'FAL_KEY が未設定です。Vercel のEnvironment Variablesに追加してください。' });
  }

  // ── POST: fal.ai キューにジョブを送信 ─────────────────────────────────────
  if (req.method === 'POST') {
    const { personBase64, personMediaType, kimonoBase64, kimonoMediaType } = req.body || {};
    if (!personBase64 || !kimonoBase64) {
      return res.status(400).json({ error: '人物写真と着物画像の両方が必要です' });
    }

    const submitBody = JSON.stringify({
      human_image_url:  `data:${personMediaType};base64,${personBase64}`,
      garment_image_url:`data:${kimonoMediaType};base64,${kimonoBase64}`,
      cloth_type: 'overall',
      num_inference_steps: 30,
      guidance_scale: 2.5,
      seed: -1
    });

    let result;
    try {
      result = await makeHttpsRequest({
        hostname: 'queue.fal.run',
        path: '/fal-ai/cat-vton',
        method: 'POST',
        headers: {
          'Authorization': `Key ${FAL_KEY}`,
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(submitBody)
        }
      }, submitBody);
    } catch (e) {
      return res.status(500).json({ error: `fal.ai への接続に失敗: ${e.message}` });
    }

    if (result.statusCode !== 200 && result.statusCode !== 201) {
      let detail = result.body;
      try { detail = JSON.parse(result.body).detail || detail; } catch (_) {}
      return res.status(500).json({ error: `fal.ai 送信エラー (${result.statusCode}): ${detail}` });
    }

    const { request_id } = JSON.parse(result.body);
    return res.json({ requestId: request_id });
  }

  // ── GET: ジョブのステータスを確認 ─────────────────────────────────────────
  if (req.method === 'GET') {
    const id = req.query?.id;
    if (!id) return res.status(400).json({ error: 'id パラメータが必要です' });

    let statusResult;
    try {
      statusResult = await makeHttpsRequest({
        hostname: 'queue.fal.run',
        path: `/fal-ai/cat-vton/requests/${id}/status`,
        method: 'GET',
        headers: { 'Authorization': `Key ${FAL_KEY}` }
      });
    } catch (e) {
      return res.status(500).json({ error: `ステータス確認に失敗: ${e.message}` });
    }

    const status = JSON.parse(statusResult.body);

    if (status.status === 'COMPLETED') {
      let finalResult;
      try {
        finalResult = await makeHttpsRequest({
          hostname: 'queue.fal.run',
          path: `/fal-ai/cat-vton/requests/${id}`,
          method: 'GET',
          headers: { 'Authorization': `Key ${FAL_KEY}` }
        });
      } catch (e) {
        return res.status(500).json({ error: `結果取得に失敗: ${e.message}` });
      }
      const result = JSON.parse(finalResult.body);
      return res.json({ status: 'COMPLETED', imageUrl: result.image?.url });
    }

    if (status.status === 'FAILED') {
      return res.json({ status: 'FAILED', error: status.error?.message || '処理に失敗しました' });
    }

    // IN_QUEUE | IN_PROGRESS
    return res.json({ status: status.status });
  }

  res.status(405).json({ error: 'Method not allowed' });
};
