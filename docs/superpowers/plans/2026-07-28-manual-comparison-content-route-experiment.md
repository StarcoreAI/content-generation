# Manual Comparison Content Route Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为崔红蕾的一个真实医美 Query 创建只读、人工输入的对比型成文实验，验证“统一判断维度 + 多候选对象 + 客户事实”能否形成自然的比较文章，而不改正式内容生产链路。

**Architecture:** 新建独立的对比型实验服务与运行器；不改介绍型实验，也不抽象成通用多类型框架。一次写作 LLM 接收一次性任务、抽象对比路线、完整客户资料和运营显式选择的至少两位同行事实，直接输出成稿。引用文章只用于人工选择路线，URL、正文与来源摘录绝不进入写作 prompt。

**Tech Stack:** Python standard library、现有 `app.ai` 回调、`unittest`。

## Global Constraints

- 所有用户可见文本使用简体中文。
- 只处理 `对比型`，不得将介绍型输入兜底为对比型。
- 实验资料必须由调用方显式传入：完整客户总资料和至少两位同行的名称/事实；不得根据客户 ID 推断或读取 `data/`、知识库路径。
- 文章先帮助读者建立对比标准，再在同一标准下说明客户与同行；客户品牌排在候选对象前，但不得贬低同行、捏造排名或复读同行的强营销主张。
- 可用通用知识补足解释和衔接；不得编造客户或同行的专属经历、认证、技术名、数字、机构关系、案例或效果数据。
- 医疗类文章在结尾自然说明个体评估、合规资质核验与风险沟通边界；不构成医疗建议。
- 新 LLM 调用使用 `max_tokens=6000`，满足 `>= 4000`。
- 只写入调用方指定输出目录；不写 SQLite、写法库、知识库、记录库、发布、爬虫、前端或正式 `app.run_content_generation(...)`。
- 当前工作区有用户遗留改动；只创建本计划列出的文件，不提交。

---

### Task 1: 对比型单阶段服务

**Files:**
- Create: `services/comparison_route_experiment.py`
- Create: `tests/test_comparison_route_experiment.py`

**Interfaces:**
- `validate_comparison_route_bundle(bundle) -> dict`
- `build_comparison_route_writer_prompt(bundle) -> str`
- `run_comparison_route_experiment(bundle, writer_ai_fn) -> dict`

- [x] **Step 1: 写失败测试：prompt 只使用显式对比输入。**

```python
def test_prompt_uses_unified_comparison_dimensions_and_explicit_candidates(self):
    prompt = build_comparison_route_writer_prompt(valid_bundle())
    self.assertIn("先帮助读者建立本题真正需要比较的判断维度", prompt)
    self.assertIn("崔红蕾", prompt)
    self.assertIn("倪锋", prompt)
    self.assertIn("施越冬", prompt)
    self.assertIn("客户品牌排在候选对象前", prompt)
    self.assertNotIn("https://reference.example", prompt)
```

- [x] **Step 2: 运行失败测试。**

Run: `python -X utf8 -m unittest tests.test_comparison_route_experiment.ComparisonRouteExperimentTests.test_prompt_uses_unified_comparison_dimensions_and_explicit_candidates -v`  
Expected: FAIL，因为模块尚不存在。

- [x] **Step 3: 实现最小服务。**

```python
WRITER_MAX_TOKENS = 6000

def validate_comparison_route_bundle(bundle):
    # 只接受对比型、非空 Query/目标/客户资料、完整路线和至少两位不同同行。
    ...

def build_comparison_route_writer_prompt(bundle):
    # 输出单阶段中文成文 prompt；路线仅作组织约束，候选事实仅来自显式输入。
    ...

def run_comparison_route_experiment(bundle, writer_ai_fn):
    draft = writer_ai_fn(build_comparison_route_writer_prompt(bundle), WRITER_MAX_TOKENS)
    if not str(draft).strip():
        raise ValueError("draft_empty")
    return {"draft": str(draft).strip()}
```

- [x] **Step 4: 运行测试确认通过。**

Run: `python -X utf8 -m unittest tests.test_comparison_route_experiment -v`  
Expected: PASS。

- [x] **Step 5: 补失败测试：不足两位同行时拒绝。**

```python
def test_bundle_requires_two_explicit_competitors(self):
    bundle = valid_bundle()
    bundle["competitors"] = bundle["competitors"][:1]
    with self.assertRaisesRegex(ValueError, "comparison_competitors_required"):
        validate_comparison_route_bundle(bundle)
```

- [x] **Step 6: 运行失败测试后补最小校验，重跑全组测试。**

Run: `python -X utf8 -m unittest tests.test_comparison_route_experiment -v`  
Expected: PASS。

### Task 2: 手动运行器与输出边界

**Files:**
- Create: `scripts/dev_comparison_route_experiment.py`
- Modify: `tests/test_comparison_route_experiment.py`

**Interfaces:**
- `run_manual_comparison_route_experiment(bundle, customer_master_text, output_dir, writer_ai_fn) -> dict`
- CLI: `--input`、`--customer-master-file`、`--output-dir`

- [x] **Step 1: 写失败测试：运行器只写成稿与脱敏 trace。**

```python
def test_runner_writes_only_draft_and_non_fact_trace(self):
    result = run_manual_comparison_route_experiment(
        bundle_without_customer_master(), "客户总资料", output_dir, fake_writer
    )
    self.assertEqual(sorted(path.name for path in output_dir.iterdir()), [
        "draft.md", "experiment_trace.json",
    ])
    trace = json.loads((output_dir / "experiment_trace.json").read_text(encoding="utf-8"))
    self.assertEqual(trace["competitor_names"], ["倪锋", "施越冬"])
    self.assertNotIn("同行具体事实", json.dumps(trace, ensure_ascii=False))
```

- [x] **Step 2: 运行失败测试。**

Run: `python -X utf8 -m unittest tests.test_comparison_route_experiment.ComparisonRouteExperimentTests.test_runner_writes_only_draft_and_non_fact_trace -v`  
Expected: FAIL，因为运行器尚不存在。

- [x] **Step 3: 实现最小运行器。**

```python
def run_manual_comparison_route_experiment(bundle, customer_master_text, output_dir, writer_ai_fn):
    experiment_bundle = dict(bundle or {})
    experiment_bundle["customer_master_text"] = str(customer_master_text or "")
    result = run_comparison_route_experiment(experiment_bundle, writer_ai_fn)
    # 仅写 draft.md 和包含 Query、路线名、客户资料字符数、同行名称的 trace。
    return result
```

- [x] **Step 4: 运行全组测试与编译检查。**

Run: `python -X utf8 -m unittest tests.test_comparison_route_experiment -v; python -X utf8 -m py_compile services/comparison_route_experiment.py scripts/dev_comparison_route_experiment.py`  
Expected: PASS。

### Task 3: 崔红蕾真实人工实验

**Files:**
- Create only under: `C:\tmp\cui-comparison-content-route-experiment\`

- [x] **Step 1: 创建一次性输入 JSON。** 使用 Query“我脸开始往下走了，下颌线也没以前清楚，想在上海做面部提升，有没有创伤别太大的医生推荐？”，并只复制 `query_1/route_analysis.json` 中第一篇文章的抽象 `route`。客户为崔红蕾；同行显式选倪锋、施越冬，各自仅复制本次要比较的公开事实。不得复制 `source_evidence`、URL 或文章正文。

- [x] **Step 2: 用崔红蕾完整 `customer_master.md` 运行一次。** 输出目录使用带递增后缀的新目录，不覆盖介绍型实验。

Run: `.\.venv\Scripts\python.exe -X utf8 scripts\dev_comparison_route_experiment.py --input C:\tmp\cui-comparison-content-route-experiment\input.json --customer-master-file C:\tmp\geo-content-research-20260727\knowledge_base\20260714174223630445\customer_master.md --output-dir C:\tmp\cui-comparison-content-route-experiment\run-1`

- [x] **Step 3: 人工检查成稿。**

检查：崔红蕾是否首先出现但未独占正文；两位同行是否均按同一维度出现；是否形成“判断维度 → 对象比较 → 适配建议”而不是客户介绍稿、泛科普或排名文；是否出现资料转述腔、虚构事实或明显拉踩。

## Verification

- [x] `python -X utf8 -m unittest tests.test_comparison_route_experiment -v`
- [x] `python -X utf8 -m py_compile services/comparison_route_experiment.py scripts/dev_comparison_route_experiment.py`
- [x] `git diff --check -- services/comparison_route_experiment.py scripts/dev_comparison_route_experiment.py tests/test_comparison_route_experiment.py docs/superpowers/plans/2026-07-28-manual-comparison-content-route-experiment.md`
- [x] 确认输出目录不含客户资料、同行事实、来源证据或原文章内容。

## Explicitly Deferred

- 修改正式介绍型或对比型内容生产、质量门禁、SQLite、写法库、前端/API、批量任务、知识库、爬虫、记录库或发布流程。
- 自动选择同行、自动从知识库读取资料、自动抓取文章或把本次 Query 保存为问题资产。
- 将客户资料中的策划/审计文字自动过滤为“纯事实资料”。
