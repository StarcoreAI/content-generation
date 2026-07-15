DEFAULT_OUTPUT_RULES = """Create a Markdown injection package from reduced customer material.
This is source material for later model use, not a promotional article.
Use only the provided reduced material. Do not browse, reopen files, or invent facts.
Organize repeated or similar content and keep about 3-5 representative entries when needed.
Lightly rewrite wording to be more rigorous and suitable for model injection.
Do not be overly strict: unverified claims may be kept as cautious wording or pending-verification notes.
Downgrade obvious guarantees, absolute promises, and legal-risk wording into careful phrasing or risk notes.
Keep case material as factual bullets, not story copy.
Keep parameter material as summaries, not full catalogs.
Return Markdown only."""


def _material_blocks(reducer_report):
    blocks = []
    for item in reducer_report.get("results", []):
        text = str(item.get("reduced_text") or "").strip()
        if not text:
            continue
        unit_id = str(item.get("unit_id") or "").strip()
        blocks.append(f"=== Reduced Unit ===\nunit_id: {unit_id}\n{text}")
    return blocks


def _build_output_prompt(reducer_report, question):
    package_path = str(reducer_report.get("package_path") or "")
    blocks = _material_blocks(reducer_report)
    return (
        "You are the final Material Output Worker. Turn reduced customer material into a clean Markdown injection package.\n\n"
        f"Package path: {package_path}\n\n"
        f"Rules:\n{question}\n\n"
        "Suggested headings, omit or merge empty sections:\n"
        "# 客户资料注入包\n"
        "## 使用说明\n"
        "## 客户基础信息\n"
        "## 核心业务与服务\n"
        "## 适合人群与使用场景\n"
        "## 可用于内容生成的宣传素材\n"
        "## 案例素材\n"
        "## 参数与政策素材\n"
        "## 表述边界与风险提醒\n"
        "## 待核验信息\n\n"
        + "\n\n".join(blocks)
    )


def build_material_output(reducer_report, ask_text, question=None, max_tokens=8192):
    if ask_text is None:
        raise ValueError("ask_text is required")
    question = str(question or DEFAULT_OUTPUT_RULES).strip()
    if not question:
        raise ValueError("question is required")

    prompt = _build_output_prompt(reducer_report, question)
    markdown = str(ask_text(prompt, max_tokens=max_tokens) or "").strip()
    if not markdown:
        raise ValueError("empty material output")
    return markdown
