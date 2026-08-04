# StarTrace 聊天分析器

StarTrace 是一个 Windows 桌面应用，用于读取本地聊天记录、筛选群组和用户、分析下注消息，并提供站点开奖信息、历史记录、自动下注与运行统计功能。

## 项目目标

- 从本地消息数据库读取并分析群组聊天记录。
- 按站点、期号、群组、用户和玩法汇总下注数据。
- 获取当前/下一期开奖信息及历史开奖结果。
- 在用户配置后提供自动下注、AI 建议、策略运行统计和结算记录。
- 自动下注面板按当前站点的历史期数显示 13/14 与八种玩法的频率概率；压三门会排除最低频率的复合玩法，并在任一保留玩法达到最低置信度时同时下注其余三门。
- 提供普通用户版与管理员版 Windows 可执行文件。

## 运行环境

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11 |
| Python | 3.11 或兼容版本 |
| 图形界面 | PySide6 |
| 打包工具 | PyInstaller |

依赖清单见 `requirements.txt`。

## 安装

在 PowerShell 7 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 运行

普通用户模式：

```powershell
.\.venv\Scripts\python.exe app\main.py
```

管理员模式并输出调试日志：

```powershell
.\.venv\Scripts\python.exe app\main.py --debug
```

## 测试

执行完整自动化测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

编译检查：

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tools
```

## 集中服务端模式

`backend/` 提供 FastAPI、PostgreSQL、Redis 和 worker。它统一执行站点开奖/历史抓取、频率分析、在线授权、WSS 凭据加密与服务端发送；客户端通过“帮助 -> 服务器模式”使用机器码和服务端激活码登录，JWT 仅保留在内存。

### 本地开发重启 FastAPI

修改 FastAPI 代码后，在项目根目录使用以下 PowerShell 7 命令重建镜像并只重启 `api` 服务：

```powershell
Set-Location backend
docker compose up --build --force-recreate -d --wait api
Invoke-WebRequest http://127.0.0.1:8080/health/ready
```

如果只需重启进程且代码与镜像均未变化，可执行：

```powershell
Set-Location backend
docker compose restart api
```

`docker compose restart api` 不会重建镜像，因此修改了 `backend/server_api/` 后必须使用第一组命令。

修改 worker、开奖抓取、自动下注发送或结算代码后，需要同时重建 API 和 worker：

```powershell
Set-Location backend
docker compose up --build --force-recreate -d --wait api worker
Invoke-WebRequest http://127.0.0.1:8080/health/ready
```

本地启动与生产部署说明见 [`docs/server-deployment.md`](docs/server-deployment.md)。

手工诊断脚本位于 `tools/diagnostics/`，不属于自动化测试套件。它们可能访问本地客户端、数据库或外部服务，应按脚本说明单独运行。

## 打包

### 普通用户版

```powershell
.\.venv\Scripts\python.exe tools\build.py --clean
```

或运行：

```powershell
.\build.bat
```

### 管理员版

```powershell
.\.venv\Scripts\python.exe tools\build.py --admin --clean
```

输出写入被 Git 忽略的 `dist/` 目录。版本号由 `app/build_config.py` 或 `STARTRACE_VERSION` 环境变量决定。

本地构建配置应从 `build_env.bat.example` 创建；发布配置应从 `release_user_config.ps1.example` 或 `release_user_config.bat.example` 创建。真实密钥、配置和安装包不应提交到 Git。

发布、签名和 CDN 更新流程见 [`docs/release-packaging.md`](docs/release-packaging.md)。

## 目录说明

```text
app/                 生产应用包
  models/            数据模型
  services/          消息、开奖、下注、设置、更新等业务服务
  ui/                PySide6 界面组件
  utils/             请求、代理、路径和日志等通用工具
assets/              运行时图标等静态资源
docs/                当前技术和运行文档
docs/archive/        历史设计、恢复证据和会话资料
tests/               自动化回归测试
tools/               构建、发布和运行时辅助工具
tools/diagnostics/   手工探针、恢复和诊断工具
```

## 关键模块

| 模块 | 用途 |
| --- | --- |
| `app/main.py` | 应用启动入口，解析用户版/管理员版参数。 |
| `app/services/chat_service.py` | 加载、过滤、解析和统计聊天消息。 |
| `app/services/auto_bet_service.py` | 自动下注运行时、去重、结算与策略状态。 |
| `app/services/frequency_probability_analysis.py` | 历史频率概率与动态压三门决策。 |
| `app/services/ai_bet_client.py` | OpenAI 兼容与 Anthropic 格式的 AI 建议请求。 |
| `app/services/history_fetchers.py` | 站点历史开奖结果获取与规范化。 |
| `app/utils/fetch_date.py` | 当前期、下一期和倒计时信息获取。 |
| `app/ui/auto_bet_panel.py` | 自动下注配置、实战统计和策略界面。 |
| `tools/build.py` | PyInstaller 用户版/管理员版构建入口。 |

## 文档

当前文档索引见 [`docs/README.md`](docs/README.md)。历史恢复资料、旧设计和已完成计划位于 `docs/archive/`，仅供追溯，不代表当前实现。
