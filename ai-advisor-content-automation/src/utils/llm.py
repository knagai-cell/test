import os
from anthropic import Anthropic


def get_client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が設定されていません。.env ファイルを確認してください。"
        )
    return Anthropic(api_key=api_key)


def call_llm(system_prompt: str, user_message: str) -> str:
    client = get_client()
    model = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "4096"))

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text
