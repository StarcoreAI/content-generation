# GEO Agent

GEO Agent is a local Flask workspace for Generative Engine Optimization workflows. It monitors how brands appear in AI answers, stores crawler records, analyzes citation sources, and supports content generation.

## Quick Start

```powershell
.\启动.bat
```

Open:

```text
http://localhost:5000
```

## Common Commands

```powershell
.\run_tests.bat
.\health_check.bat
.\restart.bat
.\stop.bat
.\启动局域网.bat
.\full_regression.bat deepseek --timeout 600 --keep-data
```

## Documentation

- `使用说明.md`: product usage guide
- `工程化说明.md`: development, testing, and local operations
- `接手文档.md`: project understanding guide for handoff and onboarding

## Sensitive Local Data

Runtime data is stored under `data/`. Login state files such as `*_state.json` and `*_cookies.json` may contain active session data. Do not share or commit them.
