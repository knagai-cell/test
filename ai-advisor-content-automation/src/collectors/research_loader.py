from pathlib import Path


def load_research_material(data_raw_dir: str | Path) -> str:
    """data/raw/today_research.md からリサーチ素材を読み込む。
    ファイルがなければサンプルデータを返す。"""
    raw_path = Path(data_raw_dir) / "today_research.md"

    if raw_path.exists():
        content = raw_path.read_text(encoding="utf-8").strip()
        if content:
            return content

    return _get_sample_research()


def _get_sample_research() -> str:
    return """# 今日のリサーチ素材（サンプル）

## X上の同業動向
- AI副業系アカウントが「AIコンサルは営業力不要、提案力が全て」という投稿で500いいね獲得
- 「ChatGPTで業務効率化した事例」をスレッドで紹介している人が伸びている
- AI顧問系の発信者が「最初の1社を獲得する方法」を有料noteで販売開始、初日50部

## note市場
- 「AI副業の始め方」系noteが980円で月間100部以上売れている傾向
- 無料部分で「自分の失敗談」を語り、有料部分で「具体的手順」を出すnoteが高評価
- AI顧問・AIコンサル系のnoteはまだ少なく、参入余地あり

## AIニュース
- Claude 4シリーズが発表され、エージェント機能が大幅強化
- 中小企業のAI導入率が前年比2倍に増加との調査結果
- 経済産業省がAI人材育成に500億円の予算を計上

## 読者の悩み（リプやDMから収集）
- 「AIは勉強したけど、どうやってお金にするかわからない」
- 「営業経験がないのでクライアントを取れる気がしない」
- 「副業でAIを使いたいが何から始めればいいか不明」
"""
