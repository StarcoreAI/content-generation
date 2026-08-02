# 选择层证据展示 + 覆盖矩阵 · 施工任务块

> **状态：已废弃，禁止执行。** 本文保留讨论历史，但其中“只用引用标题”“我方在场/状态/缺口”“报告由云端预置”等口径均已被用户否决。请改按 `docs/superpowers/plans/2026-07-26-knowledge-hub-and-selection-evidence.md`：报告由运营临时上传；场景词由 Query 与高引用文章的标题、Meta、首段共同提取；页面只显示问题组、Query、场景词。

下发时间：2026-07-26
下发人：方案讨论 agent（用户已拍板）
执行顺序：**任务块一先做、验收通过后再做任务块二**，两块独立提交。

## 共同背景（为什么做）

2026-07-26 的引用选择规律分析（`docs/citation-selection-findings.md`）得出三层模型：入池（站点+标题主词）→ 问题分配（症状/场景词逐字匹配）→ 实体冗余（同名多篇跨站决定稳定性）。两个直接可产品化的结论：

1. **症状词覆盖矩阵**：问题里的场景/症状词能否在被引文章标题里逐字找到，决定该问题下有没有我方位置；缺口即选题（findings 第四节第 1 条）。
2. **实体厚度**：孤篇站不稳，同名多篇跨站才稳（实体冗余层）。

本次给爬取记录库页（`#page-records`）加两个分区：

- **选择层分析报告展示**（任务块一）：把已生成的表面报告（崔红蕾、扬州苏韵等，云端 `data/selection_surface_reports/<client_id>/` 下的 Markdown）在前端展示给运营看——这是让运营相信这套规律的证据。
- **覆盖矩阵**（任务块二）：按问题自动计算场景词覆盖与我方实体厚度，缺口一眼可见。

设计原则（用户拍板，不要偏离）：**全部是派生视图**——从已有数据现场算，不建需要人维护的库。唯一的落盘是场景词提取缓存（增量、可随时重建）。

用户已拍板的设计决策（不要重新讨论）：

- 只用 `refs[].title` 判覆盖，**不抓取文章 meta/正文**（"品牌在正文"检测是后续独立项，本次不做，不要顺手加抓取）。
- 场景词提取由运营按钮触发 LLM，一次批量处理、增量缓存；不做自动定时任务。
- 不做"消失预警"、不做发布归因、不做自动选题建议；矩阵只标缺口，判断留给运营。

硬约束提醒：不碰爬虫链路和本地 worker；单 gunicorn worker + 多线程；多租户越权统一 404；不引入前端图表库（表格/CSS 即可）；新 LLM 调用 `max_tokens ≥ 4000`；开发只跑 mock 单测，**不得自行调用真实 LLM**；PowerShell 用 `;` 不用 `&&`；顶层脚本编码规则见 `docs/engineering-rules.md`。

数据基础（已探索确认，直接用）：

- 表面报告：`scripts/run_selection_surface_report.py` 输出到 `data/selection_surface_reports/<client_id>/<run_date>_<客户名>[_low_frequency_random]_selection_surface.md`。本地开发环境该目录可能不存在（报告在云端生成），测试用 fixture。
- 爬取记录：`data/raw_records.json` 经 `load_client_records`（`services/records.py`）过滤；单条含 `question`、`refs[]`（`{position,title,url,platform}`）、`brand_mentioned`、`today`、`client_id`。
- 客户名/品牌：`data/clients.json`，取法参考 `scripts/run_selection_surface_report.py` 的 `_client_info`。
- 问题列表：记录库页前端已有按客户的问题下拉，复用其数据来源。
- 文章归一化键：复用 `canonical_article_key(title, url)`（`services/record_insights.py` 有现成用法）。

---

## 任务块一：选择层分析报告展示

### 改动点

#### 1. 后端路由（`app.py`）

- `GET /api/records/selection_reports?client_id=<cid>`：列出 `data/selection_surface_reports/<cid>/` 下全部 `.md` 文件，返回 `[{filename, run_date, mode, size}]`。`mode` 从文件名解析：含 `_low_frequency_random_` 为"低频随机档"，否则"高频 Top"。目录不存在返回空列表，不报错。
- `GET /api/records/selection_reports/<filename>?client_id=<cid>`：返回该文件的原文内容（JSON 里带 `content` 字段）。**安全要求**：filename 必须经过白名单校验（仅允许该客户目录下实际存在的文件名，拒绝任何含路径分隔符、`..` 的输入），防路径穿越。
- 两个路由都走 `require_client_access`（或现有同等校验），越权 404。

#### 2. 前端（`templates/index.html`、`static/js/app.js`）

- 记录库页新增"选择层分析报告"分区：报告文件列表（运行日期 + 档位 + 文件名），点击展开查看内容。
- 内容展示从简：按 Markdown 原文以预格式化文本或最小转换展示（标题行加粗即可），**不引入 Markdown 渲染库**。
- 无报告时显示空态文案（如"暂无选择层分析报告，报告由管理员在云端生成"）。

### 验收标准

- 单测全绿。
- 真实验收由用户在云端执行：
  1. 切到崔红蕾，能看到 07-25/07-26 的高频与低频档报告并可展开阅读；切到扬州苏韵同理。
  2. 无报告的客户显示空态。
  3. 用另一运营账号访问非本人客户的报告接口，返回 404。

### 测试要求

- fixture：临时 data 目录下给两个客户各放一个报告 md 文件，断言列表只返回本客户文件、内容读取正确、mode 解析正确。
- 路径穿越用例：filename 传 `../<另一客户>/xxx.md`、`..\..\x.md`、绝对路径，一律 404。
- 越权 404 用例对齐现有隔离测试写法；前端 wiring 静态断言对齐 `tests/test_content_generation_ui.py` 现有模式。
- 跑相关模块后跑 `.\run_tests.bat` 全量；独立提交，更新 `接手文档.md` 记录库能力描述。

---

## 任务块二：覆盖矩阵（场景词覆盖 × 实体厚度）

> 依赖任务块一验收通过后开工。

### 改动点

新建 `services/record_coverage.py` 放纯函数；`app.py` 加路由；前端在记录库页加一个分区。

#### 1. 场景词提取（运营按钮触发，增量缓存）

- 输入：该客户爬取记录中出现过的全部问题文本（去重）。
- 一次 LLM 调用批量处理（问题数量级为几十，单次调用足够；`max_tokens ≥ 4000`），要求输出 JSON：每个问题 `{"question": "...", "main_terms": ["城市", "项目/品类"], "scene_terms": ["症状/场景/人群词", ...]}`。prompt 要点：`main_terms` 是城市/项目/品类等主意图词；`scene_terms` 是具体的症状、场景、人群、决策细节词（如"法令纹""不对称""评职称""新能源"），**排除泛化词**（"靠谱""专业""审美在线"这类不进 scene_terms）——这是 findings 的直接结论（泛化词在问题分配层无效）。
- 缓存写入 `data/selection_coverage/<cid>/question_terms.json`，按问题文本为键。重复点击只处理缓存中没有的新问题；LLM 失败或返回无效 JSON 时不写缓存、返回错误信息，禁止盲写。
- 路由：`POST /api/records/coverage/terms`（触发生成，返回处理数/跳过数）；生成为同步调用即可（一次 LLM，秒级），不需要 job 机制。

#### 2. 矩阵计算（纯派生，请求时现算）

- 聚合函数输入：客户记录、日期范围（默认最近 30 天，可传起止日期）、场景词缓存、客户品牌名与客户名。
- 每个问题输出：
  - `scene_coverage`：每个 scene_term 的覆盖状态——该问题日期范围内引用池（`refs[]` 去重后的文章）中，是否存在**标题逐字包含该词**的文章；附命中文章的 title/url。
  - `entity_presence`：引用池中标题包含品牌名或客户名的文章数、去重域名数（域名提取可复用记录库来源站视图的现有归一化函数）。
  - `flags`：`zero_coverage`（所有 scene_terms 均未覆盖）、`thin_presence`（在场文章数 ≤1，孤篇预警）。
- 无场景词缓存的问题照常返回，`scene_coverage` 为空并带"未提取场景词"标记。
- 路由：`GET /api/records/coverage?client_id=<cid>&date_from=&date_to=`，走客户访问校验。

#### 3. 前端分区"覆盖矩阵"

- 表格：行 = 问题；列 = 场景词覆盖（每词一个标签，未覆盖标红）、我方在场（N 篇 × M 站）、预警（零覆盖 / 孤篇）。
- 顶部：日期范围选择、"提取场景词"按钮（显示上次提取覆盖了多少问题）。
- 每行提供"复制缺口"按钮：把该问题、未覆盖场景词、我方在场情况拼成一段纯文本复制到剪贴板（供运营粘贴到别处使用），实现从简。
- 不引入图表库。

### 验收标准

- 单测全绿。
- 真实验收由用户执行，**以 findings 已知结论为基准**：
  1. 崔红蕾提取场景词后，矩阵中"线雕换方案""面部不对称""疲惫感/换脸"类问题应显示零覆盖或接近零覆盖；"法令纹/下颌线"类问题应显示已覆盖——与 `docs/citation-selection-findings.md` 的人工分析一致。若不一致，先查口径再查代码。
  2. 崔红蕾的实体在场应显示为薄（1-2 篇），与 findings"1 强 1 弱"吻合。
  3. 重复点击"提取场景词"不重复调用已缓存问题；越权 404。

### 测试要求

- mock LLM：断言批量 prompt 含全部未缓存问题、排除泛化词的指令存在；无效 JSON 不落盘。
- 矩阵 fixture：构造已知覆盖/未覆盖的记录（标题含词/不含词）、品牌孤篇与多篇多站两种形态、日期范围过滤、无缓存问题的降级输出、空数据不报错。
- 缓存增量：两次调用第二次跳过已有问题。
- 越权 404、前端 wiring 断言、`.\run_tests.bat` 全量；独立提交，更新 `接手文档.md`。
