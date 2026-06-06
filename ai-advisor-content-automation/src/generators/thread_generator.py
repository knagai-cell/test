from ..utils.llm import call_llm

THREAD_SYSTEM_PROMPT = """あなたはAI顧問としてXのスレッド投稿を設計する編集者です。
以下の市場インサイトをもとに、教育的なスレッド投稿（5〜8投稿）を1本作成してください。

# 発信者の立ち位置
{positioning}

# ターゲット
{target_reader}

# 出力条件
- 1投稿目：フックとなる問題提起（保存・RTされやすい）
- 2〜6投稿目：具体的な解説（手順、事例、考え方）
- 最終投稿：まとめとCTA（noteや相談への誘導）
- 各投稿は140〜280字程度
- トーン：{tone}
- 禁止表現：{avoid_words}

# 出力形式
各投稿を番号付きで出力してください。
"""


def generate_thread(insights: str, brand: dict) -> str:
    prompt = THREAD_SYSTEM_PROMPT
    prompt = prompt.replace("{positioning}", brand.get("positioning", ""))
    prompt = prompt.replace("{target_reader}", brand.get("target_reader", ""))
    prompt = prompt.replace("{tone}", "、".join(brand.get("tone", [])))
    prompt = prompt.replace("{avoid_words}", "、".join(brand.get("avoid_words", [])))

    return call_llm(prompt, f"# 市場インサイト\n\n{insights}")
