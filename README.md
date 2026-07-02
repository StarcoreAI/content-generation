# GEO Agent

GEO Agent 是一个本地运行的 Flask 工作台，用于围绕客户、品牌和固定问题组监测 AI 平台回答中的品牌提及、引用来源和长期变化。

当前项目重点是接入并稳定运行四个平台的真实爬取链路：

- DeepSeek
- 豆包
- 元宝
- 千问 / Qwen

## 快速开始

```powershell
.\启动.bat
```

访问：

```text
http://localhost:5000
```

如果当前服务已经在给运营同学使用，修改代码或文档时不要随意执行 `restart.bat`、`stop.bat` 或关闭浏览器登录窗口。需要重启前先确认。

## 常用命令

```powershell
.\run_tests.bat
.\health_check.bat
.\启动局域网.bat
```

会影响当前服务的命令：

```powershell
.\restart.bat
.\stop.bat
```

## 关键文档

- `接手文档.md`：唯一交接入口，说明项目背景、当前进度、下一步计划和风险边界。
- `工程化说明.md`：本地环境、启动方式、测试、Node 爬虫桥接和运行注意事项。

## 敏感数据

运行数据存放在 `data/` 下。`*_state.json`、`*_cookies.json`、`settings.json` 等文件可能包含登录态或 API Key，不要外传或提交到公开仓库。
