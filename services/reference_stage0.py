import hashlib
import os
import re
from datetime import datetime

from services.reference_qualification import hard_reject_reasons
from services.storage import save_json


SHINGLE_CONTAINMENT_THRESHOLD = 0.8
SHINGLE_WIDTH = 5
SHINGLE_STEP = 1
PROMPT_CONTENT_LIMIT = 12000
STAGE0_MAX_TOKENS = 500
ARTICLE_TYPES = {"对比型", "介绍型", "其他"}


def _text(value, limit=1200):
    return str(value or "").strip()[:limit]


def _normalized_content(content):
    return re.sub(r"\s+", "", str(content or "").lower())


def _shingles(content):
    text = _normalized_content(content)
    if len(text) <= SHINGLE_WIDTH:
        return {text} if text else set()
    return {
        text[index:index + SHINGLE_WIDTH]
        for index in range(0, len(text) - SHINGLE_WIDTH + 1, SHINGLE_STEP)
    }


def _shingle_containment(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _source_metadata(article):
    return {
        "url": _text(article.get("url"), 2000),
        "title": _text(article.get("title") or article.get("source_title"), 300),
        "citation_count": _citation_count(article),
    }


def _citation_count(article):
    try:
        return max(0, int(article.get("citation_count") or 0))
    except (TypeError, ValueError):
        return 0


def _group_id(article):
    content = _normalized_content(article.get("content"))
    return "group_" + hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]


def _group_articles(articles, containment_threshold):
    groups = []
    excluded = []
    for value in articles or []:
        article = dict(value or {})
        reasons = hard_reject_reasons(article)
        if reasons:
            excluded.append({**_source_metadata(article), "reasons": reasons})
            continue
        shingles = _shingles(article.get("content"))
        group = next(
            (item for item in groups if _shingle_containment(item["shingles"], shingles) >= containment_threshold),
            None,
        )
        if group is None:
            group = {"group_id": _group_id(article), "shingles": shingles, "members": []}
            groups.append(group)
        group["members"].append(article)

    for group in groups:
        group["representative_article"] = max(group["members"], key=lambda item: len(str(item.get("content") or "")))
    return groups, excluded


def _group_metadata(group):
    return {
        "group_id": group["group_id"],
        "syndication_count": len(group["members"]),
        "member_urls": [_text(item.get("url"), 2000) for item in group["members"]],
        "representative": _source_metadata(group["representative_article"]),
    }


def group_reference_articles(articles, containment_threshold=SHINGLE_CONTAINMENT_THRESHOLD):
    groups, excluded = _group_articles(articles, containment_threshold)
    return {"groups": [_group_metadata(group) for group in groups], "excluded": excluded}


def build_stage0_prompt(article, syndication_count):
    url = _text(article.get("url"), 2000)
    title = _text(article.get("title") or article.get("source_title"), 300)
    content = _text(article.get("content"), PROMPT_CONTENT_LIMIT)
    return f"""你是 GEO 引用文章准入审核员。这篇文章被 AI 平台高频引用，请判断它是否值得进入写法分析，并做投放定性。你只判断“值不值得学”和“它是谁的内容”，不判断内容真假，不评价文中机构的好坏。

你只能输出 JSON，不要输出 Markdown。字段只能是：
{{
  "article_type": "对比型/介绍型/其他",
  "learnable": true/false,
  "reason": "一句话判定理由",
  "promoted_entity": "文章明显主推的机构或品牌名，没有则留空",
  "risk_marks": ["检测到的风险手段或质量问题，没有则空数组"]
}}

article_type：对比型=多机构多标准比较帮读者选择；介绍型=围绕一个品牌/服务/知识展开，只提一家是正常形态，不算问题。

learnable=true：完整文章，能看出“开头如何进入主题、正文按什么模块组织、结尾如何收束”，且换品牌换事实仍可照做。
learnable=false：学不到可复用写法——关键词堆砌、纯广告落地页、零散卖点无结构、目录/列表页、政策原文转载、行业无关、正文残缺；档案罗列判据：全文除了逐家罗列卖点之外，没有任何实质性决策支架。实质性的标准是“读者能照着执行”：可逐项问出口的核验清单、明确到人群特征的分流建议、具体的选择步骤、覆盖决策疑虑的 FAQ、有判别作用的服务类型划分。一笔带过的“选择时要看资质”“建议多对比”不构成支架。只要有任一实质性支架，即使采用统一维度逐家展开（这是对比型文章的正常形态），也判 true。

介绍型文章的可学判据：有完整且有辨识度的叙事结构，例如“痛点还原→服务交付拆解→成果背书→价值收束”；纯卖点和资质堆叠、无叙事推进的仍判 false。

AI 生成痕迹很浓，且除了统一罗列之外没有独特的结构动作，判 false；有实质性决策支架的照常判 true，把 AI 痕迹写进 risk_marks 即可。

重要：是否投放软文不影响 learnable，投放文往往恰恰结构最完整；风险手段也不影响 learnable，只进 risk_marks。

promoted_entity：写出明显集中主推的机构名。对比型看倾斜（篇幅偏向、独家联系方式、他家陪衬）；介绍型看口吻和结尾落点，不看篇幅。无明显主推（多方平衡、权威/媒体中立）则留空。

risk_marks 只标记不降档：拉踩贬损（含不点名影射）、过度承诺（包过/保录取/100%通过）、情绪化过度营销（恐吓渲染焦虑）、冒充口吻（伪装官方/新闻/测评但无口径）、关键数据无来源、AI 生成痕迹明显（结构仍可学时仅标记）。

拿不准时判 false。本分析会周期性重跑，值得学的套路会在后续批次反复出现，漏判的代价远低于把通用模板收进库。

【文章URL】{url}
【一稿多发铺站数】{syndication_count}
【文章标题】{title}
【文章正文】
{content}
"""


def normalize_stage0_result(raw):
    raw = raw if isinstance(raw, dict) else {}
    article_type = _text(raw.get("article_type"), 20)
    risk_marks = raw.get("risk_marks") if isinstance(raw.get("risk_marks"), list) else []
    return {
        "article_type": article_type if article_type in ARTICLE_TYPES else "其他",
        "learnable": raw.get("learnable") is True,
        "reason": _text(raw.get("reason"), 300),
        "promoted_entity": _text(raw.get("promoted_entity"), 200),
        "risk_marks": [_text(item, 120) for item in risk_marks if _text(item, 120)][:12],
    }


def derive_sponsor(promoted_entity, client_brand):
    entity = re.sub(r"\s+", "", _text(promoted_entity, 200).lower())
    brand = re.sub(r"\s+", "", _text(client_brand, 200).lower())
    if not entity:
        return ""
    return "self" if brand and (entity in brand or brand in entity) else "other"


def analyze_stage0_groups(
    articles,
    *,
    client_brand,
    ai_json_fn,
    stage_dir,
    client_id="",
    date="",
    containment_threshold=SHINGLE_CONTAINMENT_THRESHOLD,
    save_fn=save_json,
):
    groups, excluded = _group_articles(articles, containment_threshold)
    analyses = []
    for group in groups:
        representative = group["representative_article"]
        try:
            result = normalize_stage0_result(ai_json_fn(
                build_stage0_prompt(representative, len(group["members"])),
                STAGE0_MAX_TOKENS,
            ))
            llm_error = False
        except Exception:
            result = {
                "article_type": "其他",
                "learnable": True,
                "reason": "LLM 调用失败，暂按可学习放行",
                "promoted_entity": "",
                "risk_marks": [],
            }
            llm_error = True
        analyses.append({
            **_group_metadata(group),
            **result,
            "sponsor": derive_sponsor(result["promoted_entity"], client_brand),
            "llm_error": llm_error,
        })

    output = {
        "client_id": _text(client_id, 200),
        "date": _text(date, 30),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_groups": len(analyses),
        "total_excluded": len(excluded),
        "groups": analyses,
        "excluded": excluded,
    }
    save_fn(os.path.join(os.fspath(stage_dir), "stage0_filter_groups.json"), output)
    return output
