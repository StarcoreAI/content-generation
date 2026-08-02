# 知识库资料中心与可配置质量门禁 Implementation Plan

> **状态：已废弃，禁止执行。** 本文件在讨论过程中被 `docs/knowledge-base-direction.md` 覆盖：不做问法库；客户知识库是一份带来源标记的八方向总资料；竞品知识库是一份按竞品名称分节的总资料；竞品资料主来源改为当日高频引用文章和上传资料；质量规则只分通用/行业，且仅作提醒。知识库与选择层证据的现行施工计划是 `docs/superpowers/plans/2026-07-26-knowledge-hub-and-selection-evidence.md`；质量门禁随后单独立计划，不能沿用本文的客户专属规则。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不依赖内容生产、不改动写法库的前提下，给每个客户建立可追溯、可人工编辑的资料中心，并让质量门禁支持运营维护违禁词、必须做与禁止做的规则，以及人工粘贴文章检查。

**Architecture:** 资料中心只读取既有客户/竞品产物，首次或手动同步时把四份“最新 Markdown”做成带来源快照的知识文档；人工修改后的文档永不被自动覆盖。爬取与引用情报只以只读概览进入资料中心。质量规则分为管理员维护的全局补充违禁词和客户专属规则，门禁每次运行都即时读取它们；原有内容生产仍可调用同一门禁，但不是资料中心和门禁页面的前置条件。

**Tech Stack:** Flask、Python 标准库 JSON/`pathlib`、现有 `services.storage`、vanilla JavaScript、`unittest`/mock。

## Global Constraints

- **不修改** `services/pattern_library.py`、写法库 API、引用情报入库流程或内容生产抽样逻辑；写法库只保留现状。
- 客户资料、竞品资料、质量规则和人工检查结果只可在 `client:<cid>` 范围读取和写入；现有 `require_client_access(cid)` 继续作为所有客户级路由的权限门。
- 不迁移、不删除既有 `data/uploads/`、`data/material_packages/`、`data/competitor_material_packages/` 或已有文章/门禁记录；新库只新增 `data/knowledge_base/` 与质量规则 JSON。
- 资料中心不调用 LLM、Tavily、爬虫或内容生成；它只合并既有产物并允许人工编辑。
- 来源文档与人工编辑文档必须可区分；手工改过的内容遇到上游资料更新时默认保留，不能静默覆盖。
- 质量门禁的全局补充违禁词仅 admin 可编辑；客户专属违禁词、必须做、禁止做由有该客户访问权的用户编辑。全局规则不得含客户专属事实。
- “必须做/禁止做”是语义规则，进入 LLM 门禁并以 `warn` 呈现；短语级硬拦截仍放在违禁词表。LLM 异常继续 fail-open，返回 `warn` 留痕。
- 新增 LLM 调用的 `max_tokens >= 4000`；本计划不新增 LLM 调用。
- 不重启服务、不部署、不真实爬取、不真实调用 LLM/Tavily；开发验证只用 mock 与单元测试。

---

## 现有产物映射（实施前确认）

| 知识文档 ID | 来源文件 | 性质 | 同步规则 |
| --- | --- | --- | --- |
| `customer-injection` | `data/material_packages/<cid>/latest_injection.md` | 客户资料八方向整理 | 未人工编辑时更新；人工编辑后标记“来源有更新” |
| `customer-web-supplement` | `data/material_packages/<cid>/latest_web_supplement.md` | 客户联网扩展 | 同上 |
| `competitor-upload` | `data/competitor_material_packages/<cid>/latest_upload_competitors.md` | 上传竞品资料整理 | 同上 |
| `competitor-web` | `data/competitor_material_packages/<cid>/latest_web_competitors.md` | 竞品联网资料整理 | 同上 |

资料中心还返回只读引用概览：`services.record_insights.build_record_insights(...)` 的记录数、引用数、品牌提及率、Top 引用文章和竞品实体。它不被导入为可编辑事实，也不回写 `raw_records.json`。

## 数据结构

`data/knowledge_base/<cid>.json`：

```json
{
  "schema_version": 1,
  "client_id": "cid",
  "documents": [
    {
      "id": "customer-injection",
      "kind": "customer",
      "title": "AI解析客户资料包",
      "content": "# 客户资料注入包\n...",
      "source": {
        "path": "data/material_packages/cid/latest_injection.md",
        "digest": "sha256...",
        "imported_content": "# 客户资料注入包\n...",
        "imported_at": "2026-07-26 10:00:00",
        "source_changed": false
      },
      "created_at": "2026-07-26 10:00:00",
      "updated_at": "2026-07-26 10:00:00"
    },
    {
      "id": "note_<uuid>",
      "kind": "note",
      "title": "运营备注",
      "content": "...",
      "source": null,
      "created_at": "2026-07-26 10:00:00",
      "updated_at": "2026-07-26 10:00:00"
    }
  ]
}
```

质量规则：

```text
data/quality_gate/banned_words.json                 # 全局补充词，沿用既有预留路径
data/quality_gate/client_policies/<cid>.json        # 客户专属规则
```

客户专属规则文件固定为：

```json
{
  "schema_version": 1,
  "client_id": "cid",
  "banned_words": ["短语级硬拦截词"],
  "must_do": ["正文说明费用以实际方案为准"],
  "must_not_do": ["不得提及未授权的第三方品牌"],
  "updated_at": "2026-07-26 10:00:00"
}
```

### Task 1: 新建知识库服务，安全同步四份既有资料

**Files:**
- Create: `services/knowledge_base.py`
- Create: `tests/test_knowledge_base.py`

**Interfaces:**
- Produces `KnowledgeBase(root_dir, now_fn=None)`。
- Produces `load(client_id) -> dict`、`sync_sources(client_id, source_paths, force_ids=()) -> dict`、`update_document(client_id, document_id, title, content) -> dict`、`create_note(client_id, title, content) -> dict`、`delete_note(client_id, document_id) -> bool`。
- Consumes `{id, kind, title, path}` source descriptors assembled by `app.py`。

- [ ] **Step 1: 写出会失败的来源合并测试。**

```python
def test_sync_creates_four_source_documents_and_keeps_manual_edit(tmp_path):
    customer = tmp_path / "customer.md"
    competitor = tmp_path / "competitor.md"
    customer.write_text("客户原始整理", encoding="utf-8")
    competitor.write_text("竞品原始整理", encoding="utf-8")
    store = KnowledgeBase(tmp_path / "knowledge", now_fn=lambda: "2026-07-26 10:00:00")
    sources = [
        {"id": "customer-injection", "kind": "customer", "title": "AI解析客户资料包", "path": customer},
        {"id": "competitor-web", "kind": "competitor", "title": "竞品联网资料", "path": competitor},
    ]

    first = store.sync_sources("client-a", sources)
    self.assertEqual([item["id"] for item in first["documents"]], ["customer-injection", "competitor-web"])
    store.update_document("client-a", "customer-injection", "客户汇总", "人工合并后的客户口径")
    customer.write_text("上游新资料", encoding="utf-8")

    second = store.sync_sources("client-a", sources)
    edited = next(item for item in second["documents"] if item["id"] == "customer-injection")
    self.assertEqual(edited["content"], "人工合并后的客户口径")
    self.assertTrue(edited["source"]["source_changed"])
```

- [ ] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base -v`  
Expected: FAIL，提示 `services.knowledge_base` 不存在。

- [ ] **Step 3: 实现最小 JSON 知识库。**

```python
def sync_sources(self, client_id, source_paths, force_ids=()):
    store = self.load(client_id)
    by_id = {item["id"]: item for item in store["documents"]}
    for descriptor in source_paths:
        path = Path(descriptor["path"])
        if not path.exists() or not path.read_text(encoding="utf-8", errors="ignore").strip():
            continue
        latest = path.read_text(encoding="utf-8", errors="ignore").strip()
        digest = hashlib.sha256(latest.encode("utf-8")).hexdigest()
        current = by_id.get(descriptor["id"])
        if current is None:
            by_id[descriptor["id"]] = self._source_document(descriptor, latest, digest)
        elif current["source"]["imported_content"] == current["content"] or descriptor["id"] in set(force_ids):
            self._replace_source_content(current, latest, digest)
        else:
            current["source"]["source_changed"] = current["source"].get("digest") != digest
    store["documents"] = [by_id[key] for key in self.SOURCE_ORDER if key in by_id] + self._notes(by_id)
    self._save(client_id, store)
    return store
```

`update_document` 只允许更新已有文档的非空标题/正文；`delete_note` 遇到任何 `source` 非空的文档必须返回 `False`，从而绝不删除原始资料来源或其索引。使用 `services.storage.update_json` 保证单 worker 多线程下的原子读改写。

- [ ] **Step 4: 补笔记与强制覆盖测试。**

```python
def test_note_can_be_deleted_but_source_document_cannot(tmp_path):
    store = KnowledgeBase(tmp_path / "knowledge")
    note = store.create_note("client-a", "运营备注", "客户确认不写低价承诺")
    self.assertTrue(store.delete_note("client-a", note["id"]))
    self.assertFalse(store.delete_note("client-a", "customer-injection"))

def test_force_sync_replaces_a_manually_edited_source(tmp_path):
    # 准备 source，再人工编辑；传 force_ids=["customer-injection"] 后断言正文回到上游最新文本。
```

- [ ] **Step 5: 运行服务测试。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base -v`  
Expected: PASS；包含首次导入、人工编辑保护、强制覆盖、笔记增删四类断言。

### Task 2: 建立资料中心 API，并只读接入爬取引用概览

**Files:**
- Modify: `app.py:1355-1900`
- Modify: `tests/test_materials_api.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Produces `GET /api/knowledge-base/<cid>`。
- Produces `POST /api/knowledge-base/<cid>/sync`，body optional `{force_ids: ["customer-injection"]}`。
- Produces `POST /api/knowledge-base/<cid>/notes`、`PUT /api/knowledge-base/<cid>/documents/<id>`、`DELETE /api/knowledge-base/<cid>/notes/<id>`。
- `GET` returns `{knowledge_base, citation_summary}`；`citation_summary` 只读，来自 `build_record_insights`。

- [ ] **Step 1: 写路由、来源和隔离的失败测试。**

```python
def test_knowledge_base_sync_merges_existing_customer_and_competitor_outputs(self):
    material_dir = Path(geo_app.D) / "material_packages" / self.client_id
    competitor_dir = Path(geo_app.D) / "competitor_material_packages" / self.client_id
    material_dir.mkdir(parents=True)
    competitor_dir.mkdir(parents=True)
    (material_dir / "latest_injection.md").write_text("客户八方向资料", encoding="utf-8")
    (competitor_dir / "latest_web_competitors.md").write_text("## 机构甲\n竞品资料", encoding="utf-8")

    response = self.client.post(f"/api/knowledge-base/{self.client_id}/sync", json={})
    documents = response.get_json()["knowledge_base"]["documents"]
    self.assertEqual([item["id"] for item in documents], ["customer-injection", "competitor-web"])

def test_other_operator_cannot_read_or_edit_knowledge_base(self):
    response = self.other_client.get(f"/api/knowledge-base/{self.client_id}")
    self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: 运行测试确认路由不存在。**

Run: `python -X utf8 -m unittest tests.test_materials_api tests.test_auth.UserSettingsTests -v`  
Expected: FAIL，`/api/knowledge-base/...` 返回 404。

- [ ] **Step 3: 在 `app.py` 复用既有路径函数，新增小型路由。**

```python
def knowledge_base_service():
    return KnowledgeBase(Path(D) / "knowledge_base")

def knowledge_base_sources(cid):
    material_dir = material_package_output_dir(cid)
    competitor_dir = competitor_package_output_dir(cid)
    return [
        {"id": "customer-injection", "kind": "customer", "title": "AI解析客户资料包", "path": material_dir / "latest_injection.md"},
        {"id": "customer-web-supplement", "kind": "customer", "title": "AI联网扩展资料", "path": material_dir / "latest_web_supplement.md"},
        {"id": "competitor-upload", "kind": "competitor", "title": "上传竞品资料整理", "path": competitor_dir / "latest_upload_competitors.md"},
        {"id": "competitor-web", "kind": "competitor", "title": "竞品联网资料整理", "path": competitor_dir / "latest_web_competitors.md"},
    ]

@app.route("/api/knowledge-base/<cid>/sync", methods=["POST"])
def sync_knowledge_base(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    force_ids = (request.get_json(silent=True) or {}).get("force_ids") or []
    store = knowledge_base_service().sync_sources(cid, knowledge_base_sources(cid), force_ids)
    return jsonify({"ok": True, "knowledge_base": store})
```

`GET` 不触发同步，只返回已保存的库和 `build_record_insights(load_client_records(...))` 的精简字段：`total_records`、`total_refs`、`mention_rate`、`top_articles[:10]`、`mentioned_entities[:10]`。这样打开页面不会重写资料，也不会触发 LLM。

- [ ] **Step 4: 实现编辑与笔记 API，限制输入。**

```python
@app.route("/api/knowledge-base/<cid>/documents/<document_id>", methods=["PUT"])
def update_knowledge_document(cid, document_id):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    data = request.get_json(silent=True) or {}
    try:
        document = knowledge_base_service().update_document(
            cid, document_id, str(data.get("title") or "")[:120], str(data.get("content") or "")[:50000]
        )
    except KeyError:
        return jsonify({"error": "knowledge_document_not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "document": document})
```

笔记创建也限制标题 120 字、正文 50,000 字；删除只调用 `delete_note`，来源文档一律返回 `409 source_document_cannot_be_deleted`。

- [ ] **Step 5: 运行 API 与权限测试。**

Run: `python -X utf8 -m unittest tests.test_materials_api tests.test_auth.UserSettingsTests -v`  
Expected: PASS；无客户资料时同步为空库、有任一来源时精确入库、跨客户 404、来源文档不可删、笔记可删。

### Task 3: 在网页增加“知识库”入口，集中查看、同步和编辑

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `static/css/app.css`
- Modify: `tests/test_content_generation_ui.py`

**Interfaces:**
- Produces `loadKnowledgeBase()`、`syncKnowledgeBase(forceIds=[])`、`editKnowledgeDocument(id)`、`saveKnowledgeDocument()`、`createKnowledgeNote()`。
- Consumes Task 2 的 API；不调用内容生成 API。

- [ ] **Step 1: 写静态页面接线失败测试。**

```python
def test_knowledge_base_page_is_independent_of_content_generation(self):
    self.assertIn("navTo('knowledge'", self.template)
    self.assertIn('id="page-knowledge"', self.template)
    self.assertIn("loadKnowledgeBase", self.script)
    self.assertIn("/api/knowledge-base/", self.script)
    self.assertNotIn("generateContentArticle()", self.template[self.template.index('id="page-knowledge"'):])
```

- [ ] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_content_generation_ui -v`  
Expected: FAIL，因为知识库导航和脚本尚不存在。

- [ ] **Step 3: 增加最小页面。**

```html
<div class="s-nav" onclick="navTo('knowledge',this)"><i class="ti ti-books"></i>知识库</div>

<div class="page" id="page-knowledge">
  <div class="pg-hd">
    <div><div class="pg-title">✦ <em>知识库</em></div><div class="pg-sub">集中管理客户、竞品与引用情报；不会自动参与内容生产。</div></div>
    <div class="acts"><button class="btn btn-o btn-sm" onclick="loadKnowledgeBase()">刷新</button><button class="btn btn-p btn-sm" onclick="syncKnowledgeBase()">同步现有资料</button></div>
  </div>
  <div class="card"><div class="card-hd"><span class="card-title">引用情报概览（只读）</span></div><div id="knowledgeCitationSummary"></div></div>
  <div class="card"><div class="card-hd"><span class="card-title">合并资料</span><button class="btn btn-o btn-sm" onclick="createKnowledgeNote()">新增运营备注</button></div><div id="knowledgeDocumentList"></div></div>
</div>
```

每张来源文档卡显示“客户资料/竞品资料”、来源文件名、最后同步时间、`来源有更新` 徽标、编辑按钮；来源有更新时编辑框明确提供“保留人工版本”和“用最新来源覆盖”两个按钮。运营备注可以编辑和删除。引用概览仅显示数值、Top10 引用文章和实体，不提供编辑或“导入成事实”的按钮。

- [ ] **Step 4: 做页面验证。**

Run: `python -X utf8 -m unittest tests.test_content_generation_ui -v; node --check static\js\app.js`  
Expected: PASS；页面不包含内容生成按钮，JavaScript 无语法错误。

### Task 4: 新建质量规则存储，并让门禁实时合并全局与客户规则

**Files:**
- Create: `services/quality_gate_policies.py`
- Modify: `services/quality_gate.py`
- Modify: `tests/test_quality_gate.py`
- Create: `tests/test_quality_gate_policies.py`

**Interfaces:**
- Produces `QualityGatePolicyStore(root_dir, now_fn=None)`。
- Produces `load_global_banned_words() -> list[str]`、`save_global_banned_words(words) -> list[str]`、`load_client_policy(cid) -> dict`、`save_client_policy(cid, banned_words, must_do, must_not_do) -> dict`。
- Extends `run_quality_gate(..., policy=None)`；`policy` contains `banned_words`、`must_do`、`must_not_do`.

- [ ] **Step 1: 写失败测试，锁定规则隔离和实时读取。**

```python
def test_client_policy_isolated_and_normalizes_phrase_lists(tmp_path):
    store = QualityGatePolicyStore(tmp_path, now_fn=lambda: "2026-07-26 10:00:00")
    saved = store.save_client_policy("client-a", [" 禁用甲 ", "禁用甲"], ["必须写甲"], ["不能写乙"])
    self.assertEqual(saved["banned_words"], ["禁用甲"])
    self.assertEqual(store.load_client_policy("client-b")["banned_words"], [])

def test_client_banned_phrase_blocks_without_module_reload():
    report = run_quality_gate(
        "中性标题", "这里含客户禁用甲", {}, {}, client_brand="", competitor_names=[],
        competitor_markdown="", recent_articles=[], ai_json_fn=lambda *_: {"checks": []},
        policy={"banned_words": ["禁用甲"], "must_do": [], "must_not_do": []},
    )
    self.assertEqual(report["verdict"], "blocked")
    self.assertIn("禁用甲", report["code_layer"][0]["evidence"])
```

- [ ] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_quality_gate tests.test_quality_gate_policies -v`  
Expected: FAIL，缺少 `QualityGatePolicyStore`，且 `run_quality_gate` 不接受 `policy`。

- [ ] **Step 3: 实现规则存储和门禁合并。**

```python
def check_banned_words(article_content, banned_words=None, industry="", extra_words=None):
    merged = dict(banned_words or load_banned_words())
    merged["client_custom"] = _normalize_phrases(extra_words)
    industry_words = _industry_banned_words(industry)
    if industry_words:
        merged["industry"] = industry_words
    # 后续匹配循环保持原有“警示语境 = warn”的行为。

def run_quality_gate(..., industry="", policy=None):
    policy = policy or {"banned_words": [], "must_do": [], "must_not_do": []}
    code_layer = [
        check_banned_words(article_content, industry=industry, extra_words=policy["banned_words"]),
        check_title_brand(...), check_meta_discourse(...), check_shingle_duplicate(...),
    ]
```

删除模块导入时冻结的 `BANNED_WORDS = load_banned_words()` 使用点：每次 `check_banned_words` 未传显式词表时都调用 `load_banned_words()`，从而运营保存 `data/quality_gate/banned_words.json` 后无需重启服务。`_quality_gate_prompt` 增加两段固定输入：

```text
运营要求必须做到：<JSON list>
运营要求禁止做到：<JSON list>
```

并要求 LLM 返回 `operator_must_do`、`operator_must_not_do` 检查项；它们由现有 `_parse_llm_checks` 归为 `warn`，不改变 fail-open 机制。

- [ ] **Step 4: 补全门禁规则测试。**

```python
def test_operator_rules_enter_llm_prompt_as_warning_checks(self):
    prompts = []
    report = run_quality_gate(
        "标题", "正文", {}, {}, client_brand="", competitor_names=[], competitor_markdown="",
        recent_articles=[], policy={"banned_words": [], "must_do": ["说明费用边界"], "must_not_do": ["不得攻击同行"]},
        ai_json_fn=lambda prompt, _tokens: prompts.append(prompt) or {"checks": [{"check_id": "operator_must_do", "passed": False, "evidence": ["缺费用边界"]}]},
    )
    self.assertIn("说明费用边界", prompts[0])
    self.assertEqual("warn", report["verdict"])
```

- [ ] **Step 5: 运行质量门禁测试。**

Run: `python -X utf8 -m unittest tests.test_quality_gate tests.test_quality_gate_policies -v`  
Expected: PASS；原有医疗/教育/金融词与警示语境测试仍通过，新增客户词无需重启即可生效。

### Task 5: 质量门禁独立配置与人工粘贴检查

**Files:**
- Modify: `app.py:2289-2311, 2724-2798`
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_auth.py`
- Modify: `tests/test_content_generation_ui.py`

**Interfaces:**
- Produces `GET|PUT /api/quality-gate/<cid>/policy`。
- Produces `GET|PUT /api/quality-gate/global-banned-words`；PUT admin-only。
- Produces `POST /api/quality-gate/<cid>/review` with `{title, content}`。
- Existing `content_article_gate_report` and `_run_content_generation` pass the current client policy into `run_quality_gate`。

- [ ] **Step 1: 写 API 与权限失败测试。**

```python
def test_operator_can_edit_owned_client_policy_and_run_manual_review(self):
    saved = self.client.put(f"/api/quality-gate/{self.client_id}/policy", json={
        "banned_words": ["禁止词"], "must_do": ["说明限制"], "must_not_do": ["攻击同行"],
    })
    self.assertEqual(saved.status_code, 200)
    with patch.object(geo_app, "ai_json", return_value={"checks": []}):
        reviewed = self.client.post(f"/api/quality-gate/{self.client_id}/review", json={
            "title": "中性标题", "content": "正文含禁止词",
        })
    self.assertEqual(reviewed.get_json()["report"]["verdict"], "blocked")

def test_operator_cannot_edit_global_words_or_other_client_policy(self):
    self.assertEqual(self.client.put("/api/quality-gate/global-banned-words", json={"words": ["词"]}).status_code, 404)
    self.assertEqual(self.other_client.get(f"/api/quality-gate/{self.client_id}/policy").status_code, 404)
```

- [ ] **Step 2: 运行测试确认失败。**

Run: `python -X utf8 -m unittest tests.test_auth.UserSettingsTests tests.test_quality_gate -v`  
Expected: FAIL，质量规则路由不存在。

- [ ] **Step 3: 实现路由，并将规则接进既有自动门禁。**

```python
@app.route("/api/quality-gate/<cid>/review", methods=["POST"])
def review_manual_quality_gate(cid):
    if not require_client_access(cid):
        return jsonify({"error": "client_not_found"}), 404
    data = request.get_json(silent=True) or {}
    title, content = str(data.get("title") or "").strip(), str(data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content_required"}), 400
    client, sources = get_client(cid) or {}, read_content_generation_sources(cid)
    report = run_quality_gate(
        title, content, {}, {}, client_brand=client.get("brand", ""),
        competitor_names=quality_gate_competitor_names(sources["competitor_markdown"]),
        competitor_markdown=sources["competitor_markdown"], recent_articles=[], ai_json_fn=ai_json,
        customer_material_text=sources["customer_material_text"], content_upload_text="",
        industry=client.get("industry", ""), policy=quality_gate_policy_store().load_client_policy(cid),
    )
    return jsonify({"ok": True, "report": report})
```

手工检查不写入 `ContentGenerationStore`，也不产生发布草稿；它是纯检查工具。`content_article_gate_report` 与 `_run_content_generation` 只增加 `policy=quality_gate_policy_store().load_client_policy(cid)` 参数，其他生成逻辑不改。

- [ ] **Step 4: 增加最小门禁页面配置和检查区。**

```html
<div class="card"><div class="card-hd"><span class="card-title">客户质量规则</span><button class="btn btn-p btn-sm" onclick="saveQualityPolicy()">保存规则</button></div>
  <label>补充违禁词（每行一个，命中即拦截）</label><textarea id="qualityBannedWords"></textarea>
  <label>必须做到（每行一个，语义提示）</label><textarea id="qualityMustDo"></textarea>
  <label>禁止做（每行一个，语义提示）</label><textarea id="qualityMustNotDo"></textarea>
</div>
<div class="card"><div class="card-hd"><span class="card-title">人工文章检查</span><button class="btn btn-o btn-sm" onclick="runManualQualityReview()">运行门禁</button></div>
  <input id="manualQualityTitle" placeholder="标题（可选）"><textarea id="manualQualityContent" rows="12" placeholder="粘贴待检查的文章正文"></textarea><div id="manualQualityResult"></div>
</div>
```

页面加载客户后调用 `loadQualityPolicy()`；保存后重新加载并提示“已生效”。管理员额外显示全局补充违禁词卡；运营只显示只读的全局词数量，不能看到或编辑其他客户规则。人工检查沿用现有 `qualityGateCheckDescription` 和报告徽标渲染，不进入文章审核列表。

- [ ] **Step 5: 运行完整回归。**

Run: `python -X utf8 -m unittest tests.test_knowledge_base tests.test_quality_gate_policies tests.test_quality_gate tests.test_materials_api tests.test_auth.UserSettingsTests tests.test_content_generation_ui -v; node --check static\js\app.js; .\run_tests.bat; git diff --check`  
Expected: 全部 PASS；不发真实 LLM/Tavily/供应商请求，且没有空白错误。

## 验收矩阵

| 用户目标 | 验收方式 |
| --- | --- |
| 多份客户、竞品资料合并 | 为一个测试客户准备任意两份以上现有 Markdown，点“同步现有资料”，知识库出现相应来源文档，且每张保留来源路径和同步时间。 |
| 人工编辑不被覆盖 | 修改任一来源文档，再更新上游 `latest_*.md` 并同步；页面显示“来源有更新”，人工正文不变；点“用最新来源覆盖”后才替换。 |
| 资料中心不依赖内容生产 | 不创建/不生成文章时，也能同步资料、添加运营备注、看引用概览和使用人工门禁检查。 |
| 写法库保持原样 | `data/pattern_library/`、写法库路由、`services/pattern_library.py` 无改动；原有写法库测试通过。 |
| 违禁词可编辑且即时生效 | 为客户保存一个补充词，立刻用人工检查粘贴包含该词的文本，返回 `blocked`；不重启服务。 |
| 必须做/禁止做进入检查 | 保存一条规则，用 mock 门禁断言提示词包含该规则；真实页面报告以 warn 展示，不因 LLM 故障丢弃检查结果。 |
| 客户隔离 | A 运营访问 B 客户的知识库、质量规则、人工检查 API 一律 404；A 的规则不进入 B 的门禁。 |

## 自检

- 需求覆盖：资料合并与编辑由 Task 1–3 完成；违禁词和必须/禁止规则由 Task 4–5 完成；人工独立门禁由 Task 5 完成；写法库不改写入全局约束和验收矩阵。
- 无复杂 RAG、向量库、数据库迁移、自动内容生成或资料自动覆盖。
- 后续如需要“逐条事实卡、来源级差异比对、质量报告历史入库”，应另立计划；本版本先以可编辑的来源文档和人工检查闭环解决当前问题。
