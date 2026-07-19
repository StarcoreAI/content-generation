DEFAULT_OUTPUT_RULES = """Create a Markdown injection package from reduced customer material.
This is source material for later model use, not a promotional article.
Use only the provided reduced material. Do not browse, reopen files, or invent facts.
Organize repeated or similar content and keep up to 6 representative entries when needed.
Lightly rewrite wording to be more rigorous and suitable for model injection.
Organize the output by the eight customer-material directions in the suggested headings.
For each direction, first summarize what exists in the material. If the material does not contain it, do not invent it; add a short item under 缺口与检索提示.
For target audiences and demand pain points, inferred content is allowed only when clearly marked as “推断，待确认”.
For core advantages, separate material-supported claims from customer self-description. Do not treat slogans as advantages.
For price and fee wording, keep only the original wording. Do not calculate, complete, convert, or infer prices.
For trust credentials, note source nature when available: 客户自述 or 第三方可查.
List absolute wording, effect promises, unsupported numbers, guarantees, rankings, and similar risky claims under 合规风险表述 as “限制使用”; do not rewrite them into facts.
Use 缺口与检索提示 for missing public-checkable items, third-party proof, customer-to-provide evidence, and official-source public background needs.
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
        "Use these headings. Keep empty directions as a short “暂无资料” line and put missing items under 缺口与检索提示:\n"
        "# 客户资料注入包\n"
        "## 使用说明\n"
        "## 1. 品牌基础\n"
        "目标：主体名称、正规性、成立时间与背景、所在地与覆盖范围、业务范围。\n"
        "缺口处理：主体、资质类信息缺失时，登记公开可查的检索提示，例如工商注册、备案、官网。\n"
        "## 2. 产品与服务\n"
        "目标：提供什么、怎么交付、服务流程和深度、售后与长期服务能力。把散落服务细节归拢成可复述流程，不拔高。\n"
        "## 3. 核心优势\n"
        "目标：差异点及其支撑。区分“资料有支撑”和“仅是客户说法”，不要把口号当优势。\n"
        "## 4. 目标人群与需求痛点\n"
        "目标：谁在用、解决什么问题、决策顾虑、典型使用场景。资料推不出来时可写推断，但必须标注“推断，待确认”。\n"
        "## 5. 价格与费用表达\n"
        "目标：资料中已有的价格区间、费用构成、表达口径。只保留资料原有表述，不推算、不补全、不换算。\n"
        "## 6. 信任凭证\n"
        "目标：资质、荣誉、案例、用户评价、第三方背书。逐条注明出处性质：客户自述 / 第三方可查。\n"
        "## 7. 合规风险表述\n"
        "目标：绝对化用语、效果承诺、无法证实的数字，例如“包过”“第一”“XX% 通过率”。单独列出并标记“限制使用”，不要混入正文整理。\n"
        "## 8. 行业公共背景\n"
        "目标：资料中已有且与客户业务相关的政策、时间节点、公共数据。内容生产明显需要但资料没有的，登记官方来源优先的检索提示。\n"
        "## 缺口与检索提示\n"
        "资料中没有的，不要编造；按公开可查、需客户提供、限制使用三类登记。\n\n"
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
