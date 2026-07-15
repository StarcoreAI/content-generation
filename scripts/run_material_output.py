import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_entities import get_openai_client, read_json
from services.material_output import build_material_output


def choose_material_output_model(settings):
    return (
        settings.get("material_output_model")
        or settings.get("material_reducer_model")
        or settings.get("material_filter_model")
        or settings.get("model")
        or settings.get("extraction_model")
        or "deepseek-chat"
    )


def make_ask_text(settings, model=None):
    client = get_openai_client(settings)
    model = model or choose_material_output_model(settings)

    def ask_text(prompt, max_tokens):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    return ask_text


def build_output_for_report(reducer_report, ask_text, max_tokens=8192):
    try:
        return build_material_output(reducer_report, ask_text=ask_text, max_tokens=max_tokens), []
    except Exception as exc:
        return "", [{"unit_id": "__package__", "path": "", "error": str(exc)}]


def default_output_path(reducer_report):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    package_path = str(reducer_report.get("package_path") or "material-output")
    safe_name = "".join(ch if ch.isalnum() else "-" for ch in Path(package_path).name).strip("-")
    return Path("reports") / f"material_injection_{safe_name}_{timestamp}.md"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Run the customer material Output Worker.")
    parser.add_argument("reducer_report", help="Material reducer report JSON path")
    parser.add_argument("--settings", default="data/settings.json", help="Model settings JSON")
    parser.add_argument("--output", default="", help="Markdown output path")
    parser.add_argument("--max-tokens", type=int, default=8192, help="Max output tokens for the material output call")
    args = parser.parse_args()

    reducer_report = read_json(args.reducer_report, {})
    settings = read_json(args.settings, {})
    model = choose_material_output_model(settings)
    markdown, errors = build_output_for_report(reducer_report, make_ask_text(settings, model), args.max_tokens)

    output = Path(args.output) if args.output else default_output_path(reducer_report)
    output.parent.mkdir(parents=True, exist_ok=True)
    if errors:
        markdown = "# 客户资料注入包\n\n## 生成错误\n\n- " + errors[0]["error"] + "\n"
    output.write_text(markdown, encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Markdown chars: {len(markdown)}")
    if errors:
        print(f"Output errors: {len(errors)}")


if __name__ == "__main__":
    main()
