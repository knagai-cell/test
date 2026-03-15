# AI着物試着デモ

Claude Vision APIを使ったシンプルな着物試着デモアプリです。

## 起動方法

```bash
# APIキーを設定
export ANTHROPIC_API_KEY=your_api_key_here

# サーバー起動
node server.js
```

ブラウザで http://localhost:3000 を開いてください。

## 機能

1. **写真アップロード** - カメラ撮影またはファイル選択（ドラッグ＆ドロップ対応）
2. **着物選択** - 振袖・訪問着・浴衣の3種類から選択
3. **AI試着生成** - Claude claude-opus-4-6 Vision APIで着用イメージを分析・描写
4. **結果表示** - 全体印象・着こなし・色調バランス・スタイリング・おすすめシーン

## 技術スタック

- **フロントエンド**: React 18 (CDN) + Tailwind CSS (CDN) + Babel Standalone
- **バックエンド**: Node.js built-in `http` モジュール（外部依存なし）
- **AI**: Claude claude-opus-4-6 (Vision API)
