# AI 着物試着デモ

スマートフォン向けの1ページReactレスアプリです。Claude Vision APIを使って、アップロードした写真に着物の試着イメージを生成します。

## 使い方

1. `index.html` をブラウザで開く（または `npx serve .` でローカルサーバー起動）
2. Anthropic APIキーを入力
3. 写真をアップロード（自撮りや全身写真推奨）
4. 着物を1つ選択（桜染め・藍染め・金彩鶴）
5. 「着用イメージを生成」ボタンをタップ

## 機能

- 📷 写真アップロード（ドラッグ&ドロップ対応）
- 👘 着物3種類の選択（桜染め / 藍染め / 金彩鶴）
- 🎨 Canvas APIによる着物カラーオーバーレイ生成
- 🤖 Claude Vision APIによるAI着用イメージ解説
- 📱 スマートフォン向けモバイルファーストUI

## 起動方法

```bash
npx serve .
# または
python3 -m http.server 3000
```

その後 `http://localhost:3000` をブラウザで開く。

## 必要なもの

- Anthropic APIキー（`sk-ant-...`）
- モダンブラウザ（Chrome / Safari / Firefox）

## 技術スタック

- Vanilla JS + HTML + CSS（ビルドツール不要）
- Canvas API（画像合成）
- Fetch API（Anthropic Messages API 直接呼び出し）
- SVG（着物イラスト）
