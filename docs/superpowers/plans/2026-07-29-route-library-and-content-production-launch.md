# 行业写法库与单阶段内容生产正式上线计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用“行业完整写作路线 + 显式资料选择 + 单次写作 LLM”正式替换当前模块化写法库与“抽样 → 简报 LLM → 写作 LLM”内容生产模式，同时彻底删除人群角度、FAQ 和旧简报链路。

**Architecture:** 知识库新增独立的“行业写法库”知识类型。它只按行业隔离，并在库内明确分为`介绍型`与`对比型`两组；每条条目是一条完整路线，并附带可回原文核对的来源证据。它不保存客户事实、竞品事实、Query 原话或零散开头/结尾/FAQ 模块，也不物理混入客户资料或竞品资料。内容生产仍统一从 `app.run_content_generation(...)` 进入：运营显式选择客户总资料、内容上传资料和（仅对比型）至少两位竞品资料；系统按本次文章类型从行业写法库的对应组抽样，再由一次写作 LLM 直接成文，质量门禁只产生提醒并照常保存。

**Tech Stack:** Python 标准库、Flask、SQLite、现有 `app.ai` / `app.ai_json`、`unittest`、现有前端原生 JavaScript。

## 当前实施状态（2026-07-29）

已完成并通过针对性测试：

- 客户资料解析已收口为六类客户专属事实；联网补充不再自动合并；已提供“预览候选事实层 → 运营确认覆盖”的迁移后端，未确认旧资料不能注入新内容生产。
- 已建立 `ContentRouteLibrary`：只按行业存储完整路线，数据层已有 `介绍型` / `对比型` 标识；来源节选可回原文核对；内容生产抽样不会拿到来源正文。下一步应将它以“行业写法库”的独立分区纳入知识库界面，并完成已确认的直接可用状态收口。
- 已建立 `content_route_analysis`：只接收运营确认、已有正文的实际精读文章；不自动抓取、不模拟平台检索过程；正式页面可以手工提交文章、创建候选路线或合并到既有路线。
- `app.run_content_generation(...)` 已只接受正式请求：显式客户事实/内容上传资料、对比型至少两位手选竞品、行业路线抽样、一次写作 LLM、质量提醒和 `route_context_json` 记录。网页单篇与批量请求均走这一条路径。
- 内容生产页已移除旧选择项入口，改为 Query、资料开关和竞品多选；引用情报页已改为手工确认精读文章入口。
- SQLite 已完成无损迁移：保留文章正文、版本关系、批次、门禁和 `route_context_json`，物理删除 `article_subtype`、`brief_json`、`provenance_json`。

遗留生产源文件已清理完成：正式运行路径、页面入口和数据库字段均已切换；旧 `PatternLibrary`、旧自动引用情报任务、旧简报/选择模块及对应开发脚本已物理删除，正式 API 与内容生产均不可调用。历史测试中的作废断言仅作为跳过项保留，不能为它们恢复旧产品语义。`data/pattern_library/` 是既有历史数据，不参与任何正式读取，除非运营明确确认不再需要，否则不物理删除。

## Global Constraints

- 所有用户可见文本使用简体中文。
- 只保留 `介绍型` 与 `对比型` 两个父类型；不恢复文章子类型、开头/结尾模块、FAQ 模块或模板拼装。
- 写法库作用域只能是 `industry:<行业>`；不得读取或创建 `client:<客户ID>`、`global` 写法库条目。
- 知识库中的内容资料分为三种彼此独立的知识类型：客户资料（客户级）、竞品资料（客户级且独立于客户资料）、行业写法库（行业级）。行业写法库界面必须分栏或分组展示`介绍型`与`对比型`；不得把两种路线混排后由运营猜测用途。
- 行业写法库的路线、来源证据和退役状态只服务写作组织方式；它不是客户事实库，也不能因为显示在知识库中而自动注入任何一次内容生产。
- 引用情报分析只处理运营已确认、已取得正文的“实际精读文章”；本期不自动抓取、猜测、重建或声称获得平台真实精读列表。
- 客户知识库、竞品知识库不自动注入内容生产。每次生成必须由运营显式选择资料来源；竞品资料保持独立于客户资料。
- 对比型必须由运营显式选择至少两位不同竞品；不得自动抽取、随机补齐或按客户 ID 推断竞品。
- 介绍型以客户资料为主体，Query 是切入点，路线只决定论证顺序；对比型由 Query 决定比较维度，客户与每个竞品必须在同一批维度中有足够信息量。
- 写作 prompt 不写“客户资料显示”“竞品资料显示”“公开资料显示”“公开介绍中”“资料提及”等转述腔；运营提供的稳定专属事实直接陈述。个体方案、费用、实际服务安排、机构或执业状态仍应提示以实际咨询、现场判断、公开核验和书面约定为准。
- 新增或保留的 LLM 调用 `max_tokens >= 4000`；正式内容成文仅一次写作调用，使用 `6000`。
- 质量门禁只有“通用 + 行业”两层，全部为提醒；不得阻止生成、保存、批量任务继续或后续发布操作。
- 网页单篇、批量 job、CLI 继续复用 `app.run_content_generation(...)`；不改爬虫、知识库整理、记录库、发布链路。
- 客户级读写继续越权 404；写法库行业条目对无权客户不可借由 API 或生成接口读取。
- 当前工作区存在无关改动；施工时只提交本计划明确列出的文件，且只有用户明确要求时才 commit/push。

---

## 1. 正式产品契约

### 1.1 行业路线条目

每条正式条目使用以下结构，不再使用 `skeleton`、`module` 或 `checklist`：

```json
{
  "id": "route_<uuid>",
  "industry": "医美",
  "parent_type": "介绍型",
  "name": "面部松弛分层与低创提升决策路线",
  "reader_task": "帮助读者完成的抽象判断任务",
  "steps": [
    {
      "purpose": "本步解决什么",
      "evidence_role": "需要哪类来源证据",
      "output_action": "文章如何呈现"
    }
  ],
  "signature": "整条路线的区分特征",
  "risk_notes": "适用边界或空字符串",
  "sources": [
    {
      "url": "https://example.com/article",
      "title": "来源标题",
      "source_evidence": [
        {"role": "决策框架", "finding": "忠实概括", "excerpt": "可在原文连续找到的节选"}
      ]
    }
  ],
  "evidence_count": 1,
  "created_at": "2026-07-29 00:00:00",
  "updated_at": "2026-07-29 00:00:00"
}
```

路线没有`candidate`、`active`、`retired`或其他状态字段：运营确认文章可入库后，路线即参与同类型内容生产；不再需要时直接删除。追加独立来源只用于累积可核对证据，不改变路线是否可用。写作层只接收路线字段，不接收 `sources`、URL、标题、节选或文章正文。

### 1.2 正式生成请求

```json
{
  "client_id": "客户ID",
  "query": "本次运营填写的 Query",
  "article_type": "介绍型",
  "use_customer_master": true,
  "use_content_uploads": false,
  "selected_competitor_names": []
}
```

- `use_customer_master`、`use_content_uploads` 都是显式布尔开关；未选即不读取相应资料。
- 介绍型要求至少一个客户资料来源被选中，`selected_competitor_names` 必须为空。
- 对比型要求 `use_customer_master=true` 且 `selected_competitor_names` 是至少两个不同真实名称；每个名称必须对应已选择的竞品资料章节。
- 路线父类型与 `article_type` 必须一致。文章类型是运营当前任务的明确选择，不从 Query 自动猜测。

### 1.3 新文章记录上下文

新字段 `route_context_json` 只记录可审计但不复制资料正文的上下文：

```json
{
  "parent_type": "对比型",
  "route_id": "route_<uuid>",
  "route_name": "统一评价后按需求验证的服务商选择路线",
  "material_switches": {"use_customer_master": true, "use_content_uploads": false},
  "competitor_names": ["筑祥装饰", "朗通装饰"]
}
```

不保存旧简报、模块组合、人群角度、FAQ 问题、来源文章正文或竞品事实全文。

### 1.4 客户内容资料必须是“事实层”，不是策划手册

`data/knowledge_base/<cid>/customer_master.md` 调整为运营维护的**客户专属事实层**，也是内容生产在勾选 `use_customer_master=true` 时唯一读取的客户知识库文件。它只保留以下六类可直接陈述的内容：

1. 品牌/服务主体与明确服务范围；
2. 产品、服务、方法、交付流程与专属技术名；
3. 客户特有优势的具体做法与服务逻辑；
4. 已明确的服务对象、适配范围或边界；
5. 已明确的价格、费用构成或不提供价格这一客观状态；
6. 可核验的任职、资质、认证、机构关系、地址、服务能力和售后安排。

以下内容从客户资料解析产物和 `customer_master.md` 中彻底移出，不得作为客户事实交给写作 LLM：

- “行业现象/用户顾虑”“可用角度”“可写素材方向”“推荐写法”“内容模板”“可扩展为”等策划文字；
- 通用 FAQ、典型用户语境、场景词、示例 Query、客服话术、面诊提问清单；
- 通用行业公共背景、法律/指南摘要、第三方媒体科普、市场规模、行业比较或其他主体评价；
- “来源于客户资料解析/AI 联网补充”“原始资料未提供”“需进一步核验”“网页有软文特征”等来源、审计和不确定性说明；
- 没有客户专属证据的通用合规流程、恢复护理、风险教育、费用提醒与发布建议。

原始资料包、联网补充、来源追溯与人工编辑记录继续保留在资料模块。客户资料解析不再把场景词合并到客户内容资料；但内容生产会按本次 Query 精确读取记录库中已整理的场景词，作为轻量语境提醒：可在开头或正文相关位置自然吸收一部分，不要求覆盖全部，也不得为了凑词牺牲写作质量。通用行业说明如确有文章价值，只能由运营作为“内容上传资料”显式选择。

由于现有 `customer_master.md` 是人工可编辑资产，迁移不得静默用 LLM 改写或覆盖。系统先生成“待替换的事实层草稿”与逐段删除清单，运营确认后才覆盖当前总资料；未确认客户继续使用旧资料但内容生产页显示“客户内容资料尚未完成事实层迁移”，禁止将旧总资料自动注入新内容生产。

## 2. 必须删除的旧内容

以下内容不是“停用后保留兼容”，而是在新链路验收后从代码、API、页面、客户端 JSON 与 SQLite 结构中删除：

| 删除对象 | 删除原因 | 替代物 |
| --- | --- | --- |
| `services/brief_builder.py` | 旧写法库拼骨架/模块并调用简报 LLM | `services/content_route_library.py` 的完整路线抽样 + 单阶段写作 |
| `services/content_prompts.py` | 依赖旧 `brief` 的写作 prompt | `services/content_route_generation.py` 的介绍型/对比型写作 prompt |
| `services/content_choices.py` | 人群角度、FAQ、竞品随机池选择 | 运营一次性 Query；对比型手工选择竞品 |
| `services/pattern_library.py` | `skeleton/module/checklist` 旧条目模型和 client/global scope | `services/content_route_library.py` 的行业路线模型 |
| `services/reference_anatomy.py`、`services/reference_ingest.py` | 把文章拆成骨架、开头、结尾、FAQ 与清单的旧引用沉淀方式 | `services/content_route_analysis.py` 的“来源证据 + 完整路线”分析 |
| `services/content_route_experiment.py`、`services/comparison_route_experiment.py` 与两个 `scripts/dev_*_route_experiment.py` | 实验实现不能与正式实现并行漂移 | 正式服务及正式 API/CLI；实验稿只作为人工对照文件保留在 `C:\tmp` |
| `audience_angles`、`faq_questions` 客户字段及懒生成函数 | 不建设问题库/问法库；旧资产会误导写作 | Query + `must_address` 的一次性任务语境 |
| `competitor_rules` 的 must-use/banned/随机池语义 | 对比对象必须由运营显式选择，不能静默随机 | `selected_competitor_names` |
| 内容生产页“人群角度”“FAQ 问题”“竞品规则”配置区 | 对应资产和自动化已删除 | 介绍型资料开关、对比型竞品多选与资料预览 |
| `brief_json`、`provenance_json`、`article_subtype` SQLite 列和记录库展示 | 旧两阶段与子类型资产不可再解释新文章 | `route_context_json`；保留文章正文、版本关系、批次与门禁报告 |
| `data/pattern_library/` 与 `data/content_generation_diagnostics/*/latest_planning_brief.json` | 旧条目和简报诊断不可被新链路消费 | `data/content_route_library/`；来源证据随路线条目保存 |
| 客户总资料中的策划、行业公共、场景词、来源/审计与待确认段落 | 不是客户专属事实，会稀释客户主线并诱导资料转述腔 | 原始资料模块、按当前 Query 轻量注入的记录库场景词、运营显式内容上传资料 |

旧文章正文、标题、创建时间、版本关系、批次、人工修改记录和质量门禁报告保留；删的是旧生成中间物与旧选择资产，不删内容成品。

---

### Task 0: 先把客户资料解析收口为可写的客户事实层

**Files:**

- Modify: `services/material_reducer.py`
- Modify: `services/material_output.py`
- Modify: `services/knowledge_base.py`
- Modify: `app.py`（客户资料整理、知识库 API、内容资料读取）
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Create: `tests/test_customer_content_facts.py`
- Modify: `tests/test_material_reducer.py`
- Modify: `tests/test_knowledge_base.py`

**Interfaces:** `build_material_output(reducer_report, ask_text, question=None, max_tokens=8192)` 的默认规则改为只产出六类客户专属事实；`validate_customer_content_facts(markdown)` 返回可否用于内容生产及逐段错误；`prepare_customer_fact_migration(cid, package_dir)` 返回基于 `latest_injection.md` 的待替换草稿和删除清单，但不写盘；`confirm_customer_fact_migration(cid, reviewed_markdown)` 只在运营确认后覆盖 `customer_master.md`。

- [ ] **Step 1: 写失败测试：解析 prompt 拒绝策划和通用行业内容。**

```python
def test_customer_content_facts_prompt_forbids_strategy_and_generic_background(self):
    self.assertIn("只保留客户专属、可直接陈述的事实", DEFAULT_OUTPUT_RULES)
    self.assertIn("不得输出可用角度", DEFAULT_OUTPUT_RULES)
    self.assertIn("不得输出行业现象", DEFAULT_OUTPUT_RULES)
    self.assertIn("不得输出场景词", DEFAULT_OUTPUT_RULES)
    self.assertIn("不得输出来源或待核验说明", DEFAULT_OUTPUT_RULES)
```

- [ ] **Step 2: 写失败测试：混入策划段落的总资料不能作为新内容生产输入。**

```python
def test_customer_content_facts_validation_rejects_editorial_sections(self):
    markdown = "## 产品/服务\n\n双韧焕颜提升。\n\n## 可用角度\n\n后续可写成咨询入口。"
    result = validate_customer_content_facts(markdown)
    self.assertFalse(result["usable_for_generation"])
    self.assertIn("可用角度", result["forbidden_headings"])
```

- [ ] **Step 3: 运行失败测试。**

Run: `python -X utf8 -m unittest tests.test_customer_content_facts -v`  
Expected: FAIL，因为事实层构建与校验尚不存在。

- [ ] **Step 4: 实现事实层输出、资料来源收口与校验。**

修改 `DEFAULT_REDUCER_RULES`：保留客户身份、服务、流程、客户专属方法、明确价格、资质和服务边界；删除“用户场景/痛点/推断”“行业公共背景”“缺口与检索提示”“来源性质”“限制使用”“客户待确认”及代表性案例/话术的保留要求。修改 `DEFAULT_OUTPUT_RULES` 和 `_build_output_prompt`，只允许固定六标题：`品牌与服务主体`、`产品与服务`、`特有方法与服务逻辑`、`服务对象与适配边界`、`价格与费用`、`信任与可核验信息`。每个段落只写客户专属事实；没有事实的标题直接省略，不以通用知识补齐。

在 `KnowledgeBaseService` 中把 `CUSTOMER_SECTIONS` 改为这六标题，`CUSTOMER_SOURCES` 只读取 `latest_injection.md`；`latest_web_supplement.md` 继续作为可追溯的联网补充文件存在，但不再合并进客户内容资料。`validate_customer_content_facts` 拒绝第 1.4 节列出的禁用标题和标记语，并要求至少有“品牌与服务主体”或“产品与服务”之一。

- [ ] **Step 5: 实现人工确认迁移，禁止静默覆盖。**

`prepare_customer_fact_migration` 从最新 `latest_injection.md` 读取事实层候选内容，并把现有 `customer_master.md` 中命中的禁用标题和标记语列为删除清单；它不调用 LLM、不写文件。页面展示旧资料、候选事实层和删除清单；只有运营提交审核后的完整 Markdown 到 `confirm_customer_fact_migration` 才覆盖。未完成迁移的客户在内容生产页显示明确状态，`use_customer_master=true` 返回 `customer_content_facts_migration_required`。

- [ ] **Step 6: 运行资料与越权回归。**

Run: `python -X utf8 -m unittest tests.test_customer_content_facts tests.test_material_reducer tests.test_knowledge_base -v`  
Expected: PASS；跨客户查看、准备迁移、确认迁移均为 404；来源更新仍不得覆盖人工确认后的事实层。

---

### Task 1: 建立行业完整路线存储，并迁移旧写法库文件

**Files:**

- Create: `services/content_route_library.py`
- Create: `tests/test_content_route_library.py`
- Modify: `app.py`（`pattern_library_service`、写法库 API、权限判断）
- Modify: `templates/index.html`（写法库字段和操作文案）
- Modify: `static/js/app.js`（路线列表、详情、审批操作）
- Delete after migration: `services/pattern_library.py`
- Delete after migration: `tests/test_pattern_library.py`
- Delete after migration: `tests/test_import_pattern_seeds.py`
- Delete after migration: `data/pattern_library/`
- Create at runtime: `data/content_route_library/<行业安全文件名>.json`

**Interfaces:** `ContentRouteLibrary.list_routes(industry)` 返回路线条目列表；`create_route(industry, route, source)` 直接创建路线；`add_source(industry, route_id, source)` 追加独立来源；`delete_route(industry, route_id)` 直接删除路线；`sample_route(industry, parent_type, excluded_route_ids)` 返回不含来源证据的路线副本。

- [ ] **Step 1: 写失败测试：只接受行业作用域与完整路线。**

```python
def test_candidate_requires_industry_parent_type_steps_and_verified_source(self):
    with tempfile.TemporaryDirectory() as tmp:
        library = ContentRouteLibrary(Path(tmp))
        route = {"parent_type": "介绍型", "name": "主线", "reader_task": "任务", "steps": [{"purpose": "p", "evidence_role": "e", "output_action": "o"}], "signature": "特征"}
        source = {"url": "https://example.com/a", "title": "A", "source_evidence": [{"role": "框架", "finding": "说明", "excerpt": "连续原文节选至少二十个非空白字符"}]}
        entry = library.create_candidate("医美", route, source)
        self.assertEqual(entry["status"], "candidate")
        self.assertEqual(entry["industry"], "医美")
        with self.assertRaisesRegex(ValueError, "industry_required"):
            library.create_candidate("", route, source)
```

- [ ] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_content_route_library.ContentRouteLibraryTests.test_candidate_requires_industry_parent_type_steps_and_verified_source -v`  
Expected: FAIL，因为 `ContentRouteLibrary` 尚不存在。

- [ ] **Step 3: 实现最小存储。**

实现 `ContentRouteLibrary`，只允许 `介绍型` / `对比型` 和 `candidate` / `active` / `retired`。`source_evidence` 的每个 `excerpt` 必须是 20–240 个非空白字符；`add_source` 用规范化 URL 去重，并在第二个不同 URL 加入后把 candidate 改为 active。`sample_active` 只在本行业、同父类型、非排除 ID 的 active 路线中随机抽一条；空集合抛 `missing_active_route`。

- [ ] **Step 4: 写失败测试：来源不会混入路线。**

```python
def test_sample_returns_route_without_source_evidence(self):
    route = library.sample_active("装修", "对比型", set())
    self.assertNotIn("sources", route)
    self.assertNotIn("source_evidence", json.dumps(route, ensure_ascii=False))
```

- [ ] **Step 5: 实现抽样投影并运行测试。**

`sample_active` 返回仅含 `id`、`parent_type`、`name`、`reader_task`、`steps`、`signature`、`risk_notes` 的副本。  
Run: `python -X utf8 -m unittest tests.test_content_route_library -v`  
Expected: PASS。

- [ ] **Step 6: 迁移与删除旧库。**

旧 `skeleton/module/checklist` 没有可恢复的完整路线，不转换为新 candidate。删除旧服务、种子导入脚本及对应测试，正式代码不得保留 fallback 读取；`data/pattern_library/` 仅作为只读历史数据保留，待运营明确确认不再需要后再单独删除。

### Task 2: 将引用情报改为“来源证据 + 完整路线”入库

**Files:**

- Create: `services/content_route_analysis.py`
- Create: `tests/test_content_route_analysis.py`
- Modify: `services/reference_intelligence.py`
- Modify: `app.py`（引用情报运行器与写法库 API）
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Delete after replacement: `services/reference_anatomy.py`
- Delete after replacement: `services/reference_ingest.py`
- Delete after replacement: `tests/test_reference_anatomy.py`
- Delete after replacement: `tests/test_reference_ingest.py`
- Delete after replacement: `services/reference_route_analysis.py`
- Delete after replacement: `tests/test_reference_route_analysis.py`

**Interfaces:** `analyze_content_route_article(bundle, article, ai_json_fn)` 返回一篇文章的分类、已验证来源证据与完整路线；`normalize_content_route_analysis_result(raw, article_content)` 负责把不可核对输出降级为不入库；`ingest_content_route_analysis(analysis, industry, library)` 只写入合格路线。

- [ ] **Step 1: 写失败测试：分析结果只能形成介绍型、对比型或不入库。**

```python
def test_analysis_verifies_excerpt_and_returns_complete_route_only(self):
    result = analyze_content_route_article(bundle, article, fake_ai_json)
    self.assertEqual(result["classification"], "对比型")
    self.assertTrue(result["source_evidence"][0]["excerpt_verified"])
    self.assertEqual(result["route"]["parent_type"], "对比型")
    self.assertNotIn("开头", json.dumps(result["route"], ensure_ascii=False))
    self.assertNotIn("FAQ", json.dumps(result["route"], ensure_ascii=False))
```

- [ ] **Step 2: 运行失败测试。**

Run: `python -X utf8 -m unittest tests.test_content_route_analysis.ContentRouteAnalysisTests.test_analysis_verifies_excerpt_and_returns_complete_route_only -v`  
Expected: FAIL，因为正式分析服务尚不存在。

- [ ] **Step 3: 实现分析与入库。**

沿用实验中已验证的 JSON 纪律：输入只接受运营提供的 Query、文章 URL、标题、正文和辅助要点；输出必须有可在正文连续匹配的 `excerpt`，否则降级为 `不入库`。route 禁止写入本次实体、地域、年份、价格、技术专名、Query 原话及来源事实。`ingest_content_route_analysis` 只把合格结果写到 `industry:<行业>` 的新路线库；同路线的相似判定由 LLM 在明确的“现有路线摘要 + 新路线”输入中完成，来源证据仍保留各自 URL。

- [ ] **Step 4: 写失败测试：没有来源正文或节选无法匹配时不写库。**

```python
def test_unverified_excerpt_is_not_ingested(self):
    result = normalize_content_route_analysis_result(raw, article_content="不含模型节选")
    self.assertFalse(result["library_decision"]["eligible"])
    self.assertIsNone(result["route"])
```

- [ ] **Step 5: 替换 `reference_intelligence.py` 的 stage1/stage2 调用并运行测试。**

保留其抓取预检、同稿归并和运营审批入口；删除“文章解剖卡、骨架、模块、可引用特征、种子模块”分支。  
Run: `python -X utf8 -m unittest tests.test_content_route_analysis tests.test_reference_stage0 tests.test_reference_qualification -v`  
Expected: PASS。

- [ ] **Step 6: 更新引用情报页面。**

页面每篇显示：分类、来源证据、完整路线、candidate/active/retired 状态和来源数；删除“骨架、模块、清单、开头、结尾、FAQ、种子”列与操作。运营手动批准只改变状态，不改写来源证据。

### Task 3: 用正式单阶段服务替换介绍型与对比型实验服务

**Files:**

- Create: `services/content_route_generation.py`
- Create: `tests/test_content_route_generation.py`
- Modify: `app.py`（`run_content_generation` 与 `_run_content_generation`）
- Delete after replacement: `services/content_route_experiment.py`
- Delete after replacement: `services/comparison_route_experiment.py`
- Delete after replacement: `scripts/dev_content_route_experiment.py`
- Delete after replacement: `scripts/dev_comparison_route_experiment.py`
- Delete after replacement: `tests/test_content_route_experiment.py`
- Delete after replacement: `tests/test_comparison_route_experiment.py`
- Delete after replacement: `services/brief_builder.py`
- Delete after replacement: `services/content_prompts.py`
- Delete after replacement: `tests/test_brief_builder.py`
- Delete after replacement: `tests/test_dev_brief_builder.py`
- Delete after replacement: `tests/test_content_prompts.py`
- Delete after replacement: `tests/test_person_competitors.py`

**Interfaces:** `WRITER_MAX_TOKENS = 6000`；`validate_route_generation_input(payload, client, route, customer_master_text, content_upload_text, competitors)` 返回已规范化 bundle；`build_introduction_writer_prompt(bundle)` 与 `build_comparison_writer_prompt(bundle)` 返回写作 prompt；`generate_route_content(bundle, writer_ai_fn)` 返回含 `draft` 正文的字典。

- [ ] **Step 1: 写失败测试：介绍型只用客户事实和路线。**

```python
def test_introduction_prompt_centers_customer_facts_without_source_tone(self):
    prompt = build_introduction_writer_prompt(valid_introduction_bundle())
    self.assertIn("客户总资料是文章主体", prompt)
    self.assertIn("先在开头和主体前半段用客户专属事实建立主线", prompt)
    self.assertIn("不要写“客户资料显示”", prompt)
    self.assertNotIn("competitor", prompt.lower())
    self.assertNotIn("sources", prompt)
```

- [ ] **Step 2: 写失败测试：对比型拒绝自动竞品与信息不足对象。**

```python
def test_comparison_requires_two_explicit_competitors_with_two_fact_categories(self):
    bundle = valid_comparison_bundle()
    bundle["competitors"] = [{"name": "甲", "facts": "只有一句事实"}]
    with self.assertRaisesRegex(ValueError, "comparison_competitors_required"):
        validate_route_generation_input(bundle)
```

同时测试生成 prompt 包含“每个候选品牌至少用两类本次资料确实提供的信息”，并禁止“公开资料显示”“竞品资料显示”。

- [ ] **Step 3: 运行失败测试。**

Run: `python -X utf8 -m unittest tests.test_content_route_generation -v`  
Expected: FAIL，因为正式单阶段服务尚不存在。

- [ ] **Step 4: 实现最小单阶段服务。**

介绍型 prompt 固定优先级为“客户事实主线 → Query 切口 → 路线组织”；要求客户独有方法、服务逻辑或经历形成连续解释链，通用解释只能服务于该主线。对比型 prompt 固定优先级为“Query 决定维度 → 路线组织 → 客户与显式竞品事实”；客户第一个出现但不独占，每位候选对象至少有两类可用信息或明确减少对象。两类 prompt 都不传来源证据、写法库 URL、旧简报、FAQ、人群角度或内部资料名称。

`generate_route_content` 只调用一次 `writer_ai_fn(prompt, 6000)`，空结果抛 `draft_empty`。

- [ ] **Step 5: 把 `app._run_content_generation` 改为正式调用点。**

移除 `ensure_content_generation_choices`、`build_brief_sample`、`generate_planning_brief`、`build_content_generation_messages`、简报诊断 ContextVar 和 `avoid_skeleton_opening_pairs` 参数。按显式开关读取资料，按文章父类型从 `ContentRouteLibrary.sample_active` 抽路线，构造正式 bundle 并调用 `generate_route_content`。不得新建第二条网页、批量或 CLI 写作入口。

- [ ] **Step 6: 运行单元与现有入口回归。**

Run: `python -X utf8 -m unittest tests.test_content_route_generation tests.test_dev_content_generate tests.test_batch_generation -v`  
Expected: PASS；断言一篇生成只发生一次 writer 调用，且所有调用 token 数为 `6000`。

### Task 4: 删除人群角度、FAQ 与自动竞品规则，并收口显式资料选择

**Files:**

- Modify: `app.py`（客户创建/更新、内容选择 API、内容生成 API、批量预处理）
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `services/content_generations.py`
- Modify: `tests/test_content_generation_ui.py`
- Modify: `tests/test_dev_content_generate.py`
- Modify: `tests/test_batch_generation.py`
- Delete: `services/content_choices.py`
- Delete: `tests/test_content_choices.py`

- [ ] **Step 1: 写失败测试：新 API 不接受旧字段，且对比型必须显式提交竞品名。**

```python
def test_generation_api_rejects_legacy_choices_and_requires_explicit_comparison_names(self):
    response = client.post("/api/content/generate", json={
        "client_id": client_id, "query": "怎么选", "article_type": "对比型",
        "use_customer_master": True, "selected_competitor_names": [],
        "audience_angles": ["旧字段"], "faq_questions": ["旧字段"],
    })
    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.get_json()["error"], "comparison_competitors_required")
```

- [ ] **Step 2: 运行失败测试。**

Run: `python -X utf8 -m unittest tests.test_dev_content_generate.ContentGenerateTests.test_generation_api_rejects_legacy_choices_and_requires_explicit_comparison_names -v`  
Expected: FAIL，因为旧 API 仍接受选择资产。

- [ ] **Step 3: 删除旧字段和 API。**

从客户创建/更新及 `F_CLIENTS` 规范化逻辑删除 `audience_angles`、`faq_questions`、`competitor_rules`。删除懒生成 prompt、`ensure_content_generation_choices`、`load_client_faq_questions`、`normalize_audience_angles`、`/api/clients/<cid>/content-choices` 的读写语义，以及 `select_competitor_names` 的随机选择。客户端历史 JSON 中这三个键在启动迁移时 `pop` 掉并写回；不得以隐藏字段形式保留。

- [ ] **Step 4: 实现内容生产页的新交互。**

保留客户、Query、文章父类型、客户总资料开关、内容上传资料开关与竞品资料总开关。介绍型隐藏竞品选择；对比型展示竞品资料中真实 `##` 名称的复选列表，未选满两项时禁用生成按钮并显示“对比型至少选择两位可用竞品”。提交 JSON 只含第 1.2 节字段。页面不出现“人群角度”“FAQ”“随机池”“必须用/禁止用竞品”。

- [ ] **Step 5: 运行 UI/API 回归。**

Run: `python -X utf8 -m unittest tests.test_content_generation_ui tests.test_dev_content_generate tests.test_batch_generation -v`  
Expected: PASS；越权客户请求仍为 404。

### Task 5: 迁移 SQLite 记录，并删除旧中间物

**Files:**

- Modify: `services/content_generations.py`
- Modify: `tests/test_content_generations_store.py`
- Modify: `app.py`（文章保存、详情读取、版本修改、质量门禁调用）
- Modify: `templates/index.html`
- Modify: `static/js/app.js`

- [ ] **Step 1: 写失败测试：新记录只有路线上下文，没有旧简报/溯源/子类型。**

```python
def test_store_round_trip_uses_route_context_not_legacy_generation_fields(self):
    store.append_generation(client_id, {
        "id": "a1", "title": "标题", "content": "正文", "article_type": "介绍型",
        "route_context": {"route_id": "route_1", "route_name": "介绍路线"},
    }, {}, {"role": "assistant", "content": "正文"})
    article = store.load_session(client_id)["articles"][0]
    self.assertEqual(article["route_context"]["route_id"], "route_1")
    self.assertNotIn("brief", article)
    self.assertNotIn("provenance", article)
    self.assertNotIn("article_subtype", article)
```

- [ ] **Step 2: 运行失败测试。**

Run: `python -X utf8 -m unittest tests.test_content_generations_store.ContentGenerationStoreTests.test_store_round_trip_uses_route_context_not_legacy_generation_fields -v`  
Expected: FAIL，因为表仍是旧列。

- [ ] **Step 3: 实现 SQLite 重建迁移。**

在事务中执行：创建 `content_articles_new`，列为 `id, client_id, sequence, title, content, model, material_count, article_type, created_at, parent_id, root_id, batch_id, route_context_json, gate_report_json, generation_status, modify_instruction`；从旧表复制同名保留列，`route_context_json` 写 `NULL`；删除旧表并把新表重命名为 `content_articles`，重建客户排序索引。迁移前后的文章行数必须相等，不相等时回滚并抛 `content_article_migration_count_mismatch`。删除 `article_subtype`、`brief_json`、`provenance_json`，不保留兼容读取。

- [ ] **Step 4: 删除简报诊断落盘和历史页面入口。**

删除 `planning_brief_diagnostic_context`、`planning_brief_diagnostic_path`、`save_planning_brief_diagnostic` 及 `data/content_generation_diagnostics/`。文章详情改显示“本次路线、资料开关、已选竞品、质量提醒”，不显示简报、模块组合、FAQ 或人群角度。

- [ ] **Step 5: 运行存储与版本回归。**

Run: `python -X utf8 -m unittest tests.test_content_generations_store tests.test_dev_content_generate tests.test_quality_gate -v`  
Expected: PASS；旧 SQLite fixture 迁移后文章正文、版本关系、批次和门禁报告仍可读取。

### Task 6: 让质量门禁消费新上下文，并保持只提醒

**Files:**

- Modify: `services/quality_gate.py`
- Modify: `tests/test_quality_gate.py`
- Modify: `app.py`
- Modify: `tests/test_dev_quality_gate_review.py`

- [ ] **Step 1: 写失败测试：门禁 prompt 不再需要简报或旧溯源。**

```python
def test_gate_uses_route_context_and_never_blocks_storage(self):
    report = run_quality_gate(
        "标题", "正文含最好", {"route_id": "r1"},
        client_brand="品牌", competitor_names=[], competitor_markdown="",
        recent_articles=[], ai_json_fn=fake_ai_json, industry="装修", policy=policy,
    )
    self.assertEqual(report["verdict"], "warn")
    self.assertNotIn("blocked", report.values())
```

- [ ] **Step 2: 实现参数替换与两层策略收口。**

`run_quality_gate` 改接收 `route_context`，LLM 审核 prompt 不传旧简报、FAQ、人群角度或来源文章。保留通用词与行业词、事实可回溯、竞品公平、语义承诺和近文相似度检查；所有失败项均为 `warn`。删除任何 `generation_status="门禁拦截"` 分支，`append_content_generation` 永远执行。

- [ ] **Step 3: 运行质量门禁回归。**

Run: `python -X utf8 -m unittest tests.test_quality_gate tests.test_dev_quality_gate_review -v`  
Expected: PASS；医疗、教育、金融行业词仍生效，非阻断保存仍生效。

### Task 7: 用 Query 主导的路线抽样实现同客户多样性，并更新批量任务

**Files:**

- Modify: `app.py`
- Modify: `services/batch_generation.py`
- Modify: `tests/test_batch_generation.py`
- Modify: `tests/test_dev_content_generate.py`

- [ ] **Step 1: 写失败测试：相同客户不同 Query 不会复用旧模块指纹机制。**

```python
def test_batch_only_excludes_route_for_the_same_normalized_query(self):
    routes = [{"id": "r1"}, {"id": "r2"}]
    recent = [{"article_type": "对比型", "query": "昆山装修公司前十名，哪家口碑最好？", "route_context": {"route_id": "r1"}}]
    same_query = choose_route_for_generation(routes, "对比型", "昆山装修公司前十名，哪家口碑最好？", recent)
    different_query = choose_route_for_generation(routes, "对比型", "昆山哪家装修公司交付力最强？", recent)
    self.assertEqual(same_query["id"], "r2")
    self.assertEqual(different_query["id"], "r1")
```

- [ ] **Step 2: 实现最小的路线避让。**

新增 `choose_route_for_generation(routes, parent_type, query, recent_articles)`：调用方先从行业库取得同父类型 active 路线；函数只排除最近同客户、同父类型且规范化 Query 完全相同的路线 ID。没有替代路线时允许复用并在 `route_context_json` 写 `route_reused=true`。不创建问题库、不保存 Query 覆盖矩阵、不按关键词自动选题。多样性的主来源仍是不同 Query 对不同路线和资料重点的影响，路线避让只是防止重复 Query 连续同稿。

- [ ] **Step 3: 删除旧批量避让参数并回归。**

从 `run_content_generation`、`_run_content_batch_article`、`BatchGenerationJobs` 调用链删除 `avoid_skeleton_opening_pairs` 和旧模块指纹；批量 job 改传 `avoid_route_ids`。  
Run: `python -X utf8 -m unittest tests.test_batch_generation tests.test_dev_content_generate -v`  
Expected: PASS；1/3/5 篇仍严格串行、可取消、失败继续。

### Task 8: 迁移前端、API、文档并做一次有限验收

**Files:**

- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `docs/content-plan.md`
- Modify: `docs/content-refactor-short-term.md`
- Modify: `docs/content-refactor-long-term.md`
- Modify: `docs/knowledge-base-direction.md`
- Modify: `接手文档.md`
- Create: `docs/content-route-library-operation.md`
- Delete after API/UI replacement: 与旧模块、FAQ、角度、简报相关的页面文案、帮助文本、测试 fixture 和截图基线

- [ ] **Step 1: 更新运营说明。**

`docs/content-route-library-operation.md` 必须写清：运营如何提交已精读文章、如何查看来源证据并批准路线、介绍型如何显式选择客户资料、对比型如何选择至少两位竞品、什么内容不会自动进入生成、质量门禁为何只提醒。明确“系统不建设问题库/问法库，Query 不是销售问法资产”。

- [ ] **Step 2: 更新旧文档的冲突口径。**

从 `docs/content-plan.md` 删除“active 骨架/模块抽样”“人群角度/FAQ”“简报 LLM”“客户/行业/global 写法库作用域”“文章子类型已废除但模块仍存在”等段落，替换为本计划第 1 节契约。更新 `docs/knowledge-base-direction.md`：客户总资料改为六类客户事实层，`latest_web_supplement.md` 不再自动并入；场景词、运营判断、来源追溯和行业公共资料不属于客户内容资料。短期/长期文档与接手文档只保留新链路和明确延期项，不能同时描述两套正式内容生产模式。

- [ ] **Step 3: 运行有限自动验收。**

Run:

```powershell
python -X utf8 -m unittest tests.test_content_route_library tests.test_content_route_analysis tests.test_content_route_generation tests.test_content_generations_store tests.test_quality_gate tests.test_content_generation_ui tests.test_batch_generation -v
python -X utf8 -m py_compile app.py services\content_route_library.py services\content_route_analysis.py services\content_route_generation.py services\content_generations.py services\quality_gate.py
git diff --check
```

Expected: 全部 PASS，且无空白/尾随空格错误。

- [ ] **Step 4: 运营验收只跑三篇，不做真实 LLM 批量验收。**

1. 崔红蕾介绍型：显式选择客户总资料、固定介绍型 active 路线、验证客户独有方法在正文前半段展开且无资料转述腔。
2. 崔红蕾对比型：显式选择客户总资料、倪锋与施越冬，验证三位对象均有独立信息量且不拉踩。
3. 古齐装饰对比型：显式选择客户总资料、筑祥与朗通，验证路线来自行业库、各品牌信息可支持读者横向决策，且没有医美措辞泄漏。

每篇只检查：路线是否正确、资料是否仅来自显式选择、文章整体感、门禁是否提醒但已保存。运营人工审核后决定是否发布；不得把这三次验收包装为平台真实问法覆盖或引用效果证明。

## 后续计划：客户与竞品资料自动增量合并及刷新复核

**已确认目标：** `latest_web_supplement.md` 只输出 `# 客户联网事实候选` 和六类客户事实。每次成功生成客户资料解析或联网事实候选后，系统立即把新增事实合并到该客户的 `customer_master.md`；运营点击客户知识库“刷新”时，也重新检查资料源并执行同一合并。

竞品资料同样采用增量合并：上传解析、联网竞品扩展、当日数据整理的高频引用文章补充任一成功后，系统把当前竞品资料包中的新增事实按真实竞品名称合并到独立 `competitor_master.md`；运营点击竞品知识库“刷新”时，也重新检查上传/联网资料包并执行同一合并。两类合并都不调用新的 LLM，重复执行不得产生重复事实。

**边界：** 这是资料总库同步，不是知识库自动注入内容生产。介绍型或对比型生成仍须由运营显式选择客户总资料和竞品资料；竞品资料始终独立于客户资料。只有符合六标题事实层格式的 `latest_web_supplement.md` 可参与客户合并；旧式“行业现象/可写角度/来源清单”联网包、无效候选或跨客户文件一律跳过。竞品合并只按真实竞品名称和可核对事实合并，不自动选择竞品进入对比型文章。

### Task 8: 实现客户与竞品资料的增量合并与刷新复核

**Files:**

- Modify: `services/knowledge_base.py`
- Modify: `app.py`
- Modify: `static/js/app.js`
- Modify: `templates/index.html`（仅在现有状态提示缺少文案时）
- Modify: `tests/test_knowledge_base.py`
- Modify: `tests/test_app_core.py`（如刷新 API 已在此覆盖）

**接口与规则：**

- `KnowledgeBaseService` 读取 `latest_injection.md` 与格式合格的 `latest_web_supplement.md`；前者是基础事实，后者是联网候选事实。
- 新增 `merge_customer_fact_candidate(client_id, candidate_markdown)`：按六标题合并；将标题、空白和 bullet 规范化后做精确去重；保留原有客户总资料的人工编辑内容和顺序，只追加此前不存在的候选事实；不得用候选全文覆盖总资料。
- `run_client_material_web_expansion(cid)` 在成功写出候选文件后调用上述合并；合并结果返回 `merged_count`、`skipped_count` 和 `merge_status`，供页面提示。
- `sync_customer_master(...)`（知识库“刷新”）先检查 `latest_injection.md` 与候选文件哈希；候选存在且格式合格时执行同一合并。源文件未变化或事实已存在时返回成功且 `merged_count=0`，不得再写入重复内容。
- 人工编辑保护改为“保留并追加”：刷新或自动合并不得抹掉人工填写的段落。候选与人工内容的精确重复只保留一份；非精确冲突不由系统裁决，仍保留现有人工内容与候选新增事实。
- 竞品总资料复用同一“保留并追加”原则：按真实竞品 `## 名称` 分节，上传资料、联网竞品资料和当日高频引用提取的新事实只追加到对应分节；精确重复事实跳过，人工填写不覆盖。竞品资料解析、联网扩展和当日高频资料成功后自动触发；竞品知识库 GET/刷新也复用同一合并。
- 合并只操作当前客户 ID；所有查看、刷新和自动合并入口继续保持越权 404。

- [ ] **Step 1: 写失败测试：新联网候选生成后自动追加事实。**

```python
def test_web_fact_candidate_auto_merges_without_overwriting_manual_master(self):
    service.save_customer_master(cid, "# 客户内容资料\n\n## 产品与服务\n\n- 人工保留事实。\n")
    candidate = "# 客户联网事实候选\n\n## 产品与服务\n\n- 联网新增事实。\n"

    result = service.merge_customer_fact_candidate(cid, candidate)

    content = service.load_customer_master(cid)["content"]
    self.assertEqual(result["merged_count"], 1)
    self.assertIn("人工保留事实。", content)
    self.assertIn("联网新增事实。", content)
```

- [ ] **Step 2: 写失败测试：刷新幂等且拒绝旧式联网素材包。**

```python
def test_refresh_remerges_candidate_once_and_skips_legacy_web_package(self):
    write_candidate(cid, "# 客户联网事实候选\n\n## 产品与服务\n\n- 联网新增事实。\n")

    first = service.sync_customer_master(cid, package_dir)
    second = service.sync_customer_master(cid, package_dir)

    self.assertEqual(first["merged_count"], 1)
    self.assertEqual(second["merged_count"], 0)
    self.assertEqual(service.load_customer_master(cid)["content"].count("联网新增事实。"), 1)
```

另建旧式 fixture：`# 联网补充摘要`、`## 行业现象/用户顾虑`、`## 来源清单`。断言刷新后该文件既不进入 `customer_master.md`，也不报成合并成功。

- [ ] **Step 3: 实现候选校验、按标题增量合并与哈希状态。**

只接受首标题为 `# 客户联网事实候选`、其余标题属于固定六类的 Markdown；复用已有客户事实拆分逻辑，以规范化后的完整 bullet/段落为去重键。状态文件单独记录 `latest_web_supplement.md` 的候选哈希和上次合并状态，不将旧格式文件哈希视为可合并来源。

- [ ] **Step 4: 接入自动触发与刷新 API。**

联网扩展完成后先写入候选文件，再调用增量合并；知识库刷新复用同一服务。前端在既有刷新状态区显示“已合并 N 条联网事实”或“未发现新增联网事实”，不显示来源正文，也不把联网候选变成内容生产的隐式输入开关。

- [ ] **Step 5: 运行回归与手工验收。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base tests.test_app_core tests.test_material_web_expansion -v`  
Expected: PASS；自动生成后只追加本客户候选事实；连续两次刷新不重复；人工段落保留；旧式联网包跳过；跨客户刷新/查看/合并返回 404。

### Task 9: 取消写法路线的全部状态分层

**已确认规则：** 本节覆盖本计划此前所有“首篇 candidate、第二个独立 URL 后转 active、运营手动转正、退役后恢复”等描述。运营提交的文章仍必须是已确认被平台精读、已取得正文且能在原文核对节选的文章；但只要该文章通过路线分析并决定入库，路线即参与对应类型内容生产。不需要状态字段、转正、退役或恢复操作；不想保留时直接删除路线。

**Files:**

- Modify: `services/content_route_library.py`
- Modify: `services/content_route_analysis.py`
- Modify: `app.py`
- Modify: `static/js/app.js`
- Modify: `templates/index.html`（仅更新仍展示候选/转正文案的位置）
- Modify: `data/content_route_library/*.json`（一次性将历史 `candidate` 物理改为 `active`）
- Modify: `tests/test_content_route_library.py`
- Modify: `tests/test_content_route_analysis.py`
- Modify: `tests/test_formal_content_route_entry.py`
- Modify: `docs/content-route-library-operation.md`（如该运营文档已创建）

**接口与规则：**

- 删除全部路线状态字段、状态筛选、转正、退役和恢复操作。
- `create_candidate(...)` 改为 `create_route(...)`；`ingest_content_route_analysis(...)` 对无既有路线 ID 的合格分析调用新接口。
- 向既有路线追加独立来源仍保留，用于累积来源证据和查看来源数。历史 JSON 中任何旧状态字段在首次读取时直接移除，并物理落盘。
- 内容生产从行业内同类型路线抽样；没有任何“可用状态”前置条件，也不把来源数作为生成门槛。
- 路线删除后不再参与生成；行业隔离、来源证据不进入写作 LLM、跨客户越权 404 等原边界不变。

- [ ] **Step 1: 写失败测试：单篇合格精读文章立即可被抽样。**

```python
def test_new_verified_route_is_immediately_available(self):
    entry = library.create_route("医美", route, verified_source)

    self.assertNotIn("status", entry)
    self.assertEqual(library.sample_route("医美", "介绍型")["id"], entry["id"])
```

- [ ] **Step 2: 写失败测试：历史 candidate 自动迁移，追加来源不改变状态。**

```python
def test_legacy_status_is_removed_and_extra_source_keeps_route(self):
    write_legacy_route(industry="装修", status="candidate", source_count=1)

    route = library.list_routes("装修")[0]
    updated = library.add_source("装修", route["id"], second_verified_source)

    self.assertNotIn("status", route)
    self.assertNotIn("status", updated)
```

- [ ] **Step 3: 实现状态收口、历史迁移与 UI 文案替换。**

删除状态常量和状态 API；新路线不写状态字段。读取路线库时兼容并物理删除旧 JSON 的状态字段；修改引用情报页的“新建候选路线”“候选”“转正”“第二来源后可用”等文案，统一改为“新建写作路线”。不新增第二篇来源的硬门槛；知识库页提供直接删除路线的动作。

- [ ] **Step 4: 运行回归并手工确认介绍型可生成。**

Run: `python -X utf8 -m unittest tests.test_content_route_library tests.test_content_route_analysis tests.test_formal_content_route_entry -v`  
Expected: PASS；一篇合格文章入库后即可被介绍型或对比型生文抽到；历史状态字段被移除；删除路线后不再被抽样；跨客户 API 继续 404。

### Task 10: 在知识库中建立行业写法库分区，并按文章类型展示

**已确认规则：** 写法库进入知识库工作台，但它仍是行业级知识，不是某个客户的客户资料或竞品资料。运营从某客户进入知识库时，系统仅以该客户所属行业定位对应写法库；写法库页面必须先区分`介绍型`和`对比型`，再展示路线。两类路线不能合并成一个无类型列表，也不能让介绍型生文读取对比型路线，反之亦然。

**Files:**

- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `app.py`
- Modify: `services/content_route_library.py`
- Modify: `tests/test_content_route_library.py`
- Modify: `tests/test_content_generation_ui.py`
- Modify: `docs/content-route-library-operation.md`

**接口与规则：**

- 知识库新增“行业写法库”分区；数据仍保存在 `data/content_route_library/`，不得复制到 `data/knowledge_base/<客户ID>/customer_master.md` 或 `competitor_master.md`。
- 进入分区后展示当前客户行业、`介绍型`路线列表、`对比型`路线列表；每条路线展示名称、读者任务、路线步骤、签名、适用边界和来源数量。来源 URL 与节选只在运营展开核对时展示，永不进入写作 LLM。
- 新建、追加来源或删除时必须明确 `parent_type`；创建页默认要求运营先选择`介绍型`或`对比型`，保存后不可通过前端静默改型。若确需改型，应新建正确类型路线并删除旧路线，避免来源证据和用途错配。
- 内容生产只从本次文章类型对应的路线中抽样，不展示或读取另一类型路线，也不将写法库视为“客户资料开关”。
- 客户级权限仍以当前客户 ID 校验；无权访问该客户时返回 404。行业写法库不能成为绕过客户访问权限读取行业、客户或来源资料的接口。

- [ ] **Step 1: 写失败测试：知识库返回的路线按两种文章类型分组。**

```python
def test_knowledge_base_route_library_groups_routes_by_parent_type(self):
    payload = get_route_library_for_client(authorized_client_id)

    self.assertEqual(set(payload["groups"]), {"介绍型", "对比型"})
    self.assertTrue(all(item["parent_type"] == "介绍型" for item in payload["groups"]["介绍型"]))
    self.assertTrue(all(item["parent_type"] == "对比型" for item in payload["groups"]["对比型"]))
```

- [ ] **Step 2: 写失败测试：生成请求不可能跨类型抽样。**

```python
def test_intro_generation_only_receives_intro_route_when_comparison_routes_exist(self):
    result = run_content_generation(intro_request)

    self.assertEqual(result["route_context"]["parent_type"], "介绍型")
```

- [ ] **Step 3: 实现知识库分区、类型分组和最小状态操作。**

复用现有行业路线存储，不新建客户级副本或第二套同步文件。前端按两个固定分区渲染；空分区明确显示“该行业暂未沉淀此类写法路线”，不回退到另一类型。新建与操作 API 验证 `parent_type`，并沿用现有行业隔离与客户授权。

- [ ] **Step 4: 运行针对性验收。**

Run: `python -X utf8 -m unittest tests.test_content_route_library tests.test_content_generation_ui tests.test_formal_content_route_entry -v`  
Expected: PASS；知识库中两类路线清晰分组，介绍型和对比型生成均只能抽到对应路线，跨客户访问继续为 404。

## Explicitly Deferred

- 获取“真正被平台精读文章”的自动化方案、爬虫改造、平台内部决策过程、缓存命中推断或任何黑盒归因承诺。
- 真实问题库、问法库、问法覆盖矩阵、自动选题或将当前 Query 伪装为销售问法资产。
- 客户/竞品知识库自动注入内容生产、竞品资料并入客户资料、自动选择竞品。上节已确认的“客户联网事实候选增量合并”仅同步客户总资料，不构成自动注入内容生产。
- 发布链路、爬虫、记录库、知识库整理、远程部署、平台微调、模型记忆与自进化。
- 按行业编写硬编码文章模板；行业隔离的是路线存储和来源，不是写作 prompt 的固定行业话术。

## 计划自检

- 选择层规律：Task 2 只从已确认精读文章积累路线；Query 不被保存为问法资产；来源证据与路线分离。
- 写法库：Task 1 删除零散模块和跨客户作用域，只保留行业完整路线与独立来源证据。
- 内容生产：Task 3、4、7 保持 `run_content_generation(...)` 为唯一入口，改成单次写作、显式资料、手动竞品和 Query 主导的多样性。
- 删除要求：第 2 节及 Task 1、3、4、5 列出代码、API、UI、文件、JSON 字段和 SQLite 列的删除目标；没有兼容 fallback。
- 边界与安全：Global Constraints、Task 4、Task 6、Deferred 覆盖显式注入、越权 404、只提醒门禁、`max_tokens` 和不碰其他链路。
