# 统一服务端下注体系设计

日期：2026-08-08
状态：待用户审阅

## 背景与目标

系统存在两套并行下注体系：**客户端本地策略**（历史遗留：trend/flat/martingale/AI，读本地聊天记录本地计算）与**服务端三门策略**（演进体系：`AutoBetStrategy` + 三门频率算法）。两者代码独立、逻辑有差异，客户端本地策略在服务器模式下不运行但代码/界面残留，造成算力浪费与混淆。

目标：

1. **统一服务端计算**：所有策略计算与下注执行在服务端，客户端只做配置与展示；客户端本地策略引擎**停用不删**（代码冻结、界面移除入口）。
2. **记录每个用户每次下注的策略和结果**：`bet_orders` 扩展策略快照字段 + 结果字段，开奖后按玩法回写中/不中。
3. **服务端扩展多策略类型**：三门 / 趋势跟踪 / 平注 / 倍投统一在服务端执行。
4. **客户端重新打包**：强制服务器模式、移除本地策略配置界面、概率分析面板动态高度与北京时间显示。

## 已确认的需求决策

| 决策点 | 选择 |
| --- | --- |
| 客户端本地策略引擎 | 停用不删（代码冻结，界面移除入口） |
| 下注记录粒度 | 加策略快照（参数、选中玩法、概率、依据） |
| 结果记录 | 开奖后回写每笔订单中/不中，按玩法判定 |
| 客户端打包 | 重新打包 exe |
| 客户端模式 | 强制服务器模式；未配置服务器/未登录时自动下注禁用并提示 |
| 服务端策略类型 | 扩展多类型：three_doors / trend_following / flat / martingale |
| 快照存储 | 扩展 `bet_orders` 表 |
| 结果判定粒度 | 按玩法判定（精确命中 exact_hit / 方向命中 direction_hit） |
| 策略数量 | 每用户一条（保持 user_id 唯一），可选策略类型 |
| 参数配置入口 | 客户端服务器模式界面（经 API 保存到服务端） |
| 历史订单 | 仅新订单记录，历史 645 笔不回填 |
| 模式兜底 | 未配置服务器时自动下注禁用并提示 |

## 现有代码定位

- 客户端本地策略引擎：`app/services/auto_bet_service.py`（trend/flat/martingale/AI 主循环）、`app/models/auto_bet.py`（`StrategyConfig`）。
- 服务端策略：`backend/server_api/workers/strategy_scheduler.py`（`schedule_frequency_orders`）、`backend/server_api/services/draws.py`（`analyze`）、`backend/server_api/db.py`（`AutoBetStrategy`/`BetOrder`）、`backend/server_api/api/routes/strategies.py`（GET/PUT `/v1/strategies/auto-bet`）。
- 结算：`backend/server_api/services/bet_settlements.py`。
- 概率分析面板：`app/ui/auto_bet_panel.py`（`_frequency_analysis_box` / `_frequency_analysis_label`，`updated_at` 在 418 行，长文本在 432-453 行）。

## 设计

### 1. 服务端策略模型扩展（`auto_bet_strategies` 表 + API）

新增字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `strategy_type` | String | `three_doors` / `trend_following` / `flat` / `martingale`，默认 `three_doors` |
| `play_types` | String(JSON) | 平注/倍投押注玩法列表（如 `["大","小"]`） |
| `observation_window` | Integer | 趋势策略观察期数（默认 10） |
| `trigger_threshold` | Integer | 趋势策略连续期数触发（默认 3） |
| `martingale_sequence` | String(JSON) | 倍投金额序列（如 `[10,20,40]`） |

保留现有字段：`site`、`history_count`、`confidence_threshold`、`require_confirmation`、`bet_amount`、`target_groups_json`、`target_group_names_json`、`enabled`。

API：`GET/PUT /v1/strategies/auto-bet` 扩展上述字段的读写；服务端校验 `strategy_type` 合法值与参数范围。

### 2. 服务端策略引擎扩展（`strategy_scheduler.py`）

`schedule_frequency_orders` 依据 `strategy.strategy_type` 分派：

| 类型 | 判定逻辑 | 下注 |
| --- | --- | --- |
| `three_doors` | 现有三门频率算法（`analyze`） | 选中三门 × `bet_amount` |
| `trend_following` | 最近 `observation_window` 期，连续 `trigger_threshold` 期同一结果 → 反向押注 | 反向玩法 × `bet_amount` |
| `flat` | 无条件 | 固定押 `play_types` × `bet_amount` |
| `martingale` | 固定押 `play_types`，连输按 `martingale_sequence` 递增金额 | 递增金额 |

- 每种类型保留现有决策事件机制（`frequency_skip`/`ai_execute`），消息标明策略类型与依据。
- 纯算法模式保持：`AI_DECISION_ENABLED=false`，AI 不干涉。
- 策略逻辑从客户端 `auto_bet_service.py` 移植（trend 反向判定、martingale 序列递增），保持行为一致。

### 3. 策略快照与结果记录（`bet_orders` 表扩展）

新增字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `strategy_type` | String | 下注时的策略类型快照 |
| `strategy_snapshot` | String(JSON) | 参数快照：`history_count`、`confidence_threshold`、`selected_plays`、`highest_probability`、`decision_reason`、`martingale_step` 等 |
| `result` | String | `pending` / `win` / `lose` / `expired` / `failed`，默认 `pending` |
| `result_detail` | String | `exact_hit` 精确命中 / `direction_hit` 方向命中（未命中为空） |

创建 `BetOrder` 时写入 `strategy_type` 与 `strategy_snapshot`（决策依据来自对应策略的判定结果）。

**结果回写**：`bet_settlements.py` 扩展，开奖后按玩法判定每笔订单：
- 压"小单"，开奖结果"小单" → `exact_hit`（精确命中）
- 压"小单"，开奖结果含"小"或"单"（如"小双"/"大单"）→ `direction_hit`（方向命中）
- 否则 → `lose`
- 失败/过期订单保留原 `failed`/`expired` 状态，不回写结果

### 4. 客户端改动（重新打包 exe）

- **强制服务器模式**：自动下注仅在服务器模式可用；未配置服务器/未登录时自动下注按钮禁用并提示。
- **移除本地策略配置界面**：trend/flat/martingale/AI 本地配置入口移除（`auto_bet_panel.py` 的本地策略配置区域）；本地策略引擎代码保留但不再被调用。
- **服务器模式策略配置**：`策略配置`按钮支持选择 `strategy_type` 并填写对应参数（观察期、触发期数、玩法、倍投序列、阈值、金额等），经 API 保存到服务端。
- **下注历史展示**：显示每笔订单的策略快照与中/不中结果。

### 5. 概率分析面板：动态高度与北京时间

**动态高度**（`auto_bet_panel.py` `_frequency_analysis_label`）：
- `_frequency_analysis_label` 已 `setWordWrap(True)`；在每次 `setText` 后动态调整高度，使"站点/目标期/更新时间"等长文本完整展示：
  ```python
  label = self._frequency_analysis_label
  label.setText(...)
  label.adjustSize()
  if label.width() > 0:
      needed = label.heightForWidth(label.width())
      if needed > label.minimumHeight():
          label.setMinimumHeight(needed)
  ```
- 或设置 `label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)`，让布局随 wordWrap 文本自动撑高 `_frequency_analysis_box`。
- 以实际效果为准，保证框高度随内容动态伸缩、不截断。

**北京时间显示**（`auto_bet_panel.py` 418 行）：
- 服务端 `analyze` 返回 `updated_at` 为服务器 UTC 时间（`datetime.utcnow().isoformat()`）。
- 客户端固定转换为北京时间（UTC+8），与用户本地时区无关：
  ```python
  from datetime import timedelta
  updated_at = (analyzed_at + timedelta(hours=8)).strftime("%H:%M:%S")
  ```
- 若 `analyzed_at` 无 tzinfo（naive UTC），直接 `+ timedelta(hours=8)`；服务端也可改为返回带 `+08:00` 的 ISO 时间作为可选优化。

### 6. 迁移与测试

**数据库迁移**：`alembic` 迁移新增 `auto_bet_strategies` 与 `bet_orders` 字段。

**服务端测试**（`backend/tests/`）：
- 四类策略引擎各自的下注判定与事件。
- 策略快照字段写入正确。
- 结果回写：按玩法判定 `exact_hit`/`direction_hit`/`lose`。
- `strategies` API 扩展字段的读写与校验。

**客户端测试**（`tests/`）：
- 强制服务器模式：未配置服务器时自动下注禁用。
- 策略配置界面：类型选择与参数保存。
- 概率分析面板：动态高度、北京时间显示。

### 7. 部署

```bash
cd /opt/startrace/backend
docker compose up --build --force-recreate -d --wait api worker
```

客户端重新打包：`tools/build.py`（用户版/管理员版）并发布。

## 兼容与回滚

- 客户端本地策略代码冻结保留，不删除；exe 界面移除入口。
- 纯算法模式开关 `AI_DECISION_ENABLED` 保持默认 false。
- 历史订单不回填，新订单自动记录快照与结果。
