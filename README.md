# GEO Agent

GEO Agent 是内部 GEO 运营工作台：运营人员按客户的问题组，在已签约 AI 平台抓取回答和实际引用来源；系统提供记录复盘、引用情报、知识库维护与内容生产。

项目当前运行在云端 Flask/Gunicorn 服务与运营电脑本地爬虫 worker 的组合中。爬虫结果受各平台登录状态和风控影响，不承诺无人值守的稳定抓取。

## 本地启动

首次安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

日常开发启动：

```powershell
.\run_dev.bat
```

访问 `http://localhost:5000`。常用检查命令：

```powershell
.\run_tests.bat
.\health_check.bat
```

## 当前能力（2026-08-04）

- 记录库按指定客户和 AI 平台展示爬取结果、趋势与逐题矩阵；当日数据整理可选择实际爬取日期。
- 引用情报默认分析整个问题组，也可选单题；引用情报与竞品资料补充都以后台任务运行，并缓存文章抓取与分析结果。
- 客户资料、竞品资料、Query 场景词、行业写法库和质量门禁均自动保存；客户、竞品、场景词和写法库可导出 DOCX。
- 内容生产提供介绍型、对比型和 1/2/3 篇批量生成。两类文章开头均不少于 600 个汉字、没有上限，并在事实边界内围绕 Query 自然展开。
- 系统提示词只读展示，可选中文本复制，不可编辑或下载。

不安排平台偏好矩阵、经验库、自进化、自动权重优化、RAG 升级或多轮人工审核。

## 文档

按以下顺序阅读即可：

1. `运营使用说明.md`：运营电脑安装、本地 worker、取消/补爬和诊断日志。
2. `deploy/README.md`：云端 SSH、Git 部署、服务日志、备份和数据补录。
3. `工程化说明.md` 与 `docs/engineering-rules.md`：本地环境、测试和工程约束。
4. `docs/content-plan.md` 与 `docs/knowledge-base-direction.md`：内容生产、引用情报和知识库的正式边界。

`docs/citation-selection-findings.md` 和 `docs/citation-selection-evidence-walkthrough.md` 是旧样本的研究记录，仅可作为后续高低频引用研究的参考，不能当作产品规则或结论。

## 代码结构

- `app.py`：Flask 路由与服务装配。
- `services/`：爬取任务、记录、引用情报、知识库、内容生产等业务模块。
- `templates/index.html`、`static/js/app.js`、`static/css/app.css`：前端页面。
- `scripts/`：运维、导入和研究数据导出工具。

## 数据安全

运行数据位于 `data/`。`.env`、`settings.json`、`*_state.json`、`*_cookies.json` 可能含 API Key 或平台登录态，禁止外传或提交到仓库。
