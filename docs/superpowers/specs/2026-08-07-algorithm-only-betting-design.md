# 纯算法下注设计（暂时停用 AI 干涉）

日期：2026-08-07
状态：已批准

## 背景与目标

服务器端自动下注策略（`strategy_scheduler.py`）当前流程为：频率分析 → 调用外部 DeepSeek AI（`SharedAiClient`）确认 → 决定是否下注。由于 DeepSeek API 响应时间极不稳定（实测 0.2s~45s+），经常超过后端 45 秒超时阈值，导致每期产生 `ai_error`（"The read operation timed out"），自动下注被跳过。

目标：

1. **暂时停止 AI 干涉**，完全由频率/概率算法支持下注推断（频率达标即下注）。
2. **保留 AI 配置与代码路径**，通过开关控制，日后可随时恢复。
3. **四站点开奖数据持续自动落库备份**（现状已满足，无需改动）。

## 已确认的需求决策

| 决策点 | 选择 |
| --- | --- |
| 改动范围 | 仅服务端（exe 无需重新打包） |
| 纯算法判定标准 | 频率达标即下注（三门最高概率 ≥ 阈值） |
| AI 配置处理 | 保留配置（数据库 + .env），代码停用 |
| 开奖数据存储 | 保持现状（已自动落库，带唯一约束） |

## 现状分析

- 服务器运行代码位于 `/opt/startrace/backend`（非 git 仓库），与本地 git 仓库版本存在差异（服务器含 `ai_settings.py` 的 `saved_ai` 逻辑）。
- `strategy_scheduler.py` 的 `schedule_frequency_orders` 中，`ai_client is None` 分支当前行为是"服务器 AI 未配置，跳过本期"（跳过下注）。
- 四站点开奖数据已由 worker 每 5 秒从外部 API 抓取并 upsert 到 `draw_results` 表（`(site, period)` 唯一约束，当前 3000+ 期无重复）。
- 客户端服务器模式事件去重与刷新依赖 `key_activity_types`（含 `ai_execute`、`ai_error`、`ai_skip`、`frequency_skip`）。

## 设计决策

### 1. `AI_DECISION_ENABLED` 开关（默认关闭 = 纯算法）

新增环境变量控制 AI 决策是否启用，默认 `false`（纯算法模式）。开关开启且 AI 配置存在时走原 AI 流程，可完整恢复旧行为。

### 2. 纯算法决策流程

`schedule_frequency_orders` 中 `ai_client is None` 分支由"跳过本期"改为"算法直接下注"。开关关闭或 AI 未配置时，频率达标即按 `selected_plays` 创建 `BetOrder`。

### 3. 事件兼容（旧 exe 无需重新打包）

算法下注复用 `ai_execute` 事件类型，消息标注"算法决策下注"。纯算法模式下不再产生 `ai_error` / `ai_skip`。`_DECISION_EVENT_TYPES` 保持不变。

### 4. 开奖数据备份

保持现状：worker 已从外部 API 持续抓取四站点每期开奖数据并自动落库，无需改动。

## 详细改动

### 文件清单（基准：服务器源码 `/opt/startrace/backend`）

| 文件 | 改动 |
| --- | --- |
| `server_api/settings.py` | 新增 `ai_decision_enabled: bool`，读 `AI_DECISION_ENABLED`，默认 `false` |
| `.env` | 新增 `AI_DECISION_ENABLED=false` |
| `server_api/worker.py` | `_run_cycle` 中：仅当 `settings.ai_decision_enabled` 为真时才构造 `ai_client`（保留现有 `load_ai_configuration` / `_shared_ai_client_from_settings` 构造代码） |
| `server_api/workers/strategy_scheduler.py` | `ai_client is None` 分支改为算法直接下注；抽取下注逻辑（创建 `BetOrder`）为 AI 与算法共用路径 |

### `strategy_scheduler.py` 决策逻辑（改后）

```
analysis = analyze(...)
if not analysis["should_bet"]:
    → frequency_skip 事件，跳过
plays = selected_plays
if ai_client is not None:
    decision = ai_client.recommend_three_doors(...)
    if 请求失败: → ai_error 事件，跳过
    if action != "execute" 或 confidence < 阈值: → ai_skip 事件，跳过
    → ai_execute 事件（消息含 AI 置信度与原因）
else:
    → ai_execute 事件（消息：频率达标，算法决策下注，最高 X%，达到阈值 Y%）
创建 BetOrder（每组 × 每玩法）
```

### 事件消息示例

- 纯算法：`频率达标：三门 小单,小双,大单；算法决策下注（最高 67.5%，达到阈值 45%）`
- 频率未达：`频率未达阈值：三门 ...，最高 X% < 阈值 Y%`（保持）

## 测试

- 更新 `backend/tests/test_strategy_scheduler.py`：
  - AI 未配置（`ai_client is None`）时不再记录 `ai_error`/跳过，改为算法下注。
- 新增用例：
  - 开关关闭时频率达标 → 直接下注、事件类型为 `ai_execute`、不产生 `ai_error`。
  - 开关关闭时频率未达标 → `frequency_skip`、不创建 `BetOrder`。
  - 开关开启且 AI 配置存在 → 保持原 AI 确认流程。

## 部署与回滚

部署：

```bash
cd /opt/startrace/backend
docker compose up --build --force-recreate -d --wait api worker
# 验证
curl http://127.0.0.1:8080/health/ready
```

回滚：将 `AI_DECISION_ENABLED` 改为 `true` 并重建容器，即恢复 AI 决策流程（配置与代码均已保留）。

## 本地 git 同步

将服务器改动及服务器新增文件（`ai_settings.py` 等）同步回本地 git 仓库并提交，保证代码可追溯。
