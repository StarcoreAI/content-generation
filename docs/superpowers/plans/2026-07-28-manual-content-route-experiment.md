# Manual Introduction Content Route Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only, manual-input introduction-content experiment that tests whether an explicitly selected route plus the full operator-maintained customer master can produce a Query-specific draft, without changing the current production generation pipeline.

**Architecture（已按实验修正）:** The experiment accepts a single article task, one manually selected `介绍型` route, and the full customer master explicitly attached by the operator. One writer LLM directly produces the draft from those inputs; it does not receive an LLM-generated brief. Citation articles and competitor knowledge are not inputs. The customer master remains external to the experiment: the runner reads only the explicit `--customer-master-file` path, never a storage path inferred from customer ID. Pattern-library persistence, SQLite, `app.run_content_generation(...)`, and the quality-gate workflow are all out of scope.

**Tech Stack:** Python standard library, existing `ai` callback convention, unittest.

## Global Constraints

- All user-facing copy is Simplified Chinese.
- This experiment handles `介绍型` only. Do not silently treat a comparison task as an introduction task.
- The full customer master enters only through the explicit runner argument `--customer-master-file`. Do not infer or read any customer or competitor storage path.
- The attached customer master is the operator-maintained source of truth: all of its content is usable by default. Operations correct, remove, or constrain information by directly editing that master before an experiment.
- The selected route is abstract writing guidance only. Its source article URL, excerpts, competitor names, doctor names, technical claims, metrics, and source evidence must never enter the writer prompt.
- 写作 LLM 仅可使用附带客户总资料和一次性任务中的中性决策引导；不得编造资料外的客户专属事实。
- “问题 → 机制 → 读者顾虑”是轻量写作考虑：客户资料本身清楚支持时可解释，不要求每篇都有，更不能虚构。
- Every new LLM call uses `max_tokens >= 4000`.
- The experiment writes only to the operator-provided output directory. No crawler, job, library, knowledge-base, record, publication, frontend, API, or database write is allowed.
- Do not commit in this round unless the user explicitly requests it.

## Manual Bundle Contract

```json
{
  "task": {
    "query": "本次唯一服务的 Query",
    "article_type": "介绍型",
    "decision_goal": "文章要帮助读者完成的判断",
    "must_address": ["本次必须回应的顾虑"],
    "title_entity_policy": "实体不入标题"
  },
  "client": {"name": "客户名称", "brand": "成文中使用的实体名"},
  "selected_route": {
    "name": "抽象路线名称",
    "parent_type": "介绍型",
    "reader_task": "抽象读者任务",
    "steps": [
      {"purpose": "本步目的", "evidence_role": "所需证据类型", "output_action": "写作动作"}
    ],
    "signature": "路线特征",
    "risk_notes": "风险或空字符串"
  }
}
```

运行器以 `--customer-master-file` 显式附加整份客户总资料。`title_entity_policy` 只允许 `实体不入标题` 或 `实体可入标题`，作为一次实验变量，不沉淀为全局规则。客户总资料默认可用；它不接受竞品资料、外部引用文章正文或未筛选素材混入。

---

### Task 1: 单阶段介绍型内容实验契约

**Files:**
- Create: `services/content_route_experiment.py`
- Test: `tests/test_content_route_experiment.py`

**Interfaces:**
- `validate_content_route_bundle(bundle) -> dict`
- `build_content_route_writer_prompt(bundle) -> str`
- `run_content_route_experiment(bundle, writer_ai_fn) -> dict`

写作 prompt 直接接收一次性任务、抽象路线和客户总资料。路线只给出组织关系，不生成中间事实简报；客户事实是正文主体，Query 限定重点，路线提供第三优先级的叙述约束。

- [x] 先为单阶段 prompt 与单次 LLM 调用写失败测试；测试断言 Query、路线、完整客户资料和标题策略都进入 prompt，且不包含竞品或引用文章内容。

测试还断言单次调用的 `max_tokens >= 4000`，并确认写作 prompt 不含引用文章 URL 或 `source_evidence`。

- [x] 实现最小服务。校验拒绝非 `介绍型` 任务或路线、缺少 Query/决策目标/客户品牌/路线步骤/客户资料、不支持的标题策略和空白成稿。写作 prompt 说明路线只负责结构、客户资料默认可用、客户特有优势必须构成正文主干；禁止竞品事实、外部来源事实、无资料支撑的客户专属事实及内部流程话语。

- [x] Run `python -X utf8 -m unittest tests.test_content_route_experiment -v`; it passes.
- [x] Run `python -X utf8 -m py_compile services/content_route_experiment.py`; it passes.

### Task 2: Manual runner and output boundary

**Files:**
- Create: `scripts/dev_content_route_experiment.py`
- Modify: `tests/test_content_route_experiment.py`

**Interfaces:**
- `run_manual_content_route_experiment(bundle, customer_master_text, output_dir, writer_ai_fn) -> dict`
- CLI: `--input`, `--customer-master-file`, and `--output-dir`

运行器只写入以下文件：

```text
draft.md
experiment_trace.json
```

`draft.md` 只含成稿。`experiment_trace.json` 包含 `schema_version`、Query、路线名、客户资料字符数、标题策略和输出路径；不得复制客户资料内容、引用文章内容、知识库路径或来源摘录。

- [x] 为运行器写失败测试：一个有效 bundle 写入 `TemporaryDirectory()` 后，目录只含 `draft.md` 与 `experiment_trace.json`；trace 只记录客户资料字符数，不记录资料文本。

- [x] 初始测试在运行器尚不存在时失败；实现后再运行同一测试通过。

- [x] 用 JSON 和显式客户资料文件实现运行器。CLI 仅在真实调用时懒加载 `app`，并只使用 `app.ai` 写作；不抓取 URL，也不推断或访问 `data/`。

- [x] 运行 `python -X utf8 -m unittest tests.test_content_route_experiment -v; python -X utf8 -m py_compile services/content_route_experiment.py scripts/dev_content_route_experiment.py`，均通过。

### Task 3: First Cui Honglei manual experiment package

**Files:**
- Create only under an operator-provided temporary directory, for example `C:\tmp\cui-content-route-experiment-input\`.
- No repository data file, knowledge-base file, or production record may be created or changed.

- [x] Use Cui Honglei’s complete, current operator-maintained `customer_master.md` as `--customer-master-file`. It was not extracted, filtered, or downgraded for this experiment; operations edit that master if they want to correct or constrain future use.
- [x] Choose one verified Query-1 introduction route from `C:\tmp\cui-route-experiment-output-mechanism-reminder\query_1\route_analysis.json`; copy only its abstract `route`, never its `source_evidence` or article URL.
- [x] Create one `介绍型` bundle with the original Query, an explicit decision goal, its stated concerns, and one title-entity policy. This is a one-off task input, not a question asset.
- [x] 以多个 Query 运行单阶段实验，输出目录均单独保留，避免覆盖。先用完整客户资料测试，发现其中的策划、审计和场景示例会分散正文重点；再用纯事实诊断副本验证，客户特有能力展开明显增强。该副本只用于诊断，未写回或替换原始资料。
- [x] 给写作 prompt 增加轻量要求：客户特有优势须成为正文主干，分别说明做法、与读者困扰的连接及共同形成的特点；不得用无证据的比较词替代介绍。
- [x] Preserve the temporary input and outputs for the review; no result was promoted to the pattern library, no production prompt was changed, and no commit was made.

## Verification

- [x] `python -X utf8 -m unittest tests.test_content_route_experiment -v`
- [x] `python -X utf8 -m py_compile services/content_route_experiment.py scripts/dev_content_route_experiment.py`
- [x] `git diff --check`
- [x] Read the runner source and confirm it has no `data/`, knowledge-base, competitor, crawler, publication, database, or `run_content_generation` reference.
- [x] 人工比对最新崔红蕾实验稿与运营稿：客户事实的展开度与整体连贯性已接近运营稿；仍需在后续实验中解决弱相关资料被一并写入的问题。

## Explicitly Deferred

- Replacing `app.run_content_generation(...)` or deleting current audience-angle / FAQ behavior from production.
- Pattern-library persistence, candidate promotion, route deduplication, or route selection automation.
- Any automatic customer/competitor knowledge-base injection, competitor comparison article, article fetching, crawling, or source acquisition.
- Any change to quality-gate behavior, article records, batch jobs, frontend/API, crawler, knowledge base, record library, or publication flow.
- 将“纯事实诊断副本”自动化为资料过滤、或静默替换运营客户总资料。资料的正式结构和可写范围需另行确认。
