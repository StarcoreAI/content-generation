# 爬取记录库清理与单平台逐题矩阵 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 移除已完成使命的临时选择层报告，并让问题组提及趋势与逐题矩阵只按运营选定的单一合同 AI 平台展示。

**Architecture:** 删除选择层报告的页面、只读 API 和运行时报告目录；保留场景词提示及离线选择层研究脚本，它们不是这项临时展示功能的一部分。问题组趋势 API 改为强制接收且校验一个客户已配置的平台，前端沿用客户合同平台顺序渲染单选按钮，并将当前选项传给同一张趋势/矩阵卡片。

**Tech Stack:** Flask、Python 标准库、原生 JavaScript、HTML、`unittest`。

## Global Constraints

- 所有用户可见文本使用简体中文。
- 不改爬虫、本地 worker、当日数据整理、内容生产、场景词提示、引用文章池或来源站趋势。
- 客户级访问仍须 `require_client_access`；平台参数只能是该客户已配置的合同平台。
- 不提供“全部平台”选项、汇总回退或隐藏的全平台矩阵。
- 物理删除运行时 `data/selection_surface_reports/` 下已有临时报告；不删除 `scripts/run_selection_surface_report.py`、其研究测试或仓库中的历史研究文档。
- 今天不再调整对比型文章开头的 600 字要求；该效果已确认满意。
- 竞品资料删除只删除当前资料库章节，不删除原始资料，也不写入抑制标记；后续同步应自动恢复。
- 竞品改名是规范名称迁移：保留旧名到新名的别名映射，后续旧名来源资料仍合并到新名称下。
- 知识库编辑统一自动保存：输入防抖、失焦立即保存、结构操作立即保存，并保留失败重试入口。
- 除质量门禁和系统提示词目录外的知识库均可下载为 Word 文档；下载内容仅为运营可见的已保存资料，不含内部元数据或原始抓取内容。
- 系统提示词仅以经审核的只读模板目录展示；不输出最终拼接请求中的客户资料、网页原文、密钥或其他运行时敏感值。
- 修改前先写最小失败测试；完成后运行相关测试和 `git diff --check`。只在用户明确要求时提交。

---

### Task 1: 删除临时选择层报告展示及历史报告文件

**Files:**
- Modify: `app.py:1369-1407` — 删除报告目录遍历函数和两个 `/api/records/selection-reports/...` 只读路由。
- Modify: `templates/index.html:254-258` — 删除“选择层分析报告”卡片。
- Modify: `static/js/app.js:1693-1730` — 删除页面加载时的调用及报告渲染、加载、预览函数。
- Modify: `tests/test_record_trends.py` — 将旧 UI 存在性断言替换为“模板、脚本均不含报告入口/API”的回归断言。
- Modify: `tests/test_selection_evidence_api.py` — 删除只覆盖已废弃报告 API 的测试用例。
- Delete at runtime: `data/selection_surface_reports/` — 删除其中全部客户目录和 Markdown 报告。
- Modify: `接手文档.md`, `docs/content-plan.md`, `docs/knowledge-base-direction.md`；Delete: `下一位Agent交接提示词.md` — 删除“可临时上传/只读展示选择层报告”这一当前能力描述；保留场景词提示的描述。

**Interfaces:**
- Removes: `selection_surface_report_paths(cid)`, `GET /api/records/selection-reports/<cid>`, `GET /api/records/selection-reports/<cid>/<report_id>`.
- Preserves: `SelectionEvidenceService` 与 `/api/records/selection-evidence/<cid>` 的读、写、刷新接口。

- [x] **Step 1: 写失败测试，锁定已删除的产品表面。**

```python
def test_records_library_removes_temporary_selection_surface_reports(self):
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

    self.assertNotIn("选择层分析报告", template)
    self.assertNotIn("selectionSurfaceReports", template)
    self.assertNotIn("selectionSurfaceReportPreview", template)
    self.assertNotIn("loadSelectionSurfaceReports", script)
    self.assertNotIn("viewSelectionSurfaceReport", script)
    self.assertNotIn("/api/records/selection-reports/", script)
```

并在路由隔离测试中断言废弃 URL 没有注册：

```python
self.assertEqual(
    alice.get("/api/records/selection-reports/alice-client").status_code,
    404,
)
```

- [x] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_record_trends.RecordTrendUiTests tests.test_selection_evidence_api.SelectionEvidenceApiTests -v`

Expected: FAIL，因为页面与 API 仍存在。

- [x] **Step 3: 最小实现删除展示能力，清理运行时目录。**

从 `app.py` 移除报告路径函数和两个 Flask 路由；从模板移除整张报告卡；从 `loadRecordsLibraryViews()` 移除 `loadSelectionSurfaceReports()`，并删除其三个关联函数。不要触碰 `loadQueryScenes()`、`refreshQueryScenes()`、`services/selection_evidence.py` 或场景词 API。

删除废弃 API 测试，并将 UI 测试改为 Step 1 的否定断言。先只读确认目标目录存在且路径正是仓库下的 `data/selection_surface_reports`，再运行：

```powershell
$reportRoot = Join-Path (Get-Location) 'data\selection_surface_reports'
if (Test-Path -LiteralPath $reportRoot) {
  Remove-Item -LiteralPath $reportRoot -Recurse -Force
}
```

同步修正文档中的“临时报告上传/展示”现状，明确记录库保留的选择层工具仅为 Query 场景词提示。历史研究结论或引用选择规律文档不因 UI 下线而删除。

- [x] **Step 4: 运行回归。**

Run: `python -X utf8 -m unittest tests.test_record_trends tests.test_selection_evidence tests.test_selection_evidence_api -v`

Expected: PASS；场景词服务和越权 404 仍正常，选择层报告 URL 为未注册的 404，工作区不存在 `data/selection_surface_reports`。

### Task 2: 用客户合同平台切换问题组趋势与逐题矩阵

**Files:**
- Modify: `templates/index.html:244-273` — 在问题组选择器下增加“AI 平台”单选按钮容器，并把趋势说明改为“当前平台最近 7 个实际采集日”。
- Modify: `static/js/app.js:1640-1904` — 维护当前记录库平台状态；按 `currentClientPlatforms` 渲染按钮；客户端变更、平台切换或问题组切换时请求同一选中平台的数据。
- Modify: `app.py:1333-1347` — `GET /api/records/group_trend` 强制要求 `platform`，并以客户合同平台验证参数后传给趋势构建函数。
- Modify: `services/record_trends.py:82-112` — 保持单平台过滤语义，并移除 `platform="all"` 作为公开产品行为的特殊分支。
- Modify: `tests/test_record_trends.py` — 增加服务层、API 和 UI 回归测试；更新现有 API 测试以提供客户合同平台和 `platform` 参数。

**Interfaces:**
- Changes: `GET /api/records/group_trend?client_id=<cid>&group_id=<gid>&platform=<configured-platform>`。
- Response: 只包含该平台的 `dates`、`overall`、`questions`；无 `platform` 返回 `400 {"error":"ai_platform_required"}`，非合同平台返回 `400 {"error":"ai_platform_not_configured"}`。
- Client state: `recordGroupTrendPlatform` 只能是 `currentClientPlatforms` 中的一项；首选该数组第一个平台，若客户切换后原选择仍有效则保留。

- [x] **Step 1: 写失败测试，锁定单平台数据与 API 契约。**

```python
def test_group_trend_filters_only_the_requested_platform(self):
    trend = build_group_mention_trend(self.records, ["装修公司怎么选"], platform="deepseek")
    self.assertEqual(trend["overall"], [
        {"mentioned": 1, "total": 2},
        {"mentioned": 0, "total": 1},
    ])
    self.assertEqual(trend["questions"][0]["values"], trend["overall"])
```

在 API 测试中设置客户的 `contract_platforms`，并覆盖缺参、越权平台和正常过滤：

```python
geo_app.save(geo_app.F_CLIENTS, [{
    "id": "alice-client", "owner_username": "alice",
    "contract_platforms": ["deepseek", "qwen"],
}])

self.assertEqual(
    alice.get("/api/records/group_trend?client_id=alice-client&group_id=group-1").status_code,
    400,
)
self.assertEqual(
    alice.get("/api/records/group_trend?client_id=alice-client&group_id=group-1&platform=doubao").get_json()["error"],
    "ai_platform_not_configured",
)
selected = alice.get(
    "/api/records/group_trend?client_id=alice-client&group_id=group-1&platform=deepseek"
)
self.assertEqual(selected.status_code, 200)
self.assertEqual(selected.get_json()["overall"][0], {"mentioned": 1, "total": 1})
```

UI 测试至少断言平台容器、渲染函数与请求参数存在，且没有“全部平台”按钮：

```python
self.assertIn('id="recordGroupPlatformChoices"', template)
self.assertIn("renderRecordGroupPlatformChoices", script)
self.assertIn("platform=${encodeURIComponent(recordGroupTrendPlatform)}", script)
self.assertNotIn("data-record-group-platform=\"all\"", script)
```

- [x] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_record_trends -v`

Expected: FAIL，因为当前页面没有记录库平台按钮，API 允许缺省平台并汇总所有平台。

- [x] **Step 3: 实现合同平台单选与服务端强制过滤。**

在 `group_trend()` 中读取客户对象、验证 `platform` 非空且属于 `normalize_contract_platforms(client["contract_platforms"])`；仅把该值传给 `build_group_mention_trend()`。删除服务函数中把 `"all"` 解释为空筛选的分支，保持传入平台时按 `source_platform` 精确过滤。

前端新增 `recordGroupTrendPlatform` 和 `renderRecordGroupPlatformChoices()`：仅基于 `currentClientPlatforms` 创建按钮，选中项使用现有主按钮样式，其余使用次按钮样式。客户切换后若当前值不在新数组中，自动切为第一个合同平台；无平台时禁用趋势/矩阵并显示“当前客户未配置 AI 平台”。按钮点击只更新状态并调用 `loadRecordGroupTrend()`；该函数的 URL 必须带上 `platform`。同一响应同时渲染总提及率与逐题矩阵，二者都只表示当前平台。

- [x] **Step 4: 运行回归与静态检查。**

Run: `python -X utf8 -m unittest tests.test_record_trends -v; node --check static/js/app.js; git diff --check`

Expected: PASS；记录库只允许切换客户配置的平台，矩阵与折线图不再汇总多平台记录，非合同平台和跨客户请求不泄露数据。

### Task 3: 让引用情报分析默认覆盖整个问题组

**Files:**
- Modify: `static/js/app.js:667-695` — 在问题组首次加载和每次切换后，将“全部问题（本问题组）”设为问题下拉框默认值。
- Modify: `templates/index.html:310` — 将“对应问题”标签改为更准确的“分析范围”，明确运营仍可改选一条具体 Query。
- Modify: `tests/test_content_generation_ui.py` — 为默认选中全部问题增加静态回归断言。

**Interfaces:**
- Keeps: `POST /api/content-routes/analyze-query-platform` 的 `query`、`analyze_all_questions` 和单一 `ai_platform` 请求契约不变。
- Default: 每当运营选择或切换问题组，`routeAnalysisQuerySelect.value` 为 `__all_questions__`；运营手动改选具体 Query 后，点击按钮仍只分析该 Query。

- [x] **Step 1: 写失败测试，锁定默认值而非仅保留选项。**

```python
def test_reference_intelligence_defaults_to_all_questions_after_group_is_loaded(self):
    script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

    self.assertIn("option.value = '__all_questions__'", script)
    self.assertIn("select.value = '__all_questions__';", script)
```

- [x] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_content_generation_ui.ContentGenerationUiTests.test_reference_intelligence_defaults_to_all_questions_after_group_is_loaded -v`

Expected: FAIL，因为现有代码只插入“全部问题”选项，没有把它设为默认值。

- [x] **Step 3: 最小实现默认选择。**

在 `addRouteAnalysisAllQuestionsOption()` 插入或确认“全部问题（本问题组）”选项后，无条件执行：

```javascript
select.value = '__all_questions__';
```

这样 `loadRouteAnalysisQuestionOptions()` 和 `onRouteAnalysisGroupChange()` 都会复用同一默认行为。保持 `runQueryPlatformReferenceAnalysis()` 现有逻辑：默认值触发 `query: ''` 与 `analyze_all_questions: true`；用户改选具体 Query 时仍发送该 Query 和 `false`。模板标签改为“分析范围”，不新增第二个控件、不改后端、不改变单一平台选择。

- [x] **Step 4: 运行回归与语法检查。**

Run: `python -X utf8 -m unittest tests.test_content_generation_ui tests.test_query_platform_reference_api -v; node --check static/js/app.js; git diff --check`

Expected: PASS；选择问题组后默认提交整个组，手选单题和单平台分析仍保持原有 API 行为。

### Task 4: 收口当前文档并删除已失效的内容路线文档

**Files:**
- Modify: `接手文档.md` — 用当前正式实现替换旧的“active 写法库、简报 LLM、竞品随机池、长期自进化”等描述；说明竞品知识库已完成，内容生产仅在运营显式选择时读取客户事实与竞品分节。
- Delete: `下一位Agent交接提示词.md` — 项目不再需要下一位 Agent 交接文档。
- Modify: `docs/content-plan.md` — 重写为当前内容生产、引用情报与记录库的产品边界文档：行业路线 + 单阶段写作 + 显式资料 + 手选竞品 + 质量提醒；删除旧两阶段、`active` 状态、随机竞品、平台微调和自进化叙述。
- Modify: `docs/knowledge-base-direction.md` — 将客户/竞品知识库的当前完成状态写清；客户事实和选定竞品分节可由运营显式用于内容生产，但不自动注入；移除临时报告描述，保留场景词提示。
- Modify: `docs/citation-selection-findings.md` — 仅更新产品落地口径：删除临时报告展示作为运行能力的说法，保留其历史研究证据与三层观察结论。
- Delete: `docs/content-refactor-short-term.md` — 已被当前正式内容路线替代，且包含已删除的简报、模块写法库、随机竞品和未来实体库方案。
- Delete: `docs/content-refactor-long-term.md` — 用户明确不再规划平台微调、经验库或自进化。
- Delete: `docs/content-refactor-pattern-library-intro-design.md` — 依赖已经移除的 PatternLibrary/简报架构。
- Delete: `docs/content-refactor-examples.md` — 仅服务已删除的简报、骨架、模块验收体系。
- Delete: `docs/pattern-library-seeds-v1.json` — 已删除 PatternLibrary 的历史种子，不参与当前运行。

**Interfaces:**
- Documentation source of truth: `接手文档.md` + `docs/content-plan.md` + `docs/knowledge-base-direction.md`。
- Current competitor model: 每客户独立、按真实名称 `##` 分节的竞品知识库；对比型文章由运营明确选择至少两家分节，系统不得自动抽取或补齐。
- Explicitly out of scope: 平台偏好矩阵、运营经验库、自动权重优化、反思任务、向量/RAG 升级，以及旧 PatternLibrary/brief/随机竞品架构。

- [x] **Step 1: 写文档一致性失败检查。**

先新增或改写文档回归检查，确保当前文档不再把历史架构写成现状：

```python
def test_current_handoff_docs_do_not_reference_retired_content_architecture(self):
    root = Path(__file__).resolve().parents[1]
    current_docs = [
        root / "接手文档.md",
        root / "docs" / "content-plan.md",
        root / "docs" / "knowledge-base-direction.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in current_docs)

    self.assertNotIn("docs/content-refactor-short-term.md", text)
    self.assertNotIn("docs/content-refactor-long-term.md", text)
    self.assertNotIn("PatternLibrary", text)
    self.assertNotIn("竞品随机池", text)
    self.assertIn("运营显式选择", text)
    self.assertIn("单阶段写作", text)
```

并断言五个删除目标均不存在：

```python
for path in retired:
    self.assertFalse((root / path).exists(), path)
```

- [x] **Step 2: 运行检查确认失败。**

Run: `python -X utf8 -m unittest tests.test_content_generation_ui tests.test_formal_content_route_entry -v`

Expected: FAIL，因为现有文档仍引用旧重构、长期规划和 PatternLibrary 架构，删除目标仍存在。

- [x] **Step 3: 按当前代码重写保留文档并删除失效文件。**

保留文档只陈述已上线或明确保留的能力，不把历史施工计划、实验结论或“以后可能做”的方向伪装成当前待办。竞品相关描述统一为“独立竞品知识库 + 运营明确选择分节”；不得再写“竞品实体库待做”或自动/随机抽取。

删除列出的五个失效文件。删除前用 `Resolve-Path` 分别确认每个目标都位于当前仓库的 `docs` 目录；不要递归删除整个 `docs` 或 `docs/superpowers/plans`。保留历史引用选择证据、工程/运营说明与 `docs/superpowers/plans/` 施工记录，后者仅视为历史审计材料，不再作为当前产品说明。

- [x] **Step 4: 运行文档与回归检查。**

Run: `python -X utf8 -m unittest tests.test_content_generation_ui tests.test_formal_content_route_entry -v; rg -n "content-refactor-(short-term|long-term)|PatternLibrary|竞品随机池" 接手文档.md docs/content-plan.md docs/knowledge-base-direction.md; git diff --check`

Expected: 测试 PASS；`rg` 无匹配；保留文档准确描述当前代码路径，五个删除目标不存在。

### Task 5: 支持竞品规范改名，并让删除可由后续同步自动恢复

**Files:**
- Modify: `services/knowledge_base.py` — 在客户竞品资料库状态中保存旧名到规范名的别名映射；同步来源资料时先解析别名，再按规范名称合并章节。
- Modify: `services/competitor_knowledge.py` — 复用现有 Markdown 分节合并逻辑，使同一规范名不会产生旧名、新名两份章节。
- Modify: `app.py` — 扩展竞品资料库保存请求以接收重命名操作；继续使用既有客户访问控制。
- Modify: `templates/index.html`, `static/js/app.js` — 将竞品章节标题改为可编辑名称；删除章节后立即保存，并展示自动保存状态与重试入口。
- Modify: `tests/test_knowledge_base.py` — 覆盖改名后的来源合并和删除后的自动恢复。

**Interfaces:**
- Competitor master state adds persistent `name_aliases` metadata: `{old_name: canonical_name}`; 名称必须非空、唯一、无换行，别名链需解析到最终规范名并拒绝循环。
- `PUT /api/knowledge/competitors/<cid>` accepts pending rename operations together with current Markdown content; response remains the saved master content/metadata.
- Delete behavior: only removes the master Markdown section. It must not delete source material or add suppression/tombstone state; a future GET/refresh sync can recreate the section.

- [x] **Step 1: 写失败测试，锁定规范名称与可恢复删除。**

```python
def test_competitor_rename_merges_later_old_name_sources_under_new_name(self):
    service.save_competitor_master(
        "alice-client", "## 新名称\n\n已有事实", renames={"旧名称": "新名称"}
    )
    service.sync_competitor_master("alice-client", ["## 旧名称\n\n新增事实"])

    content = service.get_competitor_master("alice-client")
    self.assertIn("## 新名称", content)
    self.assertIn("新增事实", content)
    self.assertNotIn("## 旧名称", content)

def test_deleted_competitor_section_is_restored_by_later_source_sync(self):
    service.save_competitor_master("alice-client", "")
    service.sync_competitor_master("alice-client", ["## 可恢复竞品\n\n来源事实"])

    self.assertIn("## 可恢复竞品", service.get_competitor_master("alice-client"))
```

同时覆盖空名、重名与别名循环返回可读 400 错误；UI 回归断言标题为名称输入框而非不可编辑的 `strong`。

- [x] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base -v`

Expected: FAIL，因为当前资料库没有名称别名，旧名来源会重建旧章节，删除也只能依赖手工保存。

- [x] **Step 3: 实现规范名称迁移和可恢复删除。**

保存时在服务端校验、持久化并解析别名；合并来源 Markdown 前将来源章节名称映射为最终规范名，再调用既有合并机制。前端在每张竞品资料卡显示名称输入框，改名立即提交；提交成功后更新本地名称和别名状态。删除卡片只从当前编辑内容移除，并立即提交当前内容，不增加抑制标记。保留来源资料和 GET 时已有的同步流程，因此运营误删后可通过重新打开或刷新资料库自动找回；若该竞品曾改名，恢复内容仍落在新名称下。

- [x] **Step 4: 运行回归。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base -v; node --check static/js/app.js; git diff --check`

Expected: PASS；改名后只有规范名称章节，来源旧名不会回生；删除章节后来源同步可恢复，且不影响其他客户。

### Task 6: 为客户、竞品和场景词资料库统一自动保存

**Files:**
- Modify: `static/js/app.js` — 增加轻量的按资料库键串行保存调度器，并接入客户资料、竞品资料和 Query 场景词。
- Modify: `templates/index.html` — 将原有“保存”按钮保留为“立即保存/重试”，并在三个资料库旁展示“正在自动保存、已保存、保存失败，可重试”状态。
- Modify: `tests/test_knowledge_base.py` — 覆盖输入防抖、失焦立即保存、增加/删除/改名立即保存，以及失败后可重试的 UI 契约。

**Interfaces:**
- Existing customer、competitor、scene terms APIs do not change their payload ownership or access control.
- Text input waits 800ms after the latest edit; `blur` saves immediately. Add/remove/rename actions save immediately.
- Per-library queues prevent an older request completing after a newer request and overwriting it. Automatic success is quiet; only status is updated.

- [x] **Step 1: 写失败 UI 测试。**

```python
def test_knowledge_editors_use_shared_autosave_contract(self):
    script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    self.assertIn("scheduleKnowledgeAutosave", script)
    self.assertIn("800", script)
    self.assertIn("正在自动保存", template)
    self.assertIn("保存失败，可重试", template)
```

另行断言客户、竞品和场景词三条编辑路径都调用同一调度器，且既有保存按钮仍可立即触发对应保存函数。

- [x] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base -v`

Expected: FAIL，因为现有三处分别依赖手动保存，且没有统一状态或串行保护。

- [x] **Step 3: 最小实现统一自动保存。**

实现不引入依赖的 `scheduleKnowledgeAutosave(key, save, {immediate})`：同一键清除旧定时器、按键串行执行保存、读取最新页面状态后再发请求。客户资料保留现有删除章节的语义；竞品资料采用 Task 5 的可恢复删除；场景词仍写入现有场景词接口。把原来的成功弹窗改为手动立即保存或失败时才显示必要反馈，避免每次输入弹窗打断运营；保存失败显示可点击重试。

- [x] **Step 4: 运行回归。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base tests.test_selection_evidence_api -v; node --check static/js/app.js; git diff --check`

Expected: PASS；三类资料的修改不需反复手点保存，最新编辑不会被较旧请求覆盖，失败仍可明确重试。

### Task 7: 为质量门禁自动保存，并明确行业写法库的即时入库行为

**Files:**
- Modify: `static/js/app.js` — 将通用质量门禁和行业质量门禁接入同一自动保存调度器，移除每次保存的确认弹窗。
- Modify: `templates/index.html` — 保留通用/行业质量门禁的适用范围说明，按钮改作“立即保存/重试”，增加自动保存状态。
- Modify: `tests/test_knowledge_base.py` or a focused quality UI test — 覆盖两种质量门禁的自动保存与既有接口参数。
- Verify only: `static/js/app.js` industry route actions — 新建于引用情报分析、删除路线本已直接调用后端，不新增冗余保存层；在相关 UI 文案中标明“操作已入库”。

**Interfaces:**
- Common quality policy continues to save through the current global-policy API and must retain its全局影响提示；industry policy continues using its existing industry-scoped endpoint.
- Both policy editors use 800ms input debounce and immediate blur/add/remove save. No `confirm()` gate remains.
- Industry route creation/deletion remains immediate persistence; no artificial Save button is added.

- [x] **Step 1: 写失败测试。**

```python
def test_quality_policies_use_autosave_without_confirmation_dialog(self):
    script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

    self.assertIn("scheduleKnowledgeAutosave('quality-common'", script)
    self.assertIn("scheduleKnowledgeAutosave('quality-industry'", script)
    self.assertNotIn("confirm('确认保存全局质量门禁", script)
```

- [x] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base -v`

Expected: FAIL，因为当前质量门禁仅在手动点击时保存，通用规则还会弹确认框。

- [x] **Step 3: 实现质量门禁自动保存并保持作用域透明。**

复用 Task 6 调度器，通用、行业质量门禁分别使用独立 key。输入和失焦自动保存；规则增删直接保存。保留“影响全部客户/仅本行业”的醒目文字，取消确认弹窗。核对行业写法库的引用情报生成和删除路线仍为直接写库，仅补充“已入库”状态，不制造第二套草稿与保存逻辑。

- [x] **Step 4: 运行回归。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base tests.test_query_platform_reference_api -v; node --check static/js/app.js; git diff --check`

Expected: PASS；所有可编辑知识资料具备一致的自动保存体验，通用质量门禁的广泛影响仍清晰可见，行业写法库操作立即入库。

### Task 8: 为非质量门禁知识库提供分类 Word 下载

**Files:**
- Modify: `app.py` — 为客户资料、竞品资料、Query 场景词和行业写法库增加受权限保护的 DOCX 下载路由。
- Add: `services/knowledge_export.py` — 以标准 Word 结构生成四类只含已保存资料的 DOCX，并统一文件名、标题、空内容处理与响应头。
- Modify: `templates/index.html`, `static/js/app.js` — 在四个对应资料库区块增加下载按钮；质量门禁和系统提示词区块不增加下载入口。
- Modify: `requirements.txt` or existing dependency manifest — 仅在当前运行依赖未提供 DOCX 生成能力时，明确加入最小依赖。
- Add/Modify: `tests/test_knowledge_export.py` — 覆盖四类文档、权限、文件名、MIME 类型、空内容，以及质量门禁、系统提示词无下载入口。

**Interfaces:**
- Proposed routes: `GET /api/knowledge/exports/customer/<cid>.docx`、`competitors/<cid>.docx`、`scenes/<cid>.docx`、`industry-routes/<industry>.docx`。
- 客户资料、竞品资料、场景词均基于当前选中客户；写法库基于当前选中行业。服务端再次校验访问权限，不依赖前端隐藏按钮。
- 文档标题和文件名采用“资料库类型-客户或行业-导出日期.docx”；竞品整库按竞品名称使用 Word 标题分节。质量门禁无下载 API、无下载按钮。

- [x] **Step 1: 写失败测试，锁定下载范围与数据边界。**

```python
def test_customer_knowledge_export_is_a_docx_for_the_current_client(self):
    response = alice.get("/api/knowledge/exports/customer/alice-client.docx")

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.mimetype,
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    self.assertTrue(response.data.startswith(b"PK"))
    self.assertIn("attachment;", response.headers["Content-Disposition"])

def test_non_exportable_knowledge_surfaces_have_no_export_api(self):
    self.assertEqual(alice.get("/api/knowledge/exports/quality/common.docx").status_code, 404)
    self.assertEqual(alice.get("/api/knowledge/exports/system-prompts.docx").status_code, 404)
```

对四类正文解析 DOCX 验证：包含相应已保存资料和正确层级，不包含别名映射、删除/抑制状态、原始网页或 API 密钥；另覆盖跨客户请求为 404/403。

- [x] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_knowledge_export -v`

Expected: FAIL，因为当前没有 DOCX 导出路由或下载按钮。

- [x] **Step 3: 最小实现分类导出。**

先确认项目现有 DOCX 生成依赖；若不存在，再采用成熟且最小的 Word 生成库，不自行拼接 OOXML。导出服务只接收已授权的领域数据，构建简洁的“标题、导出日期、分节正文”文档；不要将 Markdown 内部标记、系统提示词、别名或原始来源资料透传给用户。前端仅以普通下载链接/请求触发浏览器下载，不新增上传、历史版本或打包下载功能。空资料库返回明确提示而非生成空白文件。

为每种导出样例生成 DOCX 后，按文档产出规范用 `render_docx.py` 渲染为 PNG，并逐页人工检查中文、标题、分节和分页是否正常；修正后重新渲染。该渲染产物仅用于测试/验收，不向运营提供。

- [x] **Step 4: 运行回归与 DOCX 验收。**

Run: `python -X utf8 -m unittest tests.test_knowledge_export tests.test_knowledge_base -v; node --check static/js/app.js; git diff --check`

Expected: PASS；四类下载只导出其已保存的可见资料，质量门禁与系统提示词没有下载表面，跨客户下载不泄露数据，样例 DOCX 渲染无中文乱码、截断或错误分页。

### Task 9: 增加只读的系统提示词目录

**Files:**
- Add: `services/prompt_catalog.py` — 显式登记可展示的提示词模板、分类、用途说明、变量说明和来源标识；不提供任意文件读取能力。
- Modify: `app.py` — 增加只读目录 API，并保留现有登录/访问控制。
- Modify: `templates/index.html`, `static/js/app.js` — 在知识库增加“系统提示词（只读）”模块，提供分类切换、用途说明、模板正文和变量说明；不提供任何输入框或保存按钮。
- Add/Modify: `tests/test_prompt_catalog.py` — 覆盖目录白名单、只读 HTTP 方法、敏感数据排除和 UI 无编辑入口。

**Interfaces:**
- Proposed catalog categories: `内容生产 / 介绍型`、`内容生产 / 对比型`、`资料解析 / 客户资料`；在代码中确认实际存在且用于模型调用后，再补充竞品资料解析、引用情报分析等条目。
- `GET /api/system-prompts` returns only catalog entries. No `PUT`/`POST`/`DELETE` route is provided.
- 每个条目展示静态模板和占位符说明（例如 `{{customer_facts}}`），而不是某位客户的最终渲染 prompt。

- [x] **Step 1: 写失败测试，锁定只读目录的范围。**

```python
def test_system_prompt_catalog_exposes_only_approved_templates(self):
    response = client.get("/api/system-prompts")
    entries = response.get_json()["items"]

    self.assertEqual(response.status_code, 200)
    self.assertIn("内容生产 / 介绍型", [item["category"] for item in entries])
    self.assertIn("内容生产 / 对比型", [item["category"] for item in entries])
    self.assertNotIn("customer_facts_value", response.get_data(as_text=True))
    self.assertNotIn("api_key", response.get_data(as_text=True).lower())

def test_system_prompt_catalog_has_no_write_api(self):
    self.assertEqual(client.put("/api/system-prompts").status_code, 405)
```

UI 测试断言存在可选择的纯文本代码块及分类选择，但不含 `contenteditable`、`textarea`、保存、删除或专用复制按钮。

- [x] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_prompt_catalog -v`

Expected: FAIL，因为当前没有受控提示词目录或只读 UI。

- [x] **Step 3: 实现白名单目录与只读展示。**

从当前实际模型调用处提取仅供理解规则的静态指令模板；将动态资料改写为明确占位符，并在条目中说明这些变量来自哪里、是否会传给模型。目录只能返回服务端白名单中的键，绝不接收路径、模块名或任意 prompt 文本参数。前端用可选择的预格式化纯文本代码块展示内容，运营可使用浏览器正常复制粘贴；不增加专用复制按钮或下载入口，并附“仅供查看，不能在此修改；实际规则随代码发布更新”说明。用户不能通过该模块写入任何系统提示词。

- [x] **Step 4: 运行回归。**

Run: `python -X utf8 -m unittest tests.test_prompt_catalog tests.test_content_generation_ui tests.test_formal_content_route_entry -v; node --check static/js/app.js; git diff --check`

Expected: PASS；运营可查看介绍型、对比型、客户资料解析等经审核模板，无法编辑，接口不会泄露任何客户实际资料、抓取内容或密钥。

### 后续讨论项（不纳入本轮实现）

在 Task 1–9 全部完成并验收后，再基于真实耗时和样例结果讨论以下两项；本轮不改变相关生成流程或合并阈值：

- **生成耗时：** 评估“引用情报分析”和“当日数据整理 → 生成竞品资料”的端到端耗时，区分模型调用、网页抓取、串行处理和写库耗时后，再决定是否需要并行、缓存、减少输入或调整交互反馈。
- **写法库合并：** 复核引用情报分析对相似路线的合并是否过严。以重复保留、错误合并、未合并三类真实样例设定可解释的判断规则，避免在没有样本的情况下直接放宽。

## Self-Review

- 临时报告：Task 1 覆盖页面、前端调用、后端路由、测试、文档和实际报告目录；场景词提示与离线研究工具明确保留。
- 单平台矩阵：Task 2 覆盖平台按钮、默认选择、客户端请求、服务端强制校验、精确过滤及回归测试；没有“全部平台”回退。
- 引用情报默认范围：Task 3 只改变问题下拉框默认值，不改变具体 Query、整组任务或单平台 API 契约。
- 文档：Task 4 将完成能力集中到四份当前文档，删除与当前代码冲突的内容路线文档，并明确竞品知识库已完成、长期自进化不再排期。
- 竞品边界：Task 5 将改名实现为可追溯的规范名称映射；删除不伤及来源资料，后续同步可恢复误删内容。
- 自动保存：Task 6、7 将客户、竞品、场景词和两类质量门禁统一为防抖、失焦、结构操作即时保存，并保留失败重试；行业写法库继续沿用既有即时入库。
- 导出：Task 8 为客户资料、竞品资料、场景词和行业写法库提供各自受权限保护的 DOCX；质量门禁与系统提示词目录明确排除，导出文档须经过渲染验收。
- 提示词：Task 9 以服务端白名单和可选择的纯文本展示经审核的静态模板与变量说明；保持只读、不加下载或专用复制操作，也不暴露最终请求、客户资料、抓取内容或密钥。
- 隔离：两个任务均保留现有客户访问控制，新增平台校验不暴露其他客户数据。
- 计划中没有新依赖、爬虫改动、模型调用或对已满意的内容生产开头改动。
