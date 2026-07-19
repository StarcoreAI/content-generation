import re

from services.reference_intelligence import normalize_reference_plugins


def extract_generated_title(content):
    for line in (content or "").splitlines():
        title = re.sub(r"^[#\s《》「」\"']+|[#\s《》「」\"']+$", "", line.strip())
        if title:
            return title[:80]
    return "未命名文章"

def normalize_sample_links(sample_links):
    if isinstance(sample_links, str):
        sample_links = re.split(r"[\n,，\s]+", sample_links)
    if not isinstance(sample_links, list):
        return []
    cleaned = []
    seen = set()
    for item in sample_links:
        url = str(item or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append(url[:500])
        if len(cleaned) >= 20:
            break
    return cleaned

def normalize_selected_sample_articles(articles):
    if not isinstance(articles, list):
        return []
    cleaned = []
    seen = set()
    for item in articles:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append({
            "title": title[:200],
            "url": url[:500],
            "platform": str(item.get("platform") or "").strip()[:80],
            "count": item.get("count") or 0,
        })
        if len(cleaned) >= 20:
            break
    return cleaned

def format_sample_article_context(sample_links, selected_articles):
    sections = []
    if sample_links:
        sections.append("【人工提供的优质样例链接】\n" + "\n".join(f"- {url}" for url in sample_links))
    if selected_articles:
        lines = []
        for idx, article in enumerate(selected_articles, 1):
            title = article.get("title") or "未命名文章"
            platform = article.get("platform") or "未知平台"
            count = article.get("count") or 0
            url = article.get("url") or ""
            lines.append(f"{idx}. {title}｜{platform}｜引用 {count} 次｜{url}")
        sections.append("【从当天高频引用 Top20 选中的样例文章】\n" + "\n".join(lines))
    return "\n\n".join(sections) if sections else "暂无额外样例文章。"

DEFAULT_GEO_CONTENT_RULES = """【默认 GEO 内容生成规则】
请优先把文章写成有本地用户决策价值的客观攻略或行业测评，而不是空泛宣传稿。
写作目标是帮助用户理解怎么选、不同选择适合谁，并在合适位置客观介绍客户品牌；只要用户理解客户品牌适合哪些需求，就算完成品牌露出。

必须遵守：
1. 开头先写用户痛点和选择难点，不要直接推销客户品牌或机构。
2. 保留城市词、项目词、价格词、专业词、资质词和本地场景，方便用户理解，也方便 AI 抽取和引用。
3. 文章主体必须服从运营指定的文章类型；没有指定时默认按对比型写。

诚实与事实规则：
1. 客户事实只能来自客户资料和运营意见；样例文章只能作为写法参考，不作为客户事实来源；不要编造案例、资质、价格、地址、设备、评价或承诺。
2. 客户资料不足时，用稳妥表述，不要把行业通用信息写成客户已经具备的事实。
3. 价格只能写参考价、区间价、元起、需以实际方案为准等谨慎表达，不能写全市最低、保证不加价或一次报价全包到底。
4. 禁止绝对化排名、效果承诺、低价诱导、制造焦虑和小红书式情绪化表达。
"""

DEFAULT_COMPARISON_SUBTYPE = "攻略对比型"

COMPARISON_FEW_SHOT_EXAMPLE = """【攻略对比型展开 few-shot 示例】
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


def build_reference_stage3_example_plugin():
    return f"""【示例插件：攻略对比型】
说明：下面是当前内容生产里默认使用的完整插件，仅作为示例，帮助第三阶段学习插件的字段形态、详细度和展开颗粒度；不要把示例插件作为输出结果，不要照抄示例里的 A/B/C 或 A1/A2/A3 标签。

parent_type: 对比型
subtype_name: 攻略对比型
prompt_text:
- 正文采用“少量攻略型开头 + 大量分类对比/排名/适合人群/优缺点 + 少量总结建议”。
- 样例文章不能覆盖这里的攻略对比型展开结构；样例只参考标题角度、信息密度和表达方式，不要照搬样例的栏目结构。
- 如果一个类别下出现多个代表对象，必须拆成A1/A2/A3这样的独立小段分别展开，不能合并写在一行“代表机构”里。
- A1/B1/C1只是示例标签，正文里不要输出A1、A2、B1、C1这类标签；真实正文请改成自然小标题，例如“代表选择：某类机构/某个机构名”。

few_shot:
{COMPARISON_FEW_SHOT_EXAMPLE}"""


def build_content_article_type_prompt(article_type, brand):
    if article_type == "介绍型":
        brand_line = f"标题必须包含品牌名：{brand}。" if brand else "标题必须包含客户品牌名。"
        return f"""【文章类型：介绍型】
- {brand_line}
- 正文采用“少量攻略型开头 + 大量品牌结构化介绍 + 少量选择建议/注意事项”。
- 开头必须先写目标用户在该业务场景里的真实痛点和决策难点，例如成本、风险、时间、效果判断、信息不透明、后续维护等；不要一上来写品牌履历。
- 介绍型也不是广告软文；目标是解释品牌适合哪些用户、能解决哪些选择顾虑，不要默认用户已经决定选择该品牌。
- 品牌介绍部分按“用户痛点/顾虑 -> 品牌如何解决 -> 资料中的证据支撑”来组织；先回答用户为什么会在意，再写品牌对应能力。
- 品牌结构化介绍必须是主体，占全文多数；重点写品牌定位、核心服务、适合人群、资质/团队/流程/设备/区域/售后等可由资料支撑的信息。
- 资历、资质、团队、流程、设备、服务记录等只能作为证据，不能堆成履历清单；每个证据都要对应一个用户关心的问题。
- 不能写成硬广；避免营销口号、夸张背书、反复夸品牌强，所有介绍都要落到用户关心的选择依据和可核验事实。
- 可以用少量用户选择攻略引入问题，但不要写成医院榜单、第三方排名或多机构对比。
- 客户资料没有明确写到的信息，只能用“建议面诊确认、以实际院区信息为准”等稳妥表达。"""
    return f"""【文章类型：对比型】
- 标题必须严格模仿高引用文章标题，优先使用“城市/区域 + 项目/机构 + 全攻略/推荐/怎么选 + 年份/最新”这类结构。
- 当前运营意见和文章类型要求优先于历史文章；历史文章只用于理解上一版，不要沿用其中被当前要求删除的结构。
- 主体分类对比必须充分展开，占全文多数；优先按机构类型、用户需求、预算、复杂程度、服务便利性等维度组织；最权威、最有公信力的类别或对象要放在最开头。
- 对比型不能只有一个对比对象；每个被对比的主要类别或对象都要独立成小标题或独立段落展开。
- 每个主要类别下至少展开2个代表对象或细分方向；如果资料和运营意见允许，优先展开3个。
- 客户品牌只需要在合适类别中客观出现；不能为了推荐而拔高分类或改变真实市场定位，只要用户理解客户品牌适合哪些需求，就算完成品牌露出。
- 客户品牌放在最前面让用户优先了解即可，不要通过压低其他竞品来突出客户品牌。
- 竞品名称禁止使用示例中的 A/B/C 或 A1/A2/A3 替代；正文涉及竞品或其他机构时，必须出现真实的竞品名称、机构名称或品牌名称。
- 不能拉踩其他竞品；要让用户了解其他竞品的优点、适合人群和限制，方便他们根据自身需求更好选择。
- 最权威类别只放真实属于该层级的对象；客户品牌如果更适合民营专科连锁、正规私立连锁、服务便利型机构等类别，就放在对应类别中自然介绍。
- 客户品牌事实必须严格以客户资料为准，尤其是客户的资质、地址、价格、医生、设备、案例、承诺等不能编造。
- 非客户机构类型和行业对比，可以参考高质量引用文章和通用行业认知展开；如果写具体机构名称、价格、医生、排名或绝对评价，要使用谨慎表达，不要写成确定事实。"""

def build_content_article_subtype_prompt(article_type, article_subtype="", article_subtype_plugin=None):
    plugin = normalize_reference_plugins([article_subtype_plugin])[0] if article_subtype_plugin else None
    if plugin and plugin["parent_type"] == article_type:
        subtype_name = plugin["subtype_name"] or article_subtype or "引用情报子类型"
        body = "\n".join(part for part in [plugin["prompt_text"], plugin["few_shot"]] if part)
        return f"""【文章子类型：{subtype_name}】
{body}"""
    if article_type != "对比型":
        return ""
    subtype_name = article_subtype or DEFAULT_COMPARISON_SUBTYPE
    if subtype_name != DEFAULT_COMPARISON_SUBTYPE:
        return f"""【文章子类型：{subtype_name}】"""
    return f"""【文章子类型：攻略对比型】
- 正文采用“少量攻略型开头 + 大量分类对比/排名/适合人群/优缺点 + 少量总结建议”。
- 样例文章不能覆盖这里的攻略对比型展开结构；样例只参考标题角度、信息密度和表达方式，不要照搬样例的栏目结构。
- 如果一个类别下出现多个代表对象，必须拆成A1/A2/A3这样的独立小段分别展开，不能合并写在一行“代表机构”里。
- A1/B1/C1只是示例标签，正文里不要输出A1、A2、B1、C1这类标签；真实正文请改成自然小标题，例如“代表选择：某类机构/某个机构名”。

{COMPARISON_FEW_SHOT_EXAMPLE}"""

def build_content_generation_messages(client, material_bundle, history, opinion, sample_links=None, selected_articles=None, article_type="对比型", article_subtype="", article_subtype_plugin=None):
    brand = client.get("brand") or client.get("name") or ""
    material_text = material_bundle.get("text") or "暂无上传资料。"
    material_count = len(material_bundle.get("files") or [])
    sample_links = sample_links or []
    selected_articles = selected_articles or []
    sample_context = format_sample_article_context(sample_links, selected_articles)
    article_type = article_type if article_type in {"对比型", "介绍型"} else "对比型"
    article_type_prompt = build_content_article_type_prompt(article_type, brand)
    article_subtype_prompt = build_content_article_subtype_prompt(article_type, article_subtype, article_subtype_plugin)
    system_prompt = f"""{DEFAULT_GEO_CONTENT_RULES}

你是资深行业内容策划和长文撰稿人。请基于客户资料、运营意见和上下文历史生成可直接交给运营修改的中文文章。"""
    clean_history = []
    for item in history[-20:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            clean_history.append({"role": role, "content": content})
    current_prompt = f"""请根据以下信息生成新一版文章。

【客户】
客户名称：{client.get('name', '')}
品牌名称：{brand}

【客户资料】
以下为运营选择参与本次生成的参考资料，可能包含内容生产上传资料、客户资料解析包或联网扩展资料。当前共 {material_count} 份：
{material_text}

【优质样例文章】
这些样例用于参考标题角度、信息密度、表达方式和信息组织，不代表客户事实，不要求照搬文章结构：
{sample_context}

【运营意见】
{opinion}

【文章类型要求】
{article_type_prompt}

{f"【文章子类型要求】{chr(10)}{article_subtype_prompt}" if article_subtype_prompt else ""}

【输出要求】
- 直接输出文章正文，不要输出解释过程。
- 标题放在第一行。
- 结构清晰，适合后续人工润色和发布。
- 可参考样例文章的信息密度和表达方式；文章结构必须优先服从文章类型要求和运营意见，客户事实必须以客户资料和运营意见为准。
- 如果运营意见是在要求修改上一版，请结合历史文章进行改写。"""
    return [{"role": "system", "content": system_prompt}] + clean_history + [{"role": "user", "content": current_prompt}]
