"""Single-call GEO content generation from an explicit route and selected facts."""
import copy
import json


WRITER_MAX_TOKENS = 6000
PARENT_TYPES = {"介绍型", "对比型"}
TITLE_ENTITY_POLICIES = {"实体不入标题", "实体可入标题"}


def validate_generation_bundle(bundle):
    bundle = copy.deepcopy(bundle or {})
    task = bundle.get("task") if isinstance(bundle.get("task"), dict) else {}
    client = bundle.get("client") if isinstance(bundle.get("client"), dict) else {}
    route = bundle.get("route") if isinstance(bundle.get("route"), dict) else {}
    article_type = task.get("article_type")
    if article_type not in PARENT_TYPES or route.get("parent_type") != article_type:
        raise ValueError("route_article_type_mismatch")
    query = str(task.get("query") or "").strip()
    brand = str(client.get("brand") or "").strip()
    if not query:
        raise ValueError("task_query_required")
    if not brand:
        raise ValueError("client_brand_required")
    if task.get("title_entity_policy") not in TITLE_ENTITY_POLICIES:
        raise ValueError("title_entity_policy_invalid")
    if not isinstance(route.get("steps"), list) or not route["steps"]:
        raise ValueError("route_steps_required")
    customer_facts = str(bundle.get("customer_facts") or "").strip()
    uploads = str(bundle.get("content_uploads") or "").strip()
    if article_type == "介绍型" and not (customer_facts or uploads):
        raise ValueError("introduction_material_required")
    competitors = _competitors(bundle.get("competitors"), brand)
    scene_terms = _scene_terms(bundle.get("scene_terms"))
    supplementary_scene_terms = _supplementary_scene_terms(bundle.get("supplementary_scene_terms"))
    if article_type == "介绍型" and competitors:
        raise ValueError("introduction_competitors_forbidden")
    if article_type == "对比型":
        if not customer_facts:
            raise ValueError("comparison_customer_facts_required")
        if len(competitors) < 2:
            raise ValueError("comparison_competitors_required")
    return {
        "task": {
            "query": query, "article_type": article_type,
            "title_entity_policy": task["title_entity_policy"],
        },
        "client": {"brand": brand, "name": str(client.get("name") or "").strip()},
        "route": _route_context(route),
        "customer_facts": customer_facts,
        "content_uploads": uploads,
        "competitors": competitors,
        "scene_terms": scene_terms,
        "supplementary_scene_terms": supplementary_scene_terms,
    }


def build_content_route_messages(bundle):
    bundle = validate_generation_bundle(bundle)
    if bundle["task"]["article_type"] == "介绍型":
        instruction = _introduction_instruction(bundle)
    else:
        instruction = _comparison_instruction(bundle)
    return [
        {"role": "system", "content": "你是严谨、自然的中文内容运营撰稿人。"},
        {"role": "user", "content": instruction},
    ]


def generate_content_route_draft(bundle, writer_ai_fn):
    messages = build_content_route_messages(bundle)
    draft = str(writer_ai_fn(messages, WRITER_MAX_TOKENS) or "").strip()
    if not draft:
        raise ValueError("empty_content_generation_response")
    return draft


def route_context(bundle):
    clean = validate_generation_bundle(bundle)
    return {
        "parent_type": clean["task"]["article_type"],
        "route_id": clean["route"]["id"],
        "route_name": clean["route"]["name"],
        "query": clean["task"]["query"],
        "material_switches": {
            "use_customer_master": bool(clean["customer_facts"]),
            "use_content_uploads": bool(clean["content_uploads"]),
        },
        "competitor_names": [item["name"] for item in clean["competitors"]],
    }


def _route_context(route):
    steps = []
    for step in route.get("steps") or []:
        if not isinstance(step, dict):
            continue
        values = {key: str(step.get(key) or "").strip()[:500] for key in ("purpose", "evidence_role", "output_action")}
        if all(values.values()):
            steps.append(values)
    if not steps:
        raise ValueError("route_steps_required")
    return {
        "id": str(route.get("id") or "").strip(),
        "name": str(route.get("name") or "").strip()[:200],
        "parent_type": route.get("parent_type"),
        "reader_task": str(route.get("reader_task") or "").strip()[:600],
        "steps": steps[:8],
        "signature": str(route.get("signature") or "").strip()[:600],
        "risk_notes": str(route.get("risk_notes") or "").strip()[:500],
    }


def _competitors(value, brand):
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        facts = str(item.get("facts") or "").strip()
        if name and facts and name != brand and name not in {entry["name"] for entry in result}:
            result.append({"name": name, "facts": facts[:6000]})
    return result


def _scene_terms(value):
    terms = []
    for item in value if isinstance(value, list) else []:
        term = str(item or "").strip()
        if term and term not in terms:
            terms.append(term[:80])
    return terms


def _supplementary_scene_terms(value):
    groups = []
    used_terms = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        terms = []
        for raw in item.get("scene_terms") if isinstance(item.get("scene_terms"), list) else []:
            term = str(raw or "").strip()
            if term and term not in used_terms:
                terms.append(term[:80])
                used_terms.add(term)
        if query and terms:
            groups.append({"query": query[:300], "scene_terms": terms})
    return groups


def _shared_rules(bundle):
    title_rule = (
        f"介绍型标题必须直接出现客户品牌“{bundle['client']['brand']}”。"
        if bundle["task"]["article_type"] == "介绍型"
        else f"标题策略为“{bundle['task']['title_entity_policy']}”。若为“实体不入标题”，标题不得出现“{bundle['client']['brand']}”。"
    )
    supplementary_scene_section = ""
    if bundle["supplementary_scene_terms"]:
        supplementary_scene_section = f"""
【同问题组可选场景词】
{json.dumps(bundle['supplementary_scene_terms'], ensure_ascii=False, indent=2)}
当前 Query 仍是唯一主线。可自然吸收确实有助于回答本题的场景词；若不相关可以完全不用。不得为了覆盖其他 Query 而堆词、罗列词语、另起问题或偏离当前 Query。
"""
    return f"""直接输出一篇可编辑、可供人工审核的中文{bundle['task']['article_type']}文章，标题在第一行；不要解释过程、不要输出提纲。

这是一次单阶段写作：自行完成选材、组织、解释和成文，不存在简报、段落施工单或后续写作 LLM。
写法库路线只决定组织方式和论证节奏，不提供实体、技术或效果事实，也不要逐步照搬成固定模板。
运营提供的稳定专属事实可以直接用确定性陈述句写出。禁止出现“客户资料显示”“竞品资料显示”“公开资料显示”“公开介绍中”“公开信息提到”“资料提及”“根据资料”等内部或转述腔。
允许使用通用知识补足解释和过渡，但不得编造任何实体专属经历、认证、技术名、数字、机构关系、案例或效果数据；不得写“最好、第一、最强、唯一、领先”等无依据排名词。
个人适配、费用、实际服务安排、机构或执业状态等随人或时间变化的事项，只在结尾自然提示以实际咨询、现场判断、公开核验和书面约定为准。
{title_rule}

【本次 Query】
{bundle['task']['query']}
【本次 Query 对应场景词（轻量提醒）】
{'、'.join(bundle['scene_terms']) or '无已整理场景词。'}
场景词只用于帮助理解 Query 的具体困扰、场景或决策偏好：可在开头或正文相关位置自然吸收一部分；不要求覆盖全部，也不得为凑词牺牲行文、虚构事实或写成关键词堆砌。
【写法库路线（只决定组织方式）】
{json.dumps(bundle['route'], ensure_ascii=False, indent=2)}
{supplementary_scene_section}
"""


def _introduction_instruction(bundle):
    return _shared_rules(bundle) + f"""
介绍型优先级：客户专属事实是文章主体，Query 是读者进入这条主线的切口。先根据 Query 和写法库路线确定一条连贯的读者判断主线，再将它拆成 3—4 个相互递进的判断点；不要写成脱离客户主体的泛化科普或咨询清单，也不要只围绕一条客户事实从头写到底。
围绕本次 Query 相关的多组客户事实形成足够的信息密度：不要只用一两条事实收尾，应将与主线直接相关的产品、方法、服务动作、资源配置、适配边界或可核验信息选择性展开。客户专属事实通常以条目形式提供，而不是最终成稿句子；可以将同一组相关条目重组、扩写为完整段落，写清其实际含义、与本题的关系以及读者为什么需要关心，不能只逐条改写或罗列。
当客户资料未覆盖理解本题所需的读者需求、常见场景、判断逻辑、概念解释或段落过渡时，可以自由使用通用知识补足；但不得把这些补充写成客户独有的能力、经历、技术、数字、认证、案例或效果。段落之间应以明确的承接、递进、因果或转折关系自然衔接，使下一段是在推进上一段的判断，而不是切换到另一份资料目录；无关事实不要硬塞。
正文使用 3—4 个自然的小标题承载这些判断点，小标题应由本次 Query 推导出的读者问题或结论组成，不使用固定模板措辞。每个小标题下可以有一至数段：把能共同回答这一判断点的客户事实归并展开，不要让每一类客户资料各自成为一个孤立段落；段与段之间要说明它们为什么属于同一个判断，或为什么需要顺势进入下一项判断。
客户特有优势和差异化必须是正文主干：大幅解释其具体做法、与本题困扰的连接、以及如何共同形成服务特点。不要把差异化名称列成标签后立刻回到泛泛科普。

【客户实体】
{bundle['client']['brand']}
【客户专属事实】
{bundle['customer_facts'] or '本次未选择客户总资料。'}
【运营显式选择的内容上传资料】
{bundle['content_uploads'] or '本次未选择内容上传资料。'}
"""


def _comparison_instruction(bundle):
    return _shared_rules(bundle) + f"""
对比型优先级：Query 决定比较维度。先帮助读者建立真正需要比较的判断维度，再在同一口径下解释客户与不同同行的专业特点和适配方向，最后给出可执行的选择建议。
开头应围绕本次 Query 自由建立读者的判断语境：可按需要解释关键困扰、常见误区、选择逻辑或必要背景，并自然引出后续比较；不要只用几句泛泛提醒便进入品牌罗列。
在文章的集中比较区域，先按本次 Query 提炼 2—4 个真正影响选择的比较维度，用一小段或一个小标题说明读者为什么要看这些维度；随后按候选对象逐家展开。每个候选对象均使用“名称 + 适合什么情况”的独立二级小标题，并在标题下用完整段落展开，不要把一家机构的资料写完后才临时切换到下一家，也不要写成资料目录或一行标签。
客户品牌排在候选对象前，但不得独占正文。每个候选对象除名称外，都至少使用两类本次资料确实提供的信息说明可比较特点、适配方向或需要核验的边界；不能只写一行标签，也不能用空话或虚构信息补齐。核心比较后可从实际资料补充资质、经历、服务范围或售后响应。价格不是某对象的核心优势或本次 Query 的核心决策点时，不要主动提及价格、费用构成、收费提醒或泛化的价格比较；只有资料明确表明其构成关键差异，或 Query 明确关心价格时，才简洁、准确地写入。

【客户实体】
{bundle['client']['brand']}
【客户专属事实】
{bundle['customer_facts']}
【本次显式选择的同行事实】
{json.dumps(bundle['competitors'], ensure_ascii=False, indent=2)}
【运营显式选择的内容上传资料】
{bundle['content_uploads'] or '本次未选择内容上传资料。'}
"""
