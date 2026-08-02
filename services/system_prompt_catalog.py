"""Safe, read-only views of the product's runtime prompt templates."""
from services.content_route_generation import build_content_route_messages
from services.competitor_materials import build_upload_competitor_prompt
from services.material_filter import DEFAULT_FILTER_RULES, _build_package_prompt
from services.material_output import DEFAULT_OUTPUT_RULES, _build_output_prompt
from services.material_reducer import DEFAULT_REDUCER_RULES, _build_reducer_prompt
from services.reference_route_analysis import build_route_analysis_prompt


def _content_prompt(article_type):
    bundle = {
        "task": {"query": "{{本次 Query}}", "article_type": article_type, "title_entity_policy": "实体不入标题"},
        "client": {"brand": "{{客户品牌}}", "name": "{{客户名称}}"},
        "route": {
            "id": "{{路线 ID}}", "name": "{{写法库路线}}", "parent_type": article_type,
            "reader_task": "{{读者决策任务}}", "signature": "{{路线特征}}", "risk_notes": "{{适用边界}}",
            "steps": [{"purpose": "{{步骤目的}}", "evidence_role": "{{证据角色}}", "output_action": "{{输出动作}}"}],
        },
        "customer_facts": "{{客户资料}}",
        "content_uploads": "{{运营显式选择的上传资料}}",
        "competitors": ([
            {"name": "{{竞品一}}", "facts": "{{竞品一资料}}"},
            {"name": "{{竞品二}}", "facts": "{{竞品二资料}}"},
        ] if article_type == "对比型" else []),
        "scene_terms": ["{{场景词}}"],
        "supplementary_scene_terms": [{"query": "{{同组问题}}", "scene_terms": ["{{可选场景词}}"]}],
    }
    messages = build_content_route_messages(bundle)
    return "[System]\n" + messages[0]["content"] + "\n\n[User template]\n" + messages[1]["content"]


def _material_unit():
    return {"unit_id": "{{资料单元 ID}}", "path": "{{资料文件路径}}", "text": "{{资料正文}}"}


def list_system_prompts():
    """Return only fixed templates filled with neutral placeholders, never live data."""
    unit = _material_unit()
    return [
        {
            "id": "content-introduction", "category": "内容生产", "name": "介绍型内容生成",
            "description": "介绍型文章的完整运行提示，客户、路线和场景均使用占位符。",
            "content": _content_prompt("介绍型"),
        },
        {
            "id": "content-comparison", "category": "内容生产", "name": "对比型内容生成",
            "description": "对比型文章的完整运行提示，含竞品资料占位符。",
            "content": _content_prompt("对比型"),
        },
        {
            "id": "material-filter", "category": "客户资料解析", "name": "客户资料解析",
            "description": "客户资料包的第一阶段筛选提示。",
            "content": _build_package_prompt([unit], DEFAULT_FILTER_RULES, 300),
        },
        {
            "id": "material-reducer", "category": "客户资料解析", "name": "客户资料精简",
            "description": "客户资料包的第二阶段删减提示。",
            "content": _build_reducer_prompt([unit], DEFAULT_REDUCER_RULES),
        },
        {
            "id": "material-output", "category": "客户资料解析", "name": "客户资料汇总",
            "description": "将保留事实归并为客户资料知识库的提示。",
            "content": _build_output_prompt({"package_path": "{{资料包路径}}", "results": [{"unit_id": "{{资料单元 ID}}", "reduced_text": "{{保留事实}}"}]}, DEFAULT_OUTPUT_RULES),
        },
        {
            "id": "competitor-upload", "category": "竞品资料解析", "name": "竞品资料解析",
            "description": "将上传资料按真实竞品实体整理的提示。",
            "content": build_upload_competitor_prompt(["{{竞品名称}}"], [unit]),
        },
        {
            "id": "reference-route-analysis", "category": "引用情报", "name": "引用文章路线分析",
            "description": "从引用文章提取可核验证据与可复用写法路线的提示。",
            "content": build_route_analysis_prompt(
                {"query": "{{本次 Query}}", "final_entities": ["{{实体名称}}"]},
                {"title": "{{文章标题}}", "content": "{{文章正文}}", "support_points": ["{{人工核对要点}}"]},
            ),
        },
    ]
