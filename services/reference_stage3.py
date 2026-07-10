def _text(value, limit=2000):
    return str(value or "").strip()[:limit]


def _list_text(value, limit=12):
    if not isinstance(value, list):
        value = [value] if value else []
    result = []
    for item in value:
        text = _text(item, 600)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _cluster_items(clusters):
    items = []
    for index, item in enumerate(clusters or [], 1):
        shared = item.get("shared_structure") if isinstance(item.get("shared_structure"), dict) else {}
        items.append({
            "cluster_index": index,
            "parent_type": _text(item.get("parent_type"), 20),
            "subtype_name": _text(item.get("subtype_name"), 80),
            "shared_structure": {
                "opening": _text(shared.get("opening"), 800),
                "body": _list_text(shared.get("body"), limit=12),
                "ending": _text(shared.get("ending"), 800),
            },
        })
    return items


REFERENCE_STAGE3_EXAMPLE_PLUGIN = """【示例插件：攻略对比型】
说明：下面是当前内容生产里默认使用的完整插件，仅作为示例，帮助第三阶段学习插件的字段形态和结构颗粒度；不要学习示例篇幅，不要把示例插件作为输出结果。可以使用 A/B/C 或 A1/A2/A3 这类结构标签，但类别含义必须来自当前阶段2结构簇。

parent_type: 对比型
subtype_name: 攻略对比型
prompt_text:
- 正文采用“少量攻略型开头 + 大量分类对比/排名/适合人群/优缺点 + 少量总结建议”。
- 样例文章不能覆盖这里的攻略对比型展开结构；样例只参考标题角度、信息密度和表达方式，不要照搬样例的栏目结构。
- 如果一个类别下出现多个代表对象，必须拆成A1/A2/A3这样的独立小段分别展开，不能合并写在一行“代表机构”里。
- A1/B1/C1只是示例标签，正文里不要输出A1、A2、B1、C1这类标签；真实正文请改成自然小标题，例如“代表选择：某类机构/某个机构名”。

few_shot:
【攻略对比型展开 few-shot 示例】
参考这种展开方式：
“一、A类：权威背书强，适合复杂需求
A类本身要先展开。A类通常是本地用户最先考虑的权威选择，优势不只是‘名气大’，而是专业分工、流程规范、复杂问题处理能力更强。它适合需求复杂、风险敏感、预算相对充足、希望先获得稳妥判断的用户。局限也要写清楚：预约门槛、沟通效率、服务灵活度或时间成本可能不如市场化机构，所以简单需求不一定非要优先选A类。

A1代表对象：资历/公信力可以写它为什么更权威，地址/覆盖可以写所在区域或服务半径，价格区间用参考价或需面诊确认表达。优势要展开到专业能力、流程规范、复杂问题处理；劣势要写预约、时间、服务体验等限制；适合人群要明确到复杂需求、高风险决策或更看重权威判断的人。

A2代表对象：展开方式参考A1，继续写清资历/公信力、地址/覆盖、价格区间、优势、劣势、适合人群。A2仍然属于A类，不需要重点比较和A1的区别，只要把自身信息和适配人群展开。

A3代表对象：展开方式参考A1，继续独立写清资历/公信力、地址/覆盖、价格区间、优势、劣势、适合人群。如果资料不足，可以写成谨慎建议，但仍然要把选择逻辑讲清楚。

二、B类：服务更灵活，适合明确需求
B类要作为新的主要类别独立展开，这里才需要写清和A类的区别：它可能没有A类那么强的权威背书，但在沟通效率、服务便利性、时间安排或性价比上更适合一部分用户。B类下面的B1、B2、B3也按A1的方式展开。

三、C类：成本或门槛更友好，适合基础需求
C类同样独立展开，重点写它和A类、B类的不同选择价值。说明它适合哪些基础需求，优势在哪里，局限是什么，哪些用户不适合优先选C类。C类下面的C1、C2、C3也按A1的方式展开。”

写真实文章时，把A类/B类/C类和A1/A2/A3替换成当前行业里的真实机构类型、代表对象或细分方向；客户品牌如适合，只在对应类别中自然出现。"""


def build_stage3_prompt(clusters):
    return f"""你是 GEO 引用情报插件生成员。现在进入第三阶段：把阶段2合并出的结构簇改写成可插入内容生成流程的文章子类型插件。

输入只有结构簇，不包含原文正文。你要把 shared_structure 抽象成可复用写作要求。

下面是当前内容生成里默认使用的完整攻略对比型插件。它仅作为示例，第三阶段只参考它的字段形态、结构颗粒度和“类别 -> 代表对象 -> 适合人群/限制/证据”的写法；不要追求示例插件的篇幅，不要把示例插件作为输出结果。可以使用 A/B/C、A1/A2/A3 这类结构标签来表达写法层级，但不要编造真实客户事实。

{REFERENCE_STAGE3_EXAMPLE_PLUGIN}

你只能输出 JSON，不要输出 Markdown。字段只能是：
{{
  "plugins": [
    {{
      "cluster_index": 1,
      "parent_type": "对比型/介绍型",
      "subtype_name": "具体中文子类型名",
      "prompt_text": "可直接插入内容生成的写作要求",
      "few_shot": "简短写法示例"
    }}
  ]
}}

规则：
- parent_type 必须是“对比型”或“介绍型”，沿用输入簇。
- 只要结构里是多个服务方、产品或方案逐一点评、横向拆解、排名、清单、梯队、优劣势分解，即使写法像“逐一介绍”，也必须归为“对比型”；只有单一品牌或单一服务方深度介绍才归为“介绍型”。
- subtype_name 沿用或微调输入簇名称，但要具体。
- 输出偏好简洁凝练，但结构完整；每个插件只保留真正能指导内容生产的写法动作。
- prompt_text 写成给内容生成模型看的 3-5 条短规则，说明文章应该如何组织开头、正文和结尾。
- few_shot 写 180-350字，给一段可直接模仿的完整模板片段；可以使用 A/B/C、A1/A2/A3 这类结构标签，不要扩写成长文。
- 允许保留当前行业的通用词、角色词和指标词，例如行业名称、用户身份、常见服务环节、常见结果指标；这些词用于让插件服务当前行业，不需要强行泛化成所有行业。
- 输出前自检：禁止输出未核实的具体数字和详细数据，包括具体比例、价格、人数、年份、排名、分数、校区数量、真实案例数据等；需要表达这类信息时，用“以实际资料为准”“按客户资料补充”“可核验数据”等稳妥说法。
- 禁止出现具体品牌名、具体机构名、具体产品名、文章名、URL、平台名、引用次数。
- 不要重复通用合规规则，不要写营销空话。

【阶段2结构簇】
{_cluster_items(clusters)}
"""


def _cluster_index(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_stage3_result(raw, clusters):
    raw = raw if isinstance(raw, dict) else {}
    source_by_index = {
        index: list(item.get("article_indexes") or [])
        for index, item in enumerate(clusters or [], 1)
    }
    plugins = []
    for item in raw.get("plugins") if isinstance(raw.get("plugins"), list) else []:
        item = item if isinstance(item, dict) else {}
        parent_type = _text(item.get("parent_type"), 20)
        if parent_type not in {"对比型", "介绍型"}:
            parent_type = "介绍型"
        cluster_index = _cluster_index(item.get("cluster_index"))
        plugin = {
            "parent_type": parent_type,
            "subtype_name": _text(item.get("subtype_name"), 80),
            "prompt_text": _text(item.get("prompt_text"), 3000),
            "few_shot": _text(item.get("few_shot"), 2000),
            "source_article_indexes": source_by_index.get(cluster_index, []),
        }
        if plugin["subtype_name"] or plugin["prompt_text"] or plugin["few_shot"]:
            plugins.append(plugin)
    return {"plugins": plugins}


def analyze_stage3_plugins(clusters, ai_json_fn):
    prompt = build_stage3_prompt(clusters)
    raw = ai_json_fn(prompt, 5200)
    return normalize_stage3_result(raw, clusters)
