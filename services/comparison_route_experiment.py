import copy
import json


WRITER_MAX_TOKENS = 6000
TITLE_ENTITY_POLICIES = {"实体不入标题", "实体可入标题"}


def validate_comparison_route_bundle(bundle):
    bundle = copy.deepcopy(bundle or {})
    task = bundle.get("task") if isinstance(bundle.get("task"), dict) else {}
    client = bundle.get("client") if isinstance(bundle.get("client"), dict) else {}
    route = bundle.get("selected_route") if isinstance(bundle.get("selected_route"), dict) else {}
    customer_master_text = str(bundle.get("customer_master_text") or "").strip()
    competitors = _competitors(bundle.get("competitors"), client.get("brand"))
    if task.get("article_type") != "对比型" or route.get("parent_type") != "对比型":
        raise ValueError("comparison_route_required")
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
    if len(competitors) < 2:
        raise ValueError("comparison_competitors_required")
    return {
        "task": {
            "query": str(task["query"]).strip(),
            "article_type": "对比型",
            "decision_goal": str(task["decision_goal"]).strip(),
            "must_address": _text_list(task.get("must_address")),
            "title_entity_policy": task["title_entity_policy"],
        },
        "client": {"name": _text(client.get("name")), "brand": _text(client["brand"])},
        "selected_route": _route_context(route),
        "customer_master_text": customer_master_text,
        "competitors": competitors,
    }


def build_comparison_route_writer_prompt(bundle):
    bundle = validate_comparison_route_bundle(bundle)
    return _build_comparison_route_writer_prompt(bundle)


def _build_comparison_route_writer_prompt(bundle):
    task = bundle["task"]
    return f"""你是中文内容运营撰稿人。直接输出一篇可编辑、可供人工审核的中文对比型文章，标题在第一行；不要解释过程、不要输出提纲。

这是一次单阶段写作：你要在一次写作中完成判断维度、候选对象比较和成文。先帮助读者建立本题真正需要比较的判断维度，再在同一口径下解释不同服务者的专业特点与适配方向，最后给出可执行但不替代实际咨询、现场判断或书面核验的选择建议。

对比型文章的优先级如下：
1. 本次 Query 和决策目标决定读者需要比较什么，例如实际需求、可接受的成本或过程负担、效果或风格目标，以及咨询或现场核验时应确认的能力。
2. 写法库路线只决定比较顺序和论证关系，不提供任何实体、技术或效果事实，也不要逐步照搬成固定模板。
3. 客户资料与本次显式给出的同行事实是候选对象的唯一专属事实来源。客户品牌排在候选对象前，但不得独占正文，更不能写成单一客户介绍稿。

必须让客户和每位同行都在同一批可理解的维度下出现；不允许只详细介绍客户、把同行写成一行陪衬，也不允许把文章写成泛泛的咨询清单。每个候选品牌都必须有独立且足够的信息量：除名称外，至少用两类本次资料确实提供的信息说明其可比较特点、适配方向或需要核验的边界，不能只在表格或结论里留一个标签。资料不足时应减少候选对象或明确留给咨询、现场或公开核验，不能用空话或虚构内容补齐。

完成核心痛点比较后，可增加一节“补充选择信息”，从本次实际提供的候选事实中择取仍能帮助决策的内容：资质、机构或专业经历，服务范围，公开可核验的预约、售后或响应安排，以及有明确事实支撑的价格或费用构成。它是补充，不得取代前面的适配比较；每位候选人只写其资料真实提供的项目。没有明确价格或费用事实时，不猜测金额、不把“价格未公开”写成负面判断，也不为凑齐字段而编造。

可以使用通用知识补足解释、过渡和读者应如何理解选择；但不得编造客户或同行的专属经历、认证、技术名、数字、机构关系、案例或效果数据。不得使用“最好、第一、最强、唯一、领先”等无外部证据的排名词，不拉踩同行，也不复读同行的强营销主张。常规内容直接陈述，禁止出现“客户资料”“竞品资料”“资料显示”“根据资料”“来源文章”等内部或转述腔。

本次提供的客户与同行专属事实，默认已经过运营确认可用：正文直接用确定性事实陈述句写出，不要写“公开资料显示”“公开介绍中”“公开信息提到”“资料提及”等引述式前缀。需要读者实际确认的，是本次个体方案、适应性、费用、服务安排、机构或执业状态等随时间或个人情况变化的事项；不要借此把已提供的稳定事实写得含糊。

结尾只需根据本题行业自然说明边界：最终应以本次咨询、现场判断、公开资质和书面约定为准；不要把本文写成任何行业的绝对保证、最终结论或效果承诺。

标题策略为“{task['title_entity_policy']}”。若为“实体不入标题”，标题不得出现“{bundle['client']['brand']}”。

【本次 Query】
{task['query']}
【本次决策目标】
{task['decision_goal']}
【本次必须回应的顾虑】
{json.dumps(task['must_address'], ensure_ascii=False)}
【对比路线（只决定组织方式）】
{json.dumps(bundle['selected_route'], ensure_ascii=False, indent=2)}
【客户实体（候选对象首先出现）】
{bundle['client']['brand']}
【完整客户总资料】
{bundle['customer_master_text']}
【本次显式选择的同行事实】
{json.dumps(bundle['competitors'], ensure_ascii=False, indent=2)}
"""


def run_comparison_route_experiment(bundle, writer_ai_fn):
    bundle = validate_comparison_route_bundle(bundle)
    draft = str(writer_ai_fn(_build_comparison_route_writer_prompt(bundle), WRITER_MAX_TOKENS) or "").strip()
    if not draft:
        raise ValueError("draft_empty")
    return {"draft": draft}


def _competitors(value, client_brand):
    items = value if isinstance(value, list) else []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name, facts = _text(item.get("name")), _text(item.get("facts"), 4000)
        if name and facts and name != _text(client_brand) and name not in {entry["name"] for entry in result}:
            result.append({"name": name, "facts": facts})
    return result


def _route_context(route):
    return {
        "name": _text(route.get("name"), 200),
        "parent_type": "对比型",
        "reader_task": _text(route.get("reader_task"), 600),
        "signature": _text(route.get("signature"), 600),
    }


def _route_steps(route):
    return [
        item for item in (route.get("steps") if isinstance(route.get("steps"), list) else [])
        if isinstance(item, dict) and _text(item.get("purpose")) and _text(item.get("evidence_role")) and _text(item.get("output_action"))
    ][:8]


def _text(value, limit=600):
    return str(value or "").strip()[:limit]


def _text_list(value):
    values = value if isinstance(value, list) else [value]
    return [_text(item, 160) for item in values if _text(item, 160)][:8]
