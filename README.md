# GEO Agent

GEO Agent 是一个本地运行的 Flask 工作台，用于围绕客户、品牌和固定问题组监测 AI 平台回答中的品牌提及、引用来源和长期变化，并辅助运营基于客户资料和高频引用文章生成内容。

当前已经进入公司内部云端试用和维护阶段：登录访问、客户资料解析、竞品资料解析、内容生产独立资料上传、样例文章参考、多轮改稿、生成历史、引用情报分析和基础备份都已接入主流程。爬虫链路采用“云端任务中心 + 运营电脑本地 worker”试用方案，仍受本机登录态和平台风控影响，不承诺大规模无人值守稳定爬虫。

已接入或规划中的 AI 平台包括：

- DeepSeek
- 豆包
- 元宝
- 千问 / Qwen
- Kimi

## 快速开始

首次安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

日常本机启动：

```powershell
.\run_dev.bat
```

访问：

```text
http://localhost:5000
```

如果当前服务已经在给运营同学使用，修改代码或文档时不要随意执行 `restart.bat`、`stop.bat` 或关闭浏览器登录窗口。需要重启前先确认。

## 常用命令

```powershell
.\run_dev.bat
.\启动局域网.bat
.\run_tests.bat
.\health_check.bat
```

## 代码结构

- `app.py`：Flask 路由和服务模块装配层。
- `services/`：引用情报、crawl jobs、记录统计、客户资料解析、竞品资料解析和内容提示词等后端业务模块。
- `templates/index.html`：页面结构。
- `static/css/app.css`、`static/js/app.js`：前端样式和主体逻辑。

首次启用登录前，后台创建管理员账号：

```powershell
.\.venv\Scripts\python.exe scripts\create_user.py --username admin --role admin
```

命令会提示输入密码，并把哈希后的用户记录写入 `data/users.json`。

会影响当前服务的命令：

```powershell
.\restart.bat
.\stop.bat
```

## 关键文档

- `接手文档.md`：唯一交接入口，说明项目背景、当前状态、下一步优先级和风险边界。
- `运营使用说明.md`：Windows 运营包 setup、启动本地 worker、停止爬虫和导出诊断日志的操作说明。
- `工程化说明.md`：本地环境、启动方式、测试、Node 爬虫桥接和运行注意事项。
- `docs/engineering-rules.md`：入口脚本、运营 worker、云端部署和数据补录的工程约束。
- `docs/content-plan.md`：内容生成规则、资料来源边界、文章类型和中长期内容闭环计划。
- `docs/superpowers/plans/2026-07-06-content-generation-cloud-rollout.md`：内容生成云端试用上线准备计划。

## 敏感数据

运行数据存放在 `data/` 下。`*_state.json`、`*_cookies.json`、`settings.json` 等文件可能包含登录态或 API Key，不要外传或提交到公开仓库。
