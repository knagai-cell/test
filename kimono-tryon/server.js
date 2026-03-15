const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = 3000;
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY || '';

const server = http.createServer(async (req, res) => {
  // CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // Serve index.html
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
    const filePath = path.join(__dirname, 'index.html');
    fs.readFile(filePath, (err, data) => {
      if (err) {
        res.writeHead(500);
        res.end('Error loading index.html');
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(data);
    });
    return;
  }

  // Claude API proxy
  if (req.method === 'POST' && req.url === '/api/generate') {
    let body = '';
    req.on('data', chunk => { body += chunk.toString(); });
    req.on('end', async () => {
      try {
        const { imageBase64, imageMediaType, kimonoName, kimonoDescription, kimonoColor } = JSON.parse(body);

        if (!ANTHROPIC_API_KEY) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'ANTHROPIC_API_KEY が設定されていません。環境変数に設定してください。' }));
          return;
        }

        const requestBody = JSON.stringify({
          model: 'claude-opus-4-6',
          max_tokens: 1024,
          messages: [
            {
              role: 'user',
              content: [
                {
                  type: 'image',
                  source: {
                    type: 'base64',
                    media_type: imageMediaType,
                    data: imageBase64
                  }
                },
                {
                  type: 'text',
                  text: `この写真の人物が「${kimonoName}」（${kimonoDescription}）を着用したときの様子を、視覚的に鮮明に描写してください。

着物の特徴：
- 名前：${kimonoName}
- 説明：${kimonoDescription}
- 主な色：${kimonoColor}

以下の形式でJSONのみで回答してください（マークダウン不要）：
{
  "overall_impression": "全体的な印象（2〜3文）",
  "kimono_fit": "着物の着こなしの描写（2〜3文）",
  "color_harmony": "顔色・肌色との色調の調和（1〜2文）",
  "style_advice": "スタイリングアドバイス（1〜2文）",
  "scene_suggestion": "どんなシーンに合うか（1文）"
}`
                }
              ]
            }
          ]
        });

        const options = {
          hostname: 'api.anthropic.com',
          path: '/v1/messages',
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
            'Content-Length': Buffer.byteLength(requestBody)
          }
        };

        const apiReq = http.request(options, (apiRes) => {
          let apiBody = '';
          apiRes.on('data', chunk => { apiBody += chunk.toString(); });
          apiRes.on('end', () => {
            try {
              const apiResponse = JSON.parse(apiBody);
              if (apiResponse.error) {
                res.writeHead(400, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: apiResponse.error.message }));
                return;
              }
              const textContent = apiResponse.content?.find(b => b.type === 'text')?.text || '';
              // Extract JSON from response
              const jsonMatch = textContent.match(/\{[\s\S]*\}/);
              if (jsonMatch) {
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ result: JSON.parse(jsonMatch[0]) }));
              } else {
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ result: { overall_impression: textContent } }));
              }
            } catch (e) {
              res.writeHead(500, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ error: 'APIレスポンスの解析に失敗しました' }));
            }
          });
        });

        apiReq.on('error', (e) => {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: `Claude APIへの接続に失敗: ${e.message}` }));
        });

        apiReq.write(requestBody);
        apiReq.end();

      } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'リクエストの解析に失敗しました' }));
      }
    });
    return;
  }

  res.writeHead(404);
  res.end('Not Found');
});

server.listen(PORT, () => {
  console.log(`🎌 AI着物試着デモ起動中: http://localhost:${PORT}`);
  if (!ANTHROPIC_API_KEY) {
    console.warn('⚠️  ANTHROPIC_API_KEY が未設定です。export ANTHROPIC_API_KEY=your_key で設定してください。');
  }
});
