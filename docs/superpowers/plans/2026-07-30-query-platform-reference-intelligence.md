# Query × AI 平台引用情报一键分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 运营只选择问题组、Query 和单个 AI 平台，即可从该 Query × 平台的实际引用记录中抽取两篇文章、完成逐篇分析，并在批次结束后由单独的 LLM 合并到行业写法库。

**Architecture:** 新任务不读取当日整理的 Top20，因为后者缺少 Query 维度；它复用相同的规范 URL 逻辑，从原始记录按 `client_id + query + source_platform` 重算。逐篇分析只输出文章—Query—平台证据和候选路线；随后按介绍型、对比型分别调用批次合并 LLM，决定创建路线、强化已有路线或丢弃重复证据。

**Tech Stack:** Flask、Python 标准库 JSON/随机数、现有 `fetch_article_text`、`ai_json`、行业写法库 JSON、原生前端 JavaScript。

## Global Constraints

- 一次任务只允许一个 Query 和一个 AI 平台，不支持多选平台。
- 候选数据必须按 `client_id + Query + source_platform` 从原始引用记录重新统计；规范 URL 和引用次数口径复用 `services.ref_articles.canonical_article_key`。
- 选文固定第 1 名，再从第 2～5 名按当前 AI 平台引用次数加权随机抽取 1 篇；保存候选快照、随机种子、权重和结果。
- 新增 LLM 调用 `max_tokens >= 4000`；逐篇分析与批次合并是独立调用。
- 写法库暂按行业 + 介绍型/对比型共享；来源证据必须保留 Query 和 AI 平台，为未来平台隔离留下数据但不改变当前读取行为。
- 客户级 API 继续使用 `require_client_access`，越权返回 404。
- 质量门禁只提醒，不参与本功能的路线准入判断。

---

### Task 1: Query × 平台候选统计与抽样

**Files:**
- Create: `services/query_platform_reference_intelligence.py`
- Test: `tests/test_query_platform_reference_intelligence.py`

**Interfaces:**
- Consumes: 原始记录列表，每条记录包含 `question`、`source_platform`、`refs`。
- Produces: `select_query_platform_articles(records, query, ai_platform, seed)`，返回规范 URL 候选排序、固定头部文章、加权随机文章和可复盘的抽样元数据。

- [ ] **Step 1: Write the failing test**

```python
def test_selects_anchor_and_weighted_article_from_exact_query_and_platform():
    result = select_query_platform_articles(records, "Q1", "doubao", seed=7)
    assert result["anchor"]["url"] == "https://example.com/a"
    assert result["selected"][0]["citation_count"] == 4
    assert {item["url"] for item in result["weighted_pool"]} == {
        "https://example.com/b", "https://example.com/c", "https://example.com/d", "https://example.com/e",
    }
    assert all(item["citation_count"] == item["weight"] for item in result["weighted_pool"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_query_platform_reference_intelligence`

Expected: FAIL because `services.query_platform_reference_intelligence` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def select_query_platform_articles(records, query, ai_platform, seed):
    grouped = _group_canonical_articles(records, query, ai_platform)
    ranked = sorted(grouped, key=lambda item: (-item["citation_count"], item["url"]))
    anchor, pool = ranked[:1], ranked[1:5]
    picked = random.Random(seed).choices(pool, weights=[item["citation_count"] for item in pool], k=1) if pool else []
    return {"seed": seed, "ranked": ranked, "anchor": anchor[0] if anchor else None, "weighted_pool": pool, "selected": anchor + picked}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_query_platform_reference_intelligence`

Expected: PASS.

### Task 2: 批次路线合并与来源上下文

**Files:**
- Create: `services/reference_route_batch_merge.py`
- Modify: `services/content_route_library.py`
- Test: `tests/test_reference_route_batch_merge.py`, `tests/test_content_route_library.py`

**Interfaces:**
- Consumes: 已完成逐篇分析、同一行业同一父类型的现有路线摘要。
- Produces: `merge_reference_route_batch(analyses, existing_routes, ai_json_fn)`，返回 `create`、`reinforce`、`discard` 操作；`ContentRouteLibrary.add_or_merge_source()` 保留同 URL 的多个 Query × 平台来源上下文。

- [ ] **Step 1: Write failing tests**

```python
def test_batch_merge_uses_a_separate_4000_token_llm_call():
    result = merge_reference_route_batch([analysis], [route], fake_ai_json)
    assert result["updates"][0]["action"] == "reinforce"
    assert captured_tokens == 4000

def test_same_source_url_merges_new_query_platform_context():
    route = library.create_route("装修", route_payload, source_a)
    updated = library.add_or_merge_source("装修", route["id"], source_a_for_other_query)
    assert len(updated["sources"]) == 1
    assert len(updated["sources"][0]["citation_contexts"]) == 2
```

- [ ] **Step 2: Run tests to verify failure**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_reference_route_batch_merge tests.test_content_route_library`

Expected: FAIL because batch merger and `add_or_merge_source` do not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def merge_reference_route_batch(analyses, existing_routes, ai_json_fn):
    raw = ai_json_fn(build_batch_merge_prompt(analyses, existing_routes), 4000)
    return normalize_batch_merge_result(raw, analyses, existing_routes)

def add_or_merge_source(self, industry, route_id, source):
    existing = _find_source_by_url(route["sources"], source["url"])
    if existing:
        _merge_source_context(existing, source)
    else:
        route["sources"].append(clean_source)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_reference_route_batch_merge tests.test_content_route_library`

Expected: PASS.

### Task 3: 一键任务 API、持久化与路线落库

**Files:**
- Modify: `app.py`
- Test: `tests/test_app_core.py`, `tests/test_formal_content_route_entry.py`

**Interfaces:**
- Endpoint: `POST /api/content-routes/analyze-query-platform` with JSON `{client_id, group_id, query, ai_platform}`.
- Response: `{task, analyses, merge_results, routes}`；任务记录保存到 `data/reference_intelligence_tasks/<client_id>.json`。

- [ ] **Step 1: Write failing API tests**

```python
def test_one_click_reference_analysis_recounts_exact_query_and_platform_then_merges():
    response = client.post("/api/content-routes/analyze-query-platform", json={
        "client_id": client_id, "group_id": group_id, "query": "Q1", "ai_platform": "doubao",
    })
    assert response.status_code == 200
    assert load_client_records.call_args.kwargs == {"question": "Q1", "platform": "doubao"}
    assert response.get_json()["task"]["selected"][0]["citation_count"] == 4

def test_one_click_reference_analysis_rejects_query_outside_group():
    response = client.post("/api/content-routes/analyze-query-platform", json={"client_id": client_id, "group_id": group_id, "query": "其他问题", "ai_platform": "doubao"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "query_not_in_group"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_app_core tests.test_formal_content_route_entry`

Expected: FAIL with a 404 for the new endpoint.

- [ ] **Step 3: Write minimal API flow**

```python
records = load_client_records(cid, question=query, platform=ai_platform)
selection = select_query_platform_articles(records, query, ai_platform, seed=secrets.randbits(32))
analyses = [_fetch_and_analyze(candidate, query, ai_platform) for candidate in selection["selected"]]
for parent_type, items in _group_eligible_by_parent_type(analyses).items():
    updates = merge_reference_route_batch(items, library.list_routes(industry), ai_json)
    _apply_route_updates(library, industry, updates, items)
```

Each source receives `citation_contexts: [{"query": query, "ai_platform": ai_platform, "citation_count": candidate["citation_count"]}]` before route storage. Fetch failures are recorded in the task but do not discard successfully analyzed sources.

- [ ] **Step 4: Run tests to verify pass**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_app_core tests.test_formal_content_route_entry`

Expected: PASS.

### Task 4: 引用情报页面改为单平台一键任务

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Test: `tests/test_content_generation_ui.py`

**Interfaces:**
- 页面字段：`routeAnalysisGroupSelect`、`routeAnalysisQuerySelect`、`routeAnalysisPlatformSelect`。
- 前端函数：`runQueryPlatformReferenceAnalysis()` 调用新 API；不再暴露 URL 输入框或旧的单篇分析按钮。

- [ ] **Step 1: Write failing UI test**

```python
def test_reference_analysis_uses_one_platform_and_no_manual_url_input(self):
    assert 'id="routeAnalysisPlatformSelect"' in template
    assert "runQueryPlatformReferenceAnalysis" in script
    assert "/api/content-routes/analyze-query-platform" in script
    assert 'id="routeAnalysisUrl"' not in template
```

- [ ] **Step 2: Run test to verify failure**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_content_generation_ui`

Expected: FAIL because the current page still exposes URL input.

- [ ] **Step 3: Write minimal UI implementation**

```javascript
async function runQueryPlatformReferenceAnalysis() {
  const result = await api('/api/content-routes/analyze-query-platform', 'POST', {
    client_id: currentClientId, group_id, query, ai_platform,
  });
  status.textContent = result.error || `已分析 ${result.analyses.length} 篇，路线更新 ${result.routes.length} 条`;
}
```

平台选择器仅渲染当前客户合同平台；每次只传一个平台值。

- [ ] **Step 4: Run UI tests and syntax validation**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_content_generation_ui; node --check static/js/app.js`

Expected: PASS.

### Task 5: 回归验证

**Files:**
- Modify: none
- Test: 全量 `tests/`

- [ ] **Step 1: Run focused tests**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_query_platform_reference_intelligence tests.test_reference_route_batch_merge tests.test_content_route_analysis tests.test_content_route_library tests.test_content_generation_ui`

Expected: PASS.

- [ ] **Step 2: Run full verification**

Run: `& .\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests; node --check static/js/app.js; git diff --check`

Expected: exit code 0.

## Self-Review

- Query 与单一 AI 平台过滤在 Task 1 和 Task 3 覆盖；当日整理统计未被改写。
- 固定头部 + 第 2～5 名加权随机、任务快照与种子在 Task 1 和 Task 3 覆盖。
- 单篇分析与批次合并独立 LLM 调用在 Task 2、Task 3 覆盖，均为 4000 tokens。
- 来源保留 Query/平台上下文、同 URL 不重复为多条来源在 Task 2 覆盖。
- 页面移除 URL 输入、限制单平台在 Task 4 覆盖。
