DEFAULT_OUTPUT_RULES = """Create a Markdown injection package from reduced customer material.
This is a customer fact layer for later model use, not a promotional article.
Use only the provided reduced material. Do not browse, reopen files, or invent facts.
Only retain customer-specific, directly stateable facts. Organize repeated or similar content and keep up to 6 representative entries when needed.
只保留客户专属、可直接陈述的事实。
Use only these six directions: brand and service entity; products and services; unique methods and service logic; service targets and fit boundaries; prices and fees; trust and verifiable information.
For unique methods and service logic, retain the concrete process, resources, mechanism, or service detail that supports the distinction. Do not turn slogans into facts.
For service targets and fit boundaries, retain only explicit customer-specific suitability, service scope, or boundary facts; do not infer generic pain points, scenes, or decision advice.
For prices and fees, keep only original wording; do not calculate, complete, convert, or infer prices.
Do not output usable angles, writing directions, article structure, templates, FAQs, user scenes, example queries, customer-service scripts, generic industry background, public education, risk advice, or market facts.
Do not output sources, source labels, search hints, pending-verification notes, restrictions, or missing-information explanations.
不得输出可用角度。不得输出行业现象。不得输出来源或待核验说明。
Keep case and parameter material as concise factual bullets, not story copy or catalogs.
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
        "Use exactly these headings. Omit a heading when there is no supported fact for it; do not add a placeholder or any extra section.\n"
        "# 客户内容资料\n"
        "## 品牌与服务主体\n"
        "主体名称、所在地区、服务范围、业务身份等已有事实。\n"
        "## 产品与服务\n"
        "提供什么，以及已有的交付或服务流程事实。\n"
        "## 特有方法与服务逻辑\n"
        "客户特有的方法、技术、流程、资源配置或服务机制；必须有资料支撑。\n"
        "## 服务对象与适配边界\n"
        "客户明确服务谁、适合什么情况、服务范围或边界；不能从行业常识推断。\n"
        "## 价格与费用\n"
        "资料已有的价格、费用构成或收费口径。\n"
        "## 信任与可核验信息\n"
        "客户自身的资质、组织、案例、荣誉或可核验服务事实。\n\n"
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
