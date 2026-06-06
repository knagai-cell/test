from pathlib import Path

from ..utils.config_loader import load_prompt, format_prompt
from ..utils.llm import call_llm


class ContentGenerator:
    def __init__(self, prompts_dir: str | Path, brand_voice: dict):
        self.prompts_dir = Path(prompts_dir)
        self.brand = brand_voice

    def _load_and_format(self, prompt_file: str) -> str:
        raw = load_prompt(self.prompts_dir / prompt_file)
        return format_prompt(raw, self.brand)

    def generate_research_summary(self, research_material: str) -> str:
        system = self._load_and_format("research_summary.md")
        return call_llm(system, f"# 本日のリサーチ素材\n\n{research_material}")

    def generate_x_posts(self, insights: str) -> str:
        system = self._load_and_format("x_post_generator.md")
        return call_llm(system, f"# 市場インサイト\n\n{insights}")

    def generate_note_outline(self, insights: str) -> str:
        system = self._load_and_format("note_outline_generator.md")
        return call_llm(system, f"# リサーチ結果\n\n{insights}")

    def generate_sales_cta(self, insights: str, content_summary: str) -> str:
        system = self._load_and_format("sales_cta_generator.md")
        user_msg = f"# 市場インサイト\n\n{insights}\n\n# コンテンツ案概要\n\n{content_summary}"
        return call_llm(system, user_msg)

    def generate_quality_check(self, all_content: str) -> str:
        system = self._load_and_format("quality_check.md")
        return call_llm(system, f"# チェック対象のコンテンツ\n\n{all_content}")
