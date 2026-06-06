"""AI顧問コンテンツ運用自動化 - メインスクリプト

使い方:
    python -m src.main [--date YYYY-MM-DD] [--dry-run]

data/raw/today_research.md にリサーチ素材を貼り付けてから実行してください。
素材がない場合はサンプルデータで動作します。
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main():
    if load_dotenv:
        load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="AI顧問コンテンツ日次レポート生成")
    parser.add_argument("--date", type=str, default=None, help="対象日（YYYY-MM-DD）")
    parser.add_argument("--dry-run", action="store_true", help="LLM呼び出しをスキップしてサンプル出力")
    args = parser.parse_args()

    target_date = date.today()
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    print(f"=== AI顧問コンテンツ日次レポート生成 ===")
    print(f"対象日: {target_date.isoformat()}")
    print()

    from .utils.config_loader import load_all_configs
    from .utils.file_writer import get_output_path, write_daily_report
    from .collectors.research_loader import load_research_material

    configs = load_all_configs(PROJECT_ROOT / "config")
    brand = configs["brand_voice"]

    print("[1/6] リサーチ素材を読み込み中...")
    research = load_research_material(PROJECT_ROOT / "data" / "raw")
    print(f"  → {len(research)}文字のリサーチ素材を読み込みました")

    if args.dry_run:
        sections = _dry_run_output(research, brand)
    else:
        sections = _generate_all(research, brand, PROJECT_ROOT / "prompts")

    output_path = get_output_path(PROJECT_ROOT / "outputs", target_date)
    write_daily_report(output_path, sections)
    print(f"\n✓ レポートを保存しました: {output_path}")


def _generate_all(research: str, brand: dict, prompts_dir: Path) -> dict[str, str]:
    from .generators.content_generator import ContentGenerator
    from .generators.thread_generator import generate_thread

    gen = ContentGenerator(prompts_dir, brand)

    print("[2/6] 市場インサイトを分析中...")
    insights = gen.generate_research_summary(research)
    print("  → 完了")

    print("[3/6] X投稿案を生成中...")
    x_posts = gen.generate_x_posts(insights)
    print("  → 完了")

    print("[4/6] スレッド案を生成中...")
    thread = generate_thread(insights, brand)
    print("  → 完了")

    print("[5/6] note構成案を生成中...")
    note_outline = gen.generate_note_outline(insights)
    print("  → 完了")

    print("[6/6] 販売導線CTA・品質チェック中...")
    cta = gen.generate_sales_cta(insights, x_posts[:500])
    print("  → 完了")

    return {
        "今日の市場インサイト": insights,
        "今日のX投稿案": x_posts,
        "今日のスレッド案": thread,
        "今日のnote案": note_outline,
        "今日のCTA・販売導線": cta,
    }


def _dry_run_output(research: str, brand: dict) -> dict[str, str]:
    print("[DRY RUN] LLM呼び出しをスキップします")
    print()

    insights = """| No | インサイト | 発信への使い方 |
|---:|---|---|
| 1 | AI顧問市場は参入者が増加中だが、実務経験を語れる人は少ない | 実体験ベースの差別化を強調 |
| 2 | 「AIを学んだがマネタイズできない」悩みが増加 | 共感→解決策の投稿パターン |
| 3 | 中小企業のAI導入ニーズが急増している | 法人向けAI顧問の需要を伝える |"""

    x_posts = """### 投稿1：問題提起

本文：「AIを勉強したのに稼げない」って悩んでる人、多いと思う。僕も最初そうだった。ChatGPTもClaudeも使えるようになった。でも収入はゼロ。理由はシンプルで「誰の、どんな困りごとを解決するか」を決めてなかったから。AI顧問は技術じゃなく「課題設定力」で差がつく。

狙い：共感から入り、AI顧問の本質を伝える

CTA：プロフィールのnoteリンクで詳しく解説しています

### 投稿2：手順解説

本文：AI顧問として最初の1社を取るまでにやったこと→①自分が業務効率化した事例を3つ言語化②知り合いの経営者に無料で1つ提案③成果が出たら月額契約を提案。営業経験ゼロでもこの順番なら自然に進む。大事なのは「まず1社の成功体験」を作ること。

狙い：具体的手順で再現性を見せる

CTA：詳しい手順はnoteにまとめています

### 投稿3：失敗回避

本文：AI顧問初心者がやりがちな失敗→「なんでもできます」と言ってしまうこと。最初は1つの業務に絞る方がいい。僕の場合は「会議の議事録と要約をAIで自動化する」だけで最初の契約を取った。広げるのは信頼を得てから。

狙い：失敗回避で読者の不安を解消

CTA：固定ポストで始め方をまとめています

### 投稿4：ストーリー

本文：専門卒、営業経験なし、物販も失敗。1年前の自分に「AI顧問5社やってるよ」って言っても信じないと思う。変わったきっかけは、前職で自分の仕事をChatGPTで効率化したこと。それを人に教えたら「お金払うから続けて」と言われた。スキルより「誰かの役に立った経験」が最初の一歩だった。

狙い：ストーリーで共感と信頼を作る

CTA：同じ状況の方、DMで相談乗ります

### 投稿5：販売導線

本文：AI顧問になりたい人向けに、僕が実際に使っている提案テンプレートと営業なしで契約を取った方法をnoteにまとめました。専門卒・営業経験なしでも再現できる内容です。今なら特典付き。

狙い：有料noteへの自然な誘導

CTA：プロフィールのリンクからどうぞ"""

    thread = """テーマ：営業経験なしでAI顧問5社を担当するまでの全手順

1投稿目：「営業できないとAI顧問は無理」って思ってませんか？僕は営業経験ゼロからAI顧問5社を担当しています。必要なのは営業力じゃなく「相手の困りごとを見つける力」でした。手順をスレッドで共有します↓

2投稿目：①まず自分の業務をAIで効率化する。僕は前職で議事録作成、メール文面作成、データ整理をChatGPTとClaudeで自動化した。この「自分で使った経験」が最初の武器になる。

3投稿目：②身近な経営者や個人事業主に「AI使ってますか？」と聞く。9割は「興味はあるけどよくわからない」と答える。そこで「1つだけ無料で試させてください」と提案する。

4投稿目：③無料で1つ成果を出す。議事録の自動化でも、SNS投稿の下書き作成でもいい。「これ毎月やってくれない？」と言われたら、月額提案する。これが最初の1社。

5投稿目：まとめ：営業力不要、必要なのは①自分で使う②身近な人に提案③無料で成果を出す④月額提案。この順番で5社まで増やせた。詳しくはnoteで解説しています。"""

    note_outline = """タイトル：【営業経験なし】専門卒からAI顧問5社を担当するまでの全記録

想定読者：AIを学んだがマネタイズできていない会社員・個人事業主

無料部分：
- 自己紹介と失敗の経歴
- AI顧問とは何か
- なぜ営業経験がなくてもできるのか

有料部分：
- 最初の1社を取った具体的手順
- 提案テンプレート（実物）
- 月額契約の提案方法
- 5社に増やすまでのタイムライン

特典案：提案書テンプレートPDF

価格案：1,980円"""

    handle = brand.get("x_account", {}).get("handle", "@_raccoon_ai")
    cta = f"""### 有料note誘導CTA
AI顧問の始め方を、営業経験なし・専門卒の僕が実体験ベースでまとめました。提案テンプレート付き→ {handle} のプロフィールリンクから

### 無料相談誘導CTA
AI顧問に興味あるけど何から始めればいいかわからない方、{handle} にDMください。営業経験なし・非エンジニアでもできた方法をお伝えします。

### 固定ポスト用CTA（{handle}）
専門卒→物販失敗→独学でAI学習→AI顧問5社｜営業経験なしでも再現できる方法をnoteで公開中｜AI顧問になりたい方はフォロー＋noteをチェック"""

    return {
        "今日の市場インサイト": insights,
        "今日のX投稿案": x_posts,
        "今日のスレッド案": thread,
        "今日のnote案": note_outline,
        "今日のCTA・販売導線": cta,
    }


if __name__ == "__main__":
    main()
