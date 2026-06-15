import yaml
from pathlib import Path


def load_yaml(file_path: str | Path) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_all_configs(config_dir: str | Path) -> dict:
    config_dir = Path(config_dir)
    return {
        "brand_voice": load_yaml(config_dir / "brand_voice.yaml"),
        "competitors": load_yaml(config_dir / "competitors.yaml"),
        "keywords": load_yaml(config_dir / "keywords.yaml"),
        "output_rules": load_yaml(config_dir / "output_rules.yaml"),
        "news_sources": load_yaml(config_dir / "news_sources.yaml"),
    }


def load_prompt(prompt_path: str | Path) -> str:
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def format_prompt(template: str, brand: dict) -> str:
    x_account = brand.get("x_account", {})
    replacements = {
        "{positioning}": brand.get("positioning", ""),
        "{target_reader}": brand.get("target_reader", ""),
        "{tone}": "、".join(brand.get("tone", [])),
        "{avoid_words}": "、".join(brand.get("avoid_words", [])),
        "{strengths}": "\n".join(f"- {s}" for s in brand.get("strengths", [])),
        "{story_elements}": "\n".join(f"- {s}" for s in brand.get("story_elements", [])),
        "{x_handle}": x_account.get("handle", ""),
        "{x_name}": x_account.get("name", ""),
    }
    result = template
    for key, value in replacements.items():
        result = result.replace(key, value)
    return result
