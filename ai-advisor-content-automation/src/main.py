"""AI顧問コンテンツ運用自動化 - メインスクリプト

使い方:
    # 1日分まとめて生成
    python -m src.main [--date YYYY-MM-DD] [--dry-run]

    # 時間帯別に生成（朝・昼・夜）
    python -m src.main --session morning [--dry-run]
    python -m src.main --session afternoon [--dry-run]
    python -m src.main --session evening [--dry-run]

    # 全セッションを一括生成
    python -m src.main --session all [--dry-run]

data/raw/today_research.md にリサーチ素材を貼り付けてから実行してください。
素材がない場合はサンプルデータで動作します。
"""

import argparse
from datetime import date, datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SESSIONS = {
    "morning": {
        "label": "朝（8:00）",
        "description": "リサーチ分析＋教育系投稿＋週次月次戦略",
        "x_types": ["問題提起", "手順解説", "失敗回避", "ストーリー"],
        "include_insights": True,
        "include_thread": True,
        "include_note": False,
        "include_cta": False,
        "include_weekly_strategy": True,
        "include_monthly_strategy": True,
    },
    "afternoon": {
        "label": "昼（12:00）",
        "description": "ストーリー＋共感系",
        "x_types": ["共感", "実績報告", "ストーリー"],
        "include_insights": False,
        "include_thread": False,
        "include_note": False,
        "include_cta": False,
    },
    "evening": {
        "label": "夜（19:00）",
        "description": "販売導線＋note案＋翌日準備",
        "x_types": ["まとめ", "販売導線"],
        "include_insights": False,
        "include_thread": False,
        "include_note": True,
        "include_cta": True,
    },
}


def main():
    if load_dotenv:
        load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="AI顧問コンテンツ日次レポート生成")
    parser.add_argument("--date", type=str, default=None, help="対象日（YYYY-MM-DD）")
    parser.add_argument("--session", type=str, default=None,
                        choices=["morning", "afternoon", "evening", "all"],
                        help="時間帯別生成（morning/afternoon/evening/all）")
    parser.add_argument("--dry-run", action="store_true", help="LLM呼び出しをスキップしてサンプル出力")
    args = parser.parse_args()

    target_date = date.today()
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    from .utils.config_loader import load_all_configs
    from .utils.file_writer import get_output_path, write_daily_report
    from .collectors.research_loader import load_research_material

    configs = load_all_configs(PROJECT_ROOT / "config")
    brand = configs["brand_voice"]

    research = load_research_material(PROJECT_ROOT / "data" / "raw")

    if args.session:
        if args.session == "all":
            session_list = ["morning", "afternoon", "evening"]
        else:
            session_list = [args.session]

        for session_name in session_list:
            _run_session(session_name, target_date, research, brand, args.dry_run)
    else:
        _run_full(target_date, research, brand, args.dry_run)


def _run_session(session_name: str, target_date: date, research: str,
                 brand: dict, dry_run: bool):
    from .utils.file_writer import write_daily_report
    session = SESSIONS[session_name]

    print(f"=== {session['label']} セッション — {session['description']} ===")
    print(f"対象日: {target_date.isoformat()}")
    print()

    if dry_run:
        sections = _dry_run_session(session_name, brand)
    else:
        sections = _generate_session(session_name, research, brand)

    outputs_dir = PROJECT_ROOT / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    output_path = outputs_dir / f"{target_date.isoformat()}_{session_name}.md"

    lines = [
        f"# AI顧問コンテンツ — {session['label']}セッション\n",
        f"日付：{target_date.isoformat()}\n",
    ]
    for title, content in sections.items():
        lines.append(f"## {title}\n")
        lines.append(content)
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ 保存しました: {output_path}\n")


def _generate_session(session_name: str, research: str, brand: dict) -> dict[str, str]:
    from .generators.content_generator import ContentGenerator
    from .generators.thread_generator import generate_thread

    session = SESSIONS[session_name]
    gen = ContentGenerator(PROJECT_ROOT / "prompts", brand)
    sections = {}

    if session["include_insights"]:
        print("[1] 市場インサイトを分析中...")
        insights = gen.generate_research_summary(research)
        sections["市場インサイト"] = insights
    else:
        insights = research

    x_type_str = "、".join(session["x_types"])
    print(f"[2] X投稿案を生成中（{x_type_str}）...")
    x_posts = gen.generate_x_posts(
        f"# 市場インサイト\n{insights}\n\n# この時間帯の投稿タイプ\n{x_type_str}"
    )
    sections["X投稿案"] = x_posts

    if session["include_thread"]:
        print("[3] スレッド案を生成中...")
        thread = generate_thread(insights, brand)
        sections["スレッド案"] = thread

    if session["include_note"]:
        print("[4] note構成案を生成中...")
        note_outline = gen.generate_note_outline(insights)
        sections["note構成案"] = note_outline

    if session["include_cta"]:
        print("[5] CTA・販売導線を生成中...")
        cta = gen.generate_sales_cta(insights, x_posts[:500])
        sections["CTA・販売導線"] = cta

    if session.get("include_weekly_strategy"):
        from datetime import date as _date
        today = _date.today()
        week_start = today - __import__("datetime").timedelta(days=today.weekday())
        week_end = week_start + __import__("datetime").timedelta(days=6)
        current_week = f"{week_start.isoformat()} 〜 {week_end.isoformat()}"
        print("[6] 今週の戦略を生成中...")
        weekly = gen.generate_weekly_strategy(insights, current_week)
        sections["今週の発信戦略"] = weekly

    if session.get("include_monthly_strategy"):
        from datetime import date as _date
        today = _date.today()
        current_month = f"{today.year}年{today.month}月"
        print("[7] 今月の戦略を生成中...")
        monthly = gen.generate_monthly_strategy(insights, current_month)
        sections["今月の発信・マネタイズ戦略"] = monthly

    return sections


def _run_full(target_date: date, research: str, brand: dict, dry_run: bool):
    from .utils.file_writer import get_output_path, write_daily_report

    print(f"=== AI顧問コンテンツ日次レポート生成（1日分一括） ===")
    print(f"対象日: {target_date.isoformat()}")
    print(f"リサーチ素材: {len(research)}文字")
    print()

    if dry_run:
        sections = _dry_run_output(research, brand)
    else:
        sections = _generate_all(research, brand)

    output_path = get_output_path(PROJECT_ROOT / "outputs", target_date)
    write_daily_report(output_path, sections)
    print(f"\n✓ レポートを保存しました: {output_path}")


def _generate_all(research: str, brand: dict) -> dict[str, str]:
    from .generators.content_generator import ContentGenerator
    from .generators.thread_generator import generate_thread

    prompts_dir = PROJECT_ROOT / "prompts"
    gen = ContentGenerator(prompts_dir, brand)

    print("[1/6] 市場インサイトを分析中...")
    insights = gen.generate_research_summary(research)
    print("  → 完了")

    print("[2/6] X投稿案を生成中...")
    x_posts = gen.generate_x_posts(insights)
    print("  → 完了")

    print("[3/6] スレッド案を生成中...")
    thread = generate_thread(insights, brand)
    print("  → 完了")

    print("[4/6] note構成案を生成中...")
    note_outline = gen.generate_note_outline(insights)
    print("  → 完了")

    print("[5/6] 販売導線CTA・品質チェック中...")
    cta = gen.generate_sales_cta(insights, x_posts[:500])
    print("  → 完了")

    return {
        "今日の市場インサイト": insights,
        "今日のX投稿案": x_posts,
        "今日のスレッド案": thread,
        "今日のnote案": note_outline,
        "今日のCTA・販売導線": cta,
    }


def _dry_run_session(session_name: str, brand: dict) -> dict[str, str]:
    print("[DRY RUN] LLM呼び出しをスキップします\n")
    session = SESSIONS[session_name]
    handle = brand.get("x_account", {}).get("handle", "@_raccoon_ai")
    sections = {}

    if session_name == "morning":
        sections["市場インサイト"] = """| No | インサイト | 発信への使い方 |
|---:|---|---|
| 1 | AI顧問市場は参入者が増加中だが、実務経験を語れる人は少ない | 実体験ベースの差別化を強調 |
| 2 | 「AIを学んだがマネタイズできない」悩みが増加 | 共感→解決策の投稿パターン |
| 3 | 中小企業のAI導入ニーズが急増している | 法人向けAI顧問の需要を伝える |"""

        sections["X投稿案"] = """### 投稿1：問題提起（朝）

本文：「AIを勉強したのに稼げない」って悩んでる人、多いと思う。僕も最初そうだった。ChatGPTもClaudeも使えるようになった。でも収入はゼロ。理由はシンプルで「誰の、どんな困りごとを解決するか」を決めてなかったから。AI顧問は技術じゃなく「課題設定力」で差がつく。

狙い：朝の通勤時間に共感を獲得

CTA：プロフィールのnoteリンクへ

### 投稿2：手順解説（朝）

本文：AI顧問として最初の1社を取るまでにやったこと→①自分が業務効率化した事例を3つ言語化②知り合いの経営者に無料で1つ提案③成果が出たら月額契約を提案。営業経験ゼロでもこの順番なら自然に進む。

狙い：具体的手順で保存を狙う

CTA：詳しい手順はnoteにまとめています

### 投稿3：失敗回避（朝）

本文：AI顧問初心者がやりがちな失敗→「なんでもできます」と言ってしまうこと。最初は1つの業務に絞る方がいい。僕の場合は「会議の議事録と要約をAIで自動化する」だけで最初の契約を取った。

狙い：失敗回避で共感＋リプを促す

CTA：固定ポストで始め方をまとめています

### 投稿4：ストーリー（朝）

本文：専門卒、営業経験なし、物販も失敗。1年前の自分に「AI顧問5社やってるよ」って言っても信じないと思う。変わったきっかけは、前職で自分の仕事をChatGPTで効率化したこと。それを人に教えたら「お金払うから続けて」と言われた。

狙い：朝のタイムラインでストーリーを流す

CTA：同じ状況の方、DMで相談乗ります"""

        sections["スレッド案"] = """テーマ：営業経験なしでAI顧問5社を担当するまでの全手順

1投稿目：「営業できないとAI顧問は無理」って思ってませんか？僕は営業経験ゼロからAI顧問5社を担当しています。必要なのは営業力じゃなく「相手の困りごとを見つける力」でした。手順をスレッドで共有します↓

2投稿目：①まず自分の業務をAIで効率化する。僕は前職で議事録作成、メール文面作成、データ整理をChatGPTとClaudeで自動化した。この「自分で使った経験」が最初の武器になる。

3投稿目：②身近な経営者や個人事業主に「AI使ってますか？」と聞く。9割は「興味はあるけどよくわからない」と答える。そこで「1つだけ無料で試させてください」と提案する。

4投稿目：③無料で1つ成果を出す。議事録の自動化でも、SNS投稿の下書き作成でもいい。「これ毎月やってくれない？」と言われたら、月額提案する。これが最初の1社。

5投稿目：まとめ：営業力不要、必要なのは①自分で使う②身近な人に提案③無料で成果を出す④月額提案。この順番で5社まで増やせた。詳しくはnoteで解説しています。"""

    elif session_name == "afternoon":
        sections["X投稿案"] = """### 投稿1：共感（昼）

本文：AI顧問の仕事で一番嬉しい瞬間は「こんなに楽になるんですね」って言われるとき。大したことはしてない。ChatGPTで日報を要約する仕組みを作っただけ。でも相手にとっては毎日30分の節約。技術力より「相手の面倒を知ってるか」が大事。

狙い：昼休みの共感タイムに刺さる投稿

CTA：なし（エンゲージメント重視）

### 投稿2：実績報告（昼）

本文：今日のAI顧問業務：クライアントの社内チャットにClaude連携を導入。質問を投げると社内マニュアルから回答を返す仕組み。設定は2時間。「新人教育のコストが半分になりそう」と言われた。こういう小さな成功体験の積み重ねが信頼になる。

狙い：リアルタイムの活動報告で信頼性アップ

CTA：AI顧問の日常、毎日投稿してます

### 投稿3：ストーリー（昼）

本文：副業で物販やったとき、仕入れに30万使って利益2万だった。SNS運用代行は月5万で毎日投稿作成に追われた。どっちも「自分の時間を切り売り」してた。AI顧問は違う。相手の業務を効率化する仕組みを作るから、自分の時間は増える。

狙い：過去の失敗→現在の成功で共感と希望

CTA：AI顧問という働き方、noteで詳しく書いてます"""

    elif session_name == "evening":
        sections["X投稿案"] = f"""### 投稿1：まとめ（夜）

本文：今日のAI顧問の気づき。クライアントに「AIで何ができますか？」と聞かれたら「御社の○○の業務、毎日何分かかってますか？」と返す。相手の具体的な困りごとから入ると、提案が通りやすい。AI顧問は技術を売るんじゃなく、時間を売る仕事。

狙い：1日の振り返り＋学びの共有

CTA：プロフィールのnoteで詳しく

### 投稿2：販売導線（夜）

本文：AI顧問になりたい人向けに、僕が実際に使っている提案テンプレートと営業なしで契約を取った方法をnoteにまとめました。専門卒・営業経験なしでも再現できる内容です。

狙い：夜のじっくり読む時間帯にnote誘導

CTA：{handle} のプロフィールリンクからどうぞ"""

        sections["note構成案"] = """タイトル：【営業経験なし】専門卒からAI顧問5社を担当するまでの全記録

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

        sections["CTA・販売導線"] = f"""### 有料note誘導CTA
AI顧問の始め方を、営業経験なし・専門卒の僕が実体験ベースでまとめました。提案テンプレート付き→ {handle} のプロフィールリンクから

### 無料相談誘導CTA
AI顧問に興味あるけど何から始めればいいかわからない方、{handle} にDMください。営業経験なし・非エンジニアでもできた方法をお伝えします。

### 固定ポスト用CTA（{handle}）
専門卒→物販失敗→独学でAI学習→AI顧問5社｜営業経験なしでも再現できる方法をnoteで公開中｜AI顧問になりたい方はフォロー＋noteをチェック"""

    return sections


def _dry_run_output(research: str, brand: dict) -> dict[str, str]:
    print("[DRY RUN] LLM呼び出しをスキップします\n")
    sections = {}
    for session_name in ["morning", "afternoon", "evening"]:
        session_sections = _dry_run_session(session_name, brand)
        for key, value in session_sections.items():
            label = SESSIONS[session_name]["label"]
            sections[f"{key}（{label}）"] = value
    return sections


if __name__ == "__main__":
    main()
