import json
import re


def extract_generated_title(content):
    for line in (content or "").splitlines():
        title = re.sub(r"^[#\s《》「」\"']+|[#\s《》「」\"']+$", "", line.strip())
        if title:
            return title[:80]
    return "未命名文章"


def build_content_generation_messages(*, client, brief, customer_material_text="", content_upload_text="",
                                      competitor_markdown="", sample=None):
    """Build the writer prompt from the approved construction brief, not legacy templates."""
    sample = sample or {}
    section_instructions = "\n\n".join(
        f"第{item.get('id')}节｜功能：{item.get('功能', '')}\n要点：{item.get('要点', '')}\n引用：{json.dumps(item.get('引用') or [], ensure_ascii=False)}\n展开来源：{json.dumps(item.get('展开来源') or [], ensure_ascii=False)}\n字数预算：{item.get('字数', '')}"
        for item in brief.get("sections") or []
    )
    material_pool = brief.get("素材池")
    material_pool_context = (
        f"【简报素材池】\n{json.dumps(material_pool, ensure_ascii=False, indent=2)}\n"
        if material_pool else ""
    )
    bans = "\n".join(f"- {item}" for item in brief.get("bans") or []) or "- 不得突破资料边界。"
    free_slot = str(sample.get("free_slot") or "").strip()
    free_instruction = "无自由槽位；不得自行改变写法。"
    if free_slot:
        labels = {"opening_module": "开头", "ending_module": "结尾", "body_modules": "正文"}
        free_instruction = f"{labels.get(free_slot, free_slot)}为自由自拟槽位；仅此处允许自拟写法，仍必须服从对应简报节的功能、要点和引用。"
    system_prompt = "你是中文决策指南撰稿人。你只负责把已确认的策划简报施工成文章，不重新决定文章结构、骨架、模块或人群主线。"
    user_prompt = f"""直接输出可编辑的中文文章正文，标题在第一行，不要解释过程。

【写作规则】
1. 语言风格：使用决策指南文风，以结构化判断维度帮助读者选择；价格只可用参考价、区间价、元起、以实际方案为准等稳妥表达。
2. 合规红线：不得拉踩其他机构、不得绝对化或效果承诺；不得使用推荐等级词汇和分档标签，机构介绍顺序不代表排名；禁止出现“占位”“补充位”“待运营补充”“本节保留结构位置”等面向内部流程的文字，简报中的说明性或流程性内容只作写作指导，不得进入正文；其他机构的强主张如确需出现，只能写为“品牌自述，以官方发布为准”。以下 bans 是逐条硬禁令：
{bans}
3. 来源话术分级（硬规则）：常规的服务、流程、定位、覆盖范围等事实直接用陈述句写，不带来源交代；仅品牌自述型数字（通过率、学员数、覆盖省数）、荣誉或强主张必须带“其官网介绍”或“品牌自述，以官方发布为准”话术。禁止逐句交代来源，不要每个事实都加‘官网介绍’。禁止出现“竞品”一词，也禁止出现“客户资料/客户提供资料/竞品资料/资料包/现有资料”等内部工作称谓。指代机构一律使用机构名称或“各机构/其他机构”；信息缺失只能省略该维度，或改写为读者核验动作（如“签约前向机构索取完整收费与退费条款”）；禁止写“未提供”“资料缺失”“待补充”等流程性表述。表格只列有内容可填的维度，禁止用“未提供”填单元格。
4. 定向展开与素材池取用：简报节标注“展开来源”时，必须到【客户资料包】【竞品资料】【内容生产上传资料】的对应小节大量取材、充分展开，把该节写实写透；品牌相关节保底 500 字连贯陈述。素材池条目继续鼓励用足，素材池没覆盖、但展开来源小节里有的内容可以直接用。竞品同样允许大段展开；客户素材只能陈述自身能力与服务，不得写成“与某机构相比更强/更全”的对照句式；不得以“信息更多”暗示品牌更优；未选用素材直接丢弃。禁止成段照抄资料原文，必须按决策指南文风重新组织表述。
5. 事实忠实：只写简报要点、引用、素材池及展开来源小节中可定位到的资料内容；缺失信息严禁编造补齐，不得为任何机构虚构价格、资质、服务承诺；可采用上述读者核验动作，不得补造。竞品强主张只能带“品牌自述，以官方发布为准”话术或不写。读者核验或签约提醒类句子每节最多 1-2 处，不得用核验、免责类句子替代实质内容。

【简报标题候选】
{json.dumps(brief.get('title_candidates') or [], ensure_ascii=False)}

【人群主线】
{brief.get('angle_statement') or ''}

【简报逐节施工指令】
{section_instructions}

{material_pool_context}
【去重提示】
{brief.get('dedup_hints') or ''}

【组合提醒】
{brief.get('combo_warning') or '无'}

【自由槽位指令】
{free_instruction}

【客户】
名称：{client.get('name', '')}
品牌：{client.get('brand') or client.get('name') or ''}

【客户资料包】
{customer_material_text or '未提供'}

【内容生产上传资料】
{content_upload_text or '未提供'}

【竞品资料】
{competitor_markdown or '未提供'}
"""
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
