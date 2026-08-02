# 客户/竞品知识库与选择层运营提示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改动内容生产和写法库的前提下，交付独立的客户知识库、竞品知识库，以及记录库中的临时选择层报告上传和问题组场景词提示表。

> **2026-07-27 实施状态：** 客户知识库、竞品知识库、场景词提示和质量门禁当前范围均已落地。竞品资料提取入口已从知识库移动到当日整理页，按当前日期/AI 平台范围从累计引用最高的 12 篇文章提取；知识库页只保留查看、编辑、保存。临时“选择层分析报告”前端展示仍按产品决定暂不实施，报告材料继续作为一次性人工展示材料。

**Architecture:** 知识库把既有资料包整理为每客户可编辑的 Markdown 总资料，底层来源保留且人工编辑绝不被静默覆盖。选择层功能是记录库的只读观察工具：运营上传人工报告；再以问题组的 Query 和组内高引用文章的标题、Meta、首段为 LLM 上下文，缓存 Query 的具体场景词。页面只显示“问题组 / Query / 场景词”，不展示命中格、不判断我方覆盖，也不驱动选题。

**Tech Stack:** Flask、Python 标准库、现有 `services.storage`、`services.selection_surface`、`services.article_fetcher`、Vanilla JavaScript、`unittest` / mock。

## 全局约束

- 不修改 `services/pattern_library.py`、写法库 API、内容生产资料开关、简报、写作或发布链路；新知识库不自动注入内容生产。
- 客户资料和竞品资料必须是两个独立模块、两个独立总文件；所有客户级读取和写入先调用 `require_client_access(cid)`，越权与不存在均返回 404。
- 客户总资料必须保留八方向结构，并清楚标记 `[客户资料解析]` 与 `[AI 联网补充]`；上游变更只提示，不能覆盖人工编辑。
- 竞品总资料按真实竞品名称的 `##` 标题分节；运营从当日整理页显式触发，按当前日期/AI 平台范围取累计引用最高的 12 篇文章正文，并合并上传解析、联网扩展等已有竞品资料。现有竞品联网搜索保留但不单独触发自动同步。
- 临时选择层报告只接受 UTF-8 `.md`，单文件最大 2 MiB；用户原始文件名绝不参与文件路径，下载/查看只接受服务端已列出的受控报告 ID。
- 场景词不是销售问法资产。它只使用现有问题组作爬取记录观察；不创建问题库、不导入销售数据、不做自动选题、不做自动发文。
- 每个问题组按组内累计被引次数取至少 3 篇不同 URL 的高引用文章；不足 3 篇时使用现有全部文章并标记样本不足。表面材料仅为标题、Meta、首段前 300 字；不保存整篇正文。
- 场景词 LLM 必须同时看到 Query、标题、Meta、首段材料；只输出具体场景表达，排除“推荐、哪个好、怎么样、价格、排名、靠谱、对比、注意事项”等泛化词；保留原词，不做同义词扩展。新增 LLM 调用 `max_tokens >= 4000`。
- 选择层页面只显示问题组、Query、场景词；不显示标题/Meta/首段命中明细、不显示“我方在场”、状态、红色预警或缺口选题。
- 开发验证只用 fixture 和 mock，不真实调用 LLM、Tavily 或公网抓取；不重启、不部署。PowerShell 命令用 `;`，Python 命令使用 `python -X utf8`。

---

## 文件与数据边界

| 路径 | 责任 |
| --- | --- |
| `services/knowledge_base.py` | 客户/竞品总资料的读取、首次整理、上游指纹、人工编辑保护。 |
| `services/competitor_knowledge.py` | 从当日高频引用文章与上传资料生成按真实名称分节的竞品总资料输入。 |
| `services/selection_evidence.py` | 临时报告安全存取、组内高引用文章选择、表面缓存、Query 场景词缓存与提示词。 |
| `app.py` | 三类服务的工厂、客户隔离路由、LLM 注入点。 |
| `templates/index.html` | 独立客户知识库页、竞品知识库页，以及记录库的报告/场景词分区。 |
| `static/js/app.js` | 上传、刷新、编辑保存、场景词提取和只读表格渲染。 |
| `data/knowledge_base/<cid>/customer_master.md` | 客户八方向可编辑总资料。 |
| `data/knowledge_base/<cid>/customer_state.json` | 来源文件哈希、人工编辑标记、来源更新状态；不保存来源正文副本。 |
| `data/knowledge_base/<cid>/competitor_master.md` | 按 `## 竞品名称` 分节的可编辑竞品总资料。 |
| `data/selection_surface_reports/<cid>/<report_id>.md` | 运营临时上传的选择层报告原件，`report_id` 为服务端 UUID。 |
| `data/selection_evidence/<cid>/article_surfaces.json` | 被选文章的 URL 指纹、标题、Meta、首段前 300 字、抓取状态；不保存全文。 |
| `data/selection_evidence/<cid>/query_scenes.json` | `问题组 ID + Query + 证据指纹 → 场景词` 的可重建缓存。 |
| `tests/test_knowledge_base.py` | 客户/竞品资料整理、来源标记、人工编辑保护、跨客户隔离。 |
| `tests/test_selection_evidence.py` | 报告安全、文章选择、首段截断、提示词、增量缓存。 |
| `tests/test_selection_evidence_api.py` | Flask 路由 404、上传、LLM mock、页面 API 返回。 |

质量门禁的通用/行业规则改造不属于本计划；它继续以 `docs/knowledge-base-direction.md` 的边界为准，后续单独立计划，避免把资料中心与门禁改造绑在一次交付中。

---

### Task 1：客户知识库总资料

**Files:**
- Create: `services/knowledge_base.py`
- Modify: `app.py`
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Create: `tests/test_knowledge_base.py`

**Interfaces:**
- Consumes: `data/material_packages/<cid>/latest_injection.md`、`latest_web_supplement.md`。
- Produces: `KnowledgeBaseService.load_customer_master(cid)`、`sync_customer_master(cid, overwrite=False)`、`save_customer_master(cid, content)`。

- [ ] **Step 1: 写客户八方向合并的失败测试。**

  fixture 分别在 `latest_injection.md` 与 `latest_web_supplement.md` 写入同一方向和不同方向内容。断言首次同步生成的 `customer_master.md` 固定含“品牌基础、产品/服务、优势、目标人群/痛点、价格、信任、合规风险、公开背景、引用情报与运营判断”标题；前两份来源的内容分别以 `[客户资料解析]`、`[AI 联网补充]` 包住。

- [ ] **Step 2: 运行失败测试。**

  Run: `python -X utf8 -m unittest tests.test_knowledge_base.CustomerMasterTests -v`  
  Expected: FAIL，提示 `services.knowledge_base` 不存在。

- [ ] **Step 3: 实现机械合并与来源更新保护。**

  使用 Markdown 二级标题解析既有八方向，不调用 LLM。`customer_state.json` 保存两个来源的 SHA-256、`edited_at` 和 `source_update_available`。首次没有总资料时自动生成；存在人工保存记录且来源哈希变化时，`sync_customer_master(overwrite=False)` 只返回 `source_update_available=true`；只有运营明确传 `overwrite=true` 才重新生成。

- [ ] **Step 4: 写并通过人工编辑保护测试。**

  先保存人工改写的总资料，再修改来源文件并调用普通同步，断言总资料字节不变且状态提示更新；调用覆盖同步后断言来源新内容出现。

- [ ] **Step 5: 接入客户隔离 API 与最小编辑页。**

  新增 `GET /api/knowledge/customer/<cid>`、`POST /api/knowledge/customer/<cid>/sync`、`PUT /api/knowledge/customer/<cid>`。每个路由开头使用 `require_client_access(cid)`；页面只提供查看、编辑、保存、来源有更新提示、主动重新整理按钮。

- [ ] **Step 6: 运行验证。**

  Run: `python -X utf8 -m unittest tests.test_knowledge_base tests.test_materials_api -v`  
  Expected: PASS；没有来源时安全空态，跨客户 GET/PUT 返回 404，现有客户资料 API 仍通过。

### Task 2：竞品知识库总资料

**Files:**
- Create: `services/competitor_knowledge.py`
- Modify: `services/knowledge_base.py`
- Modify: `app.py`
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_knowledge_base.py`

**Interfaces:**
- Consumes: 当日范围回答实体、`services.article_body_hits` / 现有文章抓取能力、高频引用文章、`latest_upload_competitors.md`。
- Produces: `build_competitor_master_input(...)`、`KnowledgeBaseService.load_competitor_master(cid)`、`save_competitor_master(cid, content)`。

- [ ] **Step 1: 写竞品按真实名称分节的失败测试。**

  fixture 给出两个真实竞品、同名文章提及和上传资料。断言输出只有 `## 竞品甲`、`## 竞品乙` 两个名称分节，不能生成“竞品 A”等占位节，也不能把客户资料放入竞品总资料。

- [ ] **Step 2: 运行失败测试。**

  Run: `python -X utf8 -m unittest tests.test_knowledge_base.CompetitorMasterTests -v`  
  Expected: FAIL，提示 `services.competitor_knowledge` 不存在。

- [ ] **Step 3: 最小实现资料来源汇集。**

  从当前客户当日整理范围内累计引用最高的 12 篇文章建立候选竞品资料；复用既有文章正文抓取能力提取公开文章中的同名证据，再与上传解析、联网扩展等已有竞品 Markdown 合并。入口放在当日整理页，知识库页只负责查看、编辑、保存；保留原始文章/上传资料做追溯，不要求在最终竞品总资料逐条标来源。

- [ ] **Step 4: 实现可编辑竞品总资料与独立页面。**

  新增 `GET /api/knowledge/competitors/<cid>`、`POST /api/knowledge/competitors/<cid>/sync`、`PUT /api/knowledge/competitors/<cid>`。页面独立于客户知识库，左侧或顶部按 `##` 名称生成跳转；保存后不因新抓取自动覆盖。

- [ ] **Step 5: 运行验证。**

  Run: `python -X utf8 -m unittest tests.test_knowledge_base tests.test_competitor_materials tests.test_history_tools -v`  
  Expected: PASS；竞品资料与客户资料不串库，保留既有联网搜索路由，越权 404。

### Task 3：临时选择层报告上传与只读展示

**Files:**
- Create: `services/selection_evidence.py`
- Modify: `app.py`
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Create: `tests/test_selection_evidence.py`
- Create: `tests/test_selection_evidence_api.py`

**Interfaces:**
- Produces: `SelectionEvidenceStore.upload_report(cid, file)`、`list_reports(cid)`、`read_report(cid, report_id)`。
- Routes: `POST /api/records/selection-reports/<cid>`、`GET /api/records/selection-reports/<cid>`、`GET /api/records/selection-reports/<cid>/<report_id>`。

- [ ] **Step 1: 写报告安全失败测试。**

  使用临时 data 根目录上传一份 `.md`；断言存储名由服务端 UUID 生成。分别请求 `../x.md`、`..\\x.md`、绝对路径、另一客户的 UUID，均断言 404；上传 `.html` 与超过 2 MiB 的文件断言 400。

- [ ] **Step 2: 运行失败测试。**

  Run: `python -X utf8 -m unittest tests.test_selection_evidence.SelectionReportTests -v`  
  Expected: FAIL，提示 `services.selection_evidence` 不存在。

- [ ] **Step 3: 实现受控文件存取。**

  `upload_report` 只读取 UTF-8 `.md`，以 UUID 保存到 `data/selection_surface_reports/<cid>/`；列表只返回该目录中正则匹配 UUID `.md` 的文件。读取接口只接收 UUID `report_id`，用 `Path.resolve()` 校验最终父目录等于当前客户目录；前端以 `<pre>` 显示文本，不把 Markdown 当 HTML 注入。

- [ ] **Step 4: 在记录库新增临时上传区。**

  增加文件选择、上传、当前客户报告列表、只读预览。页面文案明确“临时原件，不进入知识库、不自动解析”。不做报告编辑、删除、摘要、标签或长期索引。

- [ ] **Step 5: 运行验证。**

  Run: `python -X utf8 -m unittest tests.test_selection_evidence tests.test_selection_evidence_api tests.test_auth -v`  
  Expected: PASS；当前客户可上传/查看，跨客户与路径穿越均为 404。

### Task 4：问题组 Query 场景词缓存

**Files:**
- Modify: `services/selection_evidence.py`
- Modify: `app.py`
- Modify: `tests/test_selection_evidence.py`
- Modify: `tests/test_selection_evidence_api.py`

**Interfaces:**
- Consumes: `F_GROUPS`、`load_client_records(cid, group_id=...)`、`services.selection_surface.aggregate_selection_articles`、`services.article_fetcher.fetch_article_text(..., include_html=True)`。
- Produces: `build_group_query_evidence(...)`、`refresh_query_scenes(cid, ask_json)`、`load_query_scene_rows(cid)`。
- Routes: `POST /api/records/selection-evidence/<cid>/refresh`、`GET /api/records/selection-evidence/<cid>`。

- [ ] **Step 1: 写高引用样本与表面截断的失败测试。**

  fixture 为同一问题组提供 4 个不同 URL 和多轮引用。断言按组内累计引用次数选前 3 个不同 URL；不足 3 个时 `sample_insufficient=true`。mock HTML 后断言每篇输入含 title、meta description、第一长段且首段截断为 300 字。

- [ ] **Step 2: 运行失败测试。**

  Run: `python -X utf8 -m unittest tests.test_selection_evidence.QueryEvidenceTests -v`  
  Expected: FAIL，提示 `build_group_query_evidence` 不存在。

- [ ] **Step 3: 实现文章表面缓存。**

  复用 `aggregate_selection_articles` 做 URL 归一和组内排序，复用 `fetch_article_text(include_html=True)` 与 `extract_selection_surface` 提取表面。`article_surfaces.json` 仅保存 URL 指纹、标题、Meta、`first_paragraph[:300]`、成功/失败状态与抓取时间；相同 URL 不重复抓取。抓取失败仍把已有标题及缺失字段送入证据包，不能让整组失败。

- [ ] **Step 4: 写场景词提示词和增量缓存测试。**

  mock LLM 断言一次请求包含多个“问题组 / Query / 高引用文章表面”单元，明确排除泛化词、保留原词、只输出 JSON。首次刷新写入全部 Query；第二次相同证据不调用 LLM；修改 Query 或任一已选文章表面后只重算该 Query。无效 JSON 或异常不覆盖旧条目。

- [ ] **Step 5: 实现一次批量刷新。**

  `query_scenes.json` 以 `group_id + query` 为键，保存 `evidence_fingerprint`、`scene_terms`、`updated_at`。刷新时先构建所有变更单元，再以一次 `ask_json(prompt, max_tokens=4000)` 调用处理；只接受返回中对应输入 Query 的非泛化短语列表。GET 不调用 LLM、不抓网页，只读缓存并按问题组、Query 返回。

- [ ] **Step 6: 运行验证。**

  Run: `python -X utf8 -m unittest tests.test_selection_evidence tests.test_selection_evidence_api tests.test_selection_surface_report -v`  
  Expected: PASS；缓存可增量更新，文章选择/首段提取复用已有行为，LLM 失败保留旧结果。

### Task 5：记录库中的极简场景词提示表

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_record_trends.py`

**Interfaces:**
- Consumes: `GET /api/records/selection-evidence/<cid>`、`POST /api/records/selection-evidence/<cid>/refresh`。
- Produces: 记录库中的“问题组场景词提示”分区。

- [ ] **Step 1: 写前端静态接线失败测试。**

  断言记录库模板含“问题组场景词提示”、提取/更新按钮和表格容器；脚本含两个选择层 API 路径、加载函数与空态文案。

- [ ] **Step 2: 运行失败测试。**

  Run: `python -X utf8 -m unittest tests.test_record_trends.RecordTrendUiTests -v`  
  Expected: FAIL，提示缺少场景词提示分区。

- [ ] **Step 3: 实现最小表格。**

  运营点击“提取/更新场景词”后刷新数据；表格仅三列：问题组、Query、场景词。无缓存时提示先提取；空场景词显示“未识别具体场景词”。不渲染文章标题、Meta、首段、命中格、我方在场、状态、警告色、缺口文案或自动选题按钮。

- [ ] **Step 4: 运行全量验证。**

  Run: `python -X utf8 -m unittest tests.test_knowledge_base tests.test_selection_evidence tests.test_selection_evidence_api tests.test_record_trends tests.test_selection_surface_report -v; .\\run_tests.bat`  
  Expected: 相关模块全部 PASS，随后全量测试 PASS。

## 交付验收

| 目标 | 验收方式 |
| --- | --- |
| 客户资料合并 | 两份客户资料包整理为一份八方向总资料，来源标记清晰；人工编辑后上游变更不覆盖。 |
| 竞品资料独立 | 竞品总资料按真实名称分节；客户资料不出现在此文件；联网搜索仍可单独使用。 |
| 临时报告 | 运营上传 Markdown 后仅当前客户可查看；报告不进入知识库、不能路径穿越。 |
| 场景词提示 | 每个问题组的 Query 显示从 Query + 三篇高引用文章表面共同提取的具体场景词。 |
| 页面克制 | 场景词表只有问题组、Query、场景词；无我方覆盖、状态、命中明细、正文归档或自动选题。 |
| 隔离与稳妥性 | 所有客户级端点越权 404；LLM 或单页抓取失败不抹掉现有缓存；不改内容生产与写法库。 |

## 自检

- [ ] 旧 `2026-07-26-knowledge-hub-and-quality-policy.md` 与 `2026-07-26-coverage-matrix-and-evidence.md` 已标记为废弃，避免开发者按过时的“客户专属门禁”“只看标题”“我方在场/状态”施工。
- [ ] `docs/knowledge-base-direction.md`、`docs/citation-selection-findings.md`、`docs/content-plan.md`、`docs/content-refactor-long-term.md`、`接手文档.md` 已同步本计划边界。
- [ ] 计划不包含真实销售问法库、全文归档、自动选题、内容生产接入或质量门禁实现。
