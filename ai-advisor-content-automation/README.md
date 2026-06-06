# AI顧問コンテンツ運用自動化ツール

毎日のリサーチ素材から、AI顧問としてのX投稿案・note記事案・販売導線コンテンツを自動生成するツールです。

## セットアップ

```bash
cd ai-advisor-content-automation
pip install -r requirements.txt
cp .env.example .env
# .env を編集して ANTHROPIC_API_KEY を設定
```

## 使い方

### 1. リサーチ素材を準備

`data/raw/today_research.md` に、その日のリサーチ素材を貼り付けます。

- 同業アカウントの投稿、反応数、切り口
- 競合noteのタイトル、価格、構成
- AIニュース
- 読者の悩み（リプ、DM、コメントなど）

### 2. レポート生成

```bash
# 通常実行（Claude API使用）
python -m src.main

# 日付指定
python -m src.main --date 2026-06-06

# ドライラン（APIなしでサンプル出力を確認）
python -m src.main --dry-run
```

### 3. 出力を確認

`outputs/YYYY-MM-DD_daily_content.md` に日次レポートが生成されます。

## 出力内容

| 項目 | 内容 |
|---|---|
| 市場インサイト | 同業・AI業界の注目ポイント3つ |
| X投稿案 | 問題提起、手順解説、失敗回避、ストーリー、販売導線の5本 |
| スレッド案 | 教育的なスレッド投稿1本（5〜8投稿） |
| note構成案 | タイトル、無料部分、有料部分、特典の設計1本 |
| CTA・販売導線 | 有料note、無料相談、固定ポスト向けCTA |

## 設定ファイル

| ファイル | 内容 |
|---|---|
| `config/brand_voice.yaml` | ポジショニング、トーン、ストーリー要素、禁止ワード |
| `config/competitors.yaml` | 競合アカウント、noteクリエイター、YouTubeチャンネル |
| `config/keywords.yaml` | メインキーワード、読者の悩みキーワード |
| `config/output_rules.yaml` | 出力数、文字数制限、品質ルール |

## プロンプト

`prompts/` フォルダに用途別のプロンプトを管理しています。

| ファイル | 用途 |
|---|---|
| `research_summary.md` | リサーチ素材の分析・要約 |
| `x_post_generator.md` | X投稿案の生成 |
| `note_outline_generator.md` | note記事構成案の生成 |
| `sales_cta_generator.md` | 販売導線CTA の生成 |
| `quality_check.md` | 品質チェック |

## 運用ルーティン

1. **朝**：`data/raw/today_research.md` にリサーチ素材を貼る → `python -m src.main` 実行
2. **昼**：生成された投稿案を確認・修正 → 自分の体験談を追加 → X投稿
3. **夜**：反応を確認 → 翌日のリサーチメモに追記
4. **週末**：反応が良かった投稿をnote記事化

## 今後の拡張予定

1. Web検索・RSS取得による自動リサーチ
2. note無料部分のURL解析
3. X投稿の反応データ管理
4. Google Sheets / Notion 連携
5. 予約投稿ツール連携

## ディレクトリ構成

```
ai-advisor-content-automation/
├── config/          # 設定ファイル
├── prompts/         # LLMプロンプト
├── src/             # ソースコード
│   ├── collectors/  # データ収集（拡張用）
│   ├── analyzers/   # 分析（拡張用）
│   ├── generators/  # コンテンツ生成
│   └── utils/       # ユーティリティ
├── data/raw/        # リサーチ素材の入力場所
├── outputs/         # 日次レポートの出力先
└── requirements.txt
```
