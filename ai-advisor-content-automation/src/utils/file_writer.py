from datetime import date
from pathlib import Path


def get_output_path(outputs_dir: str | Path, target_date: date | None = None) -> Path:
    if target_date is None:
        target_date = date.today()
    outputs_dir = Path(outputs_dir)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir / f"{target_date.isoformat()}_daily_content.md"


def write_daily_report(output_path: Path, sections: dict[str, str]) -> Path:
    target_date = output_path.stem.split("_")[0]
    lines = [
        f"# AI顧問コンテンツ日次レポート\n",
        f"日付：{target_date}\n",
    ]
    for title, content in sections.items():
        lines.append(f"## {title}\n")
        lines.append(content)
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
