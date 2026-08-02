# 质量门禁可编辑规则 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement task-by-task. Steps use checkbox syntax.

**Goal:** 将质量门禁改为只提示，并让运营维护通用与行业两层的违禁词、必须做、不能做和审核要求。

**Architecture:** 规则保存在 `data/quality_gate/policy.json`，运行时按通用层与客户行业层合并。门禁继续使用固定 JSON 输入/输出外壳，但把业务审核要求从代码提示词移到规则数据；所有检查结果均为 `warn`，不再跳过 LLM 审核或阻断文章。

**Tech Stack:** Flask、Python 标准库 JSON、vanilla JavaScript、unittest。

## Global Constraints

- 违禁词和审核要求只分通用、行业两层；不存客户专属规则。
- 编辑通用规则必须在 UI 二次确认，并由 API 要求 `confirmed_global=true`。
- 新旧门禁结果都在前端显示为提示，不阻断文章保存、编辑或发布。
- 固定保留 JSON schema、文章/资料输入拼装；运营只编辑业务审核要求。
- 新 LLM 调用沿用现有 4000 tokens 调用，不新增调用次数。

### Task 1: 规则存储与全 warn 门禁

**Files:**
- Modify: `services/quality_gate.py`
- Modify: `tests/test_quality_gate.py`

- [ ] 写失败测试：通用与行业规则合并；违禁词命中为 `warn`；原代码层命中仍调用 LLM，最终只返回 `pass` 或 `warn`。
- [ ] 运行 `python -X utf8 -m unittest tests.test_quality_gate -v`，确认当前 `blocked` 行为失败。
- [ ] 实现 `load_quality_policy(path)`、`save_quality_policy(path, policy)`、`effective_quality_policy(policy, industry)`；规则字段固定为 `banned_words`、`must_do`、`must_not_do`、`review_requirements`。
- [ ] 将可编辑审核要求注入 `_quality_gate_prompt`，但保留 JSON schema 与资料输入；`run_quality_gate` 无条件执行 LLM 层，所有失败 severity 为 `warn`。
- [ ] 重跑质量门禁测试。

### Task 2: 通用/行业规则 API

**Files:**
- Modify: `app.py`
- Modify: `tests/test_quality_policy_api.py`

- [ ] 写失败测试：读取通用层与客户行业层；通用保存缺少确认返回 400；保存行业规则需通过该客户的访问校验。
- [ ] 运行 `python -X utf8 -m unittest tests.test_quality_policy_api -v`，确认路由缺失。
- [ ] 新增 `GET /api/quality-policy?client_id=<cid>`、`PUT /api/quality-policy/common`、`PUT /api/quality-policy/industry/<cid>`；行业名从客户 `industry` 字段读取。
- [ ] 内容生成和人工复核调用 `run_quality_gate` 时传入当前有效规则。
- [ ] 重跑 API 与质量门禁测试。

### Task 3: 质量门禁编辑页

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `tests/test_quality_policy_ui.py`

- [ ] 写失败静态 UI 测试：质量页含通用、行业规则编辑区和保存函数。
- [ ] 运行 `python -X utf8 -m unittest tests.test_quality_policy_ui -v`，确认缺少编辑区。
- [ ] 在质量页增加通用规则卡、当前行业规则卡；每卡编辑违禁词、必须做、不能做、审核要求。保存通用规则前 `confirm` 明确说明“影响全部客户”。
- [ ] 前端将历史 `blocked` 与新 `warn` 都渲染为“审核提示”。
- [ ] 运行 UI 测试、`node --check static/js/app.js`、全量相关单测和 `git diff --check`。
