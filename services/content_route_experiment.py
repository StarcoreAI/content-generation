import copy
import json
import re


WRITER_MAX_TOKENS = 6000
TITLE_ENTITY_POLICIES = {"实体不入标题", "实体可入标题"}


def validate_content_route_bundle(bundle):
    bundle = copy.deepcopy(bundle or {})
    task = bundle.get("task") if isinstance(bundle.get("task"), dict) else {}
    client = bundle.get("client") if isinstance(bundle.get("client"), dict) else {}
    route = bundle.get("selected_route") if isinstance(bundle.get("selected_route"), dict) else {}
    customer_master_text = str(bundle.get("customer_master_text") or "").strip()
    if task.get("article_type") != "介绍型" or route.get("parent_type") != "介绍型":
        raise ValueError("introduction_route_required")
    if not str(task.get("query") or "").strip():
        raise ValueError("task_query_required")
    if not str(task.get("decision_goal") or "").strip():
        raise ValueError("task_decision_goal_required")
    if task.get("title_entity_policy") not in TITLE_ENTITY_POLICIES:
        raise ValueError("title_entity_policy_invalid")
    if not str(client.get("brand") or "").strip():
        raise ValueError("client_brand_required")
    if not customer_master_text:
        raise ValueError("customer_master_required")
    if not _route_steps(route):
        raise ValueError("route_steps_required")
    headings = _customer_master_sections(customer_master_text)
    if not headings:
        raise ValueError("customer_master_sections_required")
    return {
        "task": {
            "query": str(task["query"]).strip(),
            "article_type": "介绍型",
            "decision_goal": str(task["decision_goal"]).strip(),
            "must_address": _text_list(task.get("must_address"), 160, 8),
            "title_entity_policy": task["title_entity_policy"],
        },
        "client": {
            "name": str(client.get("name") or "").strip(),
            "brand": str(client["brand"]).strip(),
        },
        "selected_route": _library_route_context(route),
        "customer_master_text": customer_master_text,
        "customer_master_sections": headings,
    }


def build_content_route_writer_prompt(bundle):
    bundle = validate_content_route_bundle(bundle)
    return _build_content_route_writer_prompt(bundle)


def _build_content_route_writer_prompt(bundle):
    task = bundle["task"]
    return f"""你是中文内容运营撰稿人。直接输出一篇可编辑、可供人工审核的中文介绍型文章，标题在第一行，不要解释过程、不要输出提纲。

这是一阶段写作：你需要在一次写作中自行完成选材、组织、解释和成文，不存在简报、段落施工单或后续写作 LLM。

介绍型文章的优先级严格如下：
1. 客户总资料是文章主体。先从完整资料中选择一条最值得完整展开的服务、项目、能力或方法主线，并让正文持续围绕它展开。
2. Query 只决定读者进入这条主线的切口：用其中的痛点、场景和顾虑帮助读者理解客户主体，不要把 Query 写成脱离客户主体的通用咨询指南。
3. 写法库脉络只决定组织方式和叙事节奏，不提供文章主体或具体事实，也不要逐步照搬成文章骨架。

客户总资料默认可用。请主动从完整资料中吸收所有与主线有关的具体内容，尽量展开项目或服务的对象、方法、相互关系、适用讨论方向、经历与审美/服务逻辑；不要把丰富资料压缩成“整体评估”“韧带思路”等泛化概念。允许使用通用知识补足解释与过渡，让文章像自然成稿，而非资料摘录或问答清单；但不要编造资料中不存在的客户专属经历、认证、技术名、数字、机构关系或效果数据。

客户特有优势和差异化必须成为正文主干：从客户总资料中识别本题最有辨识度的项目逻辑、技术组合、服务方式、经历或审美方法，逐一大幅说明其具体做法、与读者困扰的连接、以及它们如何共同形成这位客户的服务特点。不要只把差异化名称列成标签后立刻回到泛泛科普。资料没有外部比较证据时，不凭空写成独家、唯一、最好或市场领先；要用具体事实和逻辑让读者理解差异，而不是用排名词替代介绍。

常规的客户服务、流程、定位和项目方向直接用陈述句写，不带来源交代。本次提供的客户专属事实默认已经过运营确认可用：不要写“客户资料显示”“竞品资料显示”“公开资料显示”“公开介绍中”“公开信息提到”“资料提及”等引述式前缀。禁止出现“客户资料”“客户总资料”“资料中”“资料中的”“资料里”“资料显示”“根据资料”“现有资料”“客户自述”等内部或转述腔。客户资料外的一般解释可自然写入，但不能把个体化服务、医疗或效果描述扩展为对所有人适用的保证。

先在开头和主体前半段用客户专属事实建立主线，再用必要的通用解释说明这些事实如何回应本题困扰。不要先写多段脱离客户的症状分类、常识科普或咨询清单，最后才把客户作为一个例子补进来；每一段通用解释都应服务于理解这位客户的具体项目、方法或服务逻辑。

如果 Query 在寻找、推荐或比较医生、机构或服务者，先清楚说明该客户实体及其具体主线为什么和本题相关，再自然展开客户资料。不要用通用面诊清单替代客户介绍，也不要把客户实体写成“仅供沟通的起点”或“需要进一步核验的背景线索”。个体适配、风险、恢复和合规核验只在结尾自然收束一次。

标题策略为“{task['title_entity_policy']}”。若为“实体不入标题”，标题不得出现“{bundle['client']['brand']}”。文章要充分展开，但不为了凑篇幅罗列无关项目、FAQ、竞品或固定模板段。

【本次 Query（只作为读者入口）】
{task['query']}
【本次决策目标】
{task['decision_goal']}
【读者必须被回应的顾虑】
{json.dumps(task['must_address'], ensure_ascii=False)}
【客户实体】
{bundle['client']['brand']}
【写法库脉络（只决定组织方式）】
{json.dumps(bundle['selected_route'], ensure_ascii=False, indent=2)}
【完整客户总资料（文章主体）】
{bundle['customer_master_text']}
"""


def run_content_route_experiment(bundle, writer_ai_fn):
    bundle = validate_content_route_bundle(bundle)
    draft = str(writer_ai_fn(_build_content_route_writer_prompt(bundle), WRITER_MAX_TOKENS) or "").strip()
    if not draft:
        raise ValueError("draft_empty")
    return {"draft": draft}


def _library_route_context(route):
    return {
        "name": _text(route.get("name"), 200),
        "parent_type": "介绍型",
        "reader_task": _text(route.get("reader_task"), 600),
        "signature": _text(route.get("signature"), 600),
    }


def _route_steps(route):
    values = route.get("steps") if isinstance(route.get("steps"), list) else []
    result = []
    for item in values:
        if not isinstance(item, dict):
            continue
        purpose = _text(item.get("purpose"), 400)
        evidence_role = _text(item.get("evidence_role"), 160)
        output_action = _text(item.get("output_action"), 400)
        if purpose and evidence_role and output_action:
            result.append({"purpose": purpose, "evidence_role": evidence_role, "output_action": output_action})
    return result[:8]


def _customer_master_sections(text):
    return list(dict.fromkeys(
        match.group(1).strip()
        for match in re.finditer(r"^##\s+([^#\n]+?)\s*$", text, flags=re.MULTILINE)
        if match.group(1).strip()
    ))


def _text(value, limit):
    return str(value or "").strip()[:limit]


def _text_list(value, item_limit, list_limit):
    values = value if isinstance(value, list) else [value]
    return [_text(item, item_limit) for item in values if _text(item, item_limit)][:list_limit]
