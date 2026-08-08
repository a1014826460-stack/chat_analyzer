# 下注系统全景：策略、下注种类与功能清单

> 本文档系统梳理 StarTrace 的下注体系，用于复盘与决策参考。
> 最后核对：2026-08-08（服务器 UTC 时间）。所有配置以数据库实际状态为准。

## 1. 总览：两套下注体系

系统同时存在**两套自动下注体系**，容易混淆，务必分清：

| | 服务端三门策略 | 客户端本地策略 |
| --- | --- | --- |
| 运行位置 | 服务器 worker（`backend/server_api`） | exe 客户端本机（`app/services/auto_bet_service.py`） |
| 配置存储 | PostgreSQL `auto_bet_strategies` 表 | 客户端本机设置（SettingsService 的 `auto_bet` 键） |
| 决策方式 | 纯频率算法（三门） | 趋势/平注/倍投 + AI 建议流程 |
| 当前状态 | **🟢 生效（算法模式）** | ⚪ 客户端默认走服务器模式，本地策略需 AI 客户端（已停用） |
| 事件记录 | `strategy_events` / `runtime_log_events` 表 | 客户端本地日志 |

**当前生产实际生效的是「服务端三门策略」。** 客户端本地策略在服务器模式下不运行；即便本地模式，其 trend/flat/martingale 走 AI 流程，AI 停用后不可用。

---

## 2. 策略种类

### 2.1 服务端策略（AutoBetStrategy）—— 三门频率算法

**决策逻辑（`strategy_scheduler.py` + `draws.py`）**：

```
取最近 history_count 期开奖
→ 统计四种复合玩法（小单/大双/小双/大单）出现概率
→ 排除概率最低的玩法（保留三门）
→ 三门中最高概率 ≥ confidence_threshold？
    是 → 对每个目标群 × 每门 创建 BetOrder 下注
    否 → 记 frequency_skip，跳过本期
```

**参数表**：

| 参数 | 含义 | 当前策略1值 |
| --- | --- | --- |
| `site` | 站点（pc28/macao/australia/norway） | pc28 |
| `history_count` | 历史期数窗口 | 50 |
| `confidence_threshold` | 三门最高概率阈值（%） | 45 |
| `bet_amount` | 每门金额（元） | 10 |
| `target_groups` | 目标群组 ID 列表 | ["207191791"]（测试1群） |
| `require_confirmation` | 是否需人工确认后发送 | false（直接发） |
| `enabled` | 是否启用 | true |

**决策事件类型**（客户端日志可见）：

| 事件 | 含义 |
| --- | --- |
| `frequency_skip` | 频率未达标，跳过 |
| `ai_execute` | 频率达标，算法下注（复用原 AI 执行事件类型） |
| `ai_error` / `ai_skip` | 仅 AI 模式产生（当前纯算法模式不再产生） |

**当前实例**（数据库 `auto_bet_strategies`）：

| id | 用户 | 站点 | 启用 | 窗口 | 阈值 | 确认 | 金额 | 群组 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | user 1 | pc28 | ✅ | 50 | 45% | 否 | 10元 | 测试1群 | **生效** |
| 2 | user 2 | pc28 | ❌ | 500 | 2% | 否 | 1000元 | 跑火车群 | 禁用 |
| 3 | user 3 | pc28 | ❌ | 50 | 25% | 否 | 10元 | 测试1群 | 禁用 |

### 2.2 客户端本地策略（StrategyConfig）—— 3 种类型

客户端模型定义三种 `strategy_type`（`app/models/auto_bet.py`）：

| 类型 | 策略含义 | 判定条件 | 下注 |
| --- | --- | --- | --- |
| `trend_following` 趋势跟踪 | 最近 N 期出现连续同结果时反向押注 | 连续 `trigger_threshold` 期结果相同（如连续 3 期"大"） | 反向押"小" |
| `flat` 平注 | 固定金额押选定玩法 | 无条件（直接下注） | 每期固定押 `play_types` |
| `martingale` 倍投 | 固定玩法 + 输后加倍 | 无条件，按倍投序列递增 | 按 `martingale_sequence` 递增金额 |

**关键参数**：`observation_window`（观察窗口，默认10期）、`trigger_threshold`（触发期数，默认3）、`martingale_sequence`（倍投序列）、`take_profit_limit`/`stop_loss_limit`（止盈止损）、`bet_mode`（见下）。

**⚠️ 重要说明**：客户端本地策略的 trend/flat/martingale 在当前代码中都进入 **AI 建议流程**（`_process_ai_period`），由 AI 客户端决定玩法。由于 AI 已停用（`AI_DECISION_ENABLED=false` + 客户端无 AI 凭据），**这些本地策略当前实际不可用**；客户端本地模式若想下注，只能依赖三门下注路径（`bet_mode=three_doors`）。

---

## 3. 下注种类（玩法）

### 3.1 全部玩法与默认赔率（`DEFAULT_ODDS`）

| 玩法 | 类别 | 默认赔率 |
| --- | --- | --- |
| 大 | 大小 | 1.98 |
| 小 | 大小 | 1.98 |
| 单 | 单双 | 1.98 |
| 双 | 单双 | 1.98 |
| 小单 | 复合（小+单） | 3.68 |
| 大双 | 复合（大+双） | 3.68 |
| 小双 | 复合（小+双） | 4.28 |
| 大单 | 复合（大+单） | 4.28 |

### 3.2 实际下注的两条路径

| 路径 | 下注玩法 | 说明 |
| --- | --- | --- |
| **服务端三门策略** | 复合玩法四选三（排除最冷一门） | 每期 3 笔订单，每笔 `bet_amount` |
| **客户端 `bet_mode`** | `size`：单一玩法（大/小/单/双…） | 按配置 `play_types` |
| | `three_doors`：三门（与服务端同款算法） | 每期 3 笔 |

**服务端历史订单实际玩法**（`bet_orders` 表，645 笔）：全部为复合玩法——大双182 / 小单166 / 大单157 / 小双140，确认服务端只下三门。

### 3.3 金额计算示例

服务端策略 1（10元/门、测试1群）达标时：

```
群 207191791（测试1群）× 三门（如 小单/大双/小双）= 3 笔 × 10 元 = 30 元/期
```

多群组时按 群数 × 3 门 放大。

---

## 4. 功能种类清单

| 功能 | 说明 | 位置 |
| --- | --- | --- |
| **自动下注** | 服务端三门算法 / 客户端本地策略 | 服务端 worker + 客户端 |
| **AI 建议决策** | 外部 AI（DeepSeek）确认是否下注 | 服务端 `ai_client.py`，**已停用** |
| **频率概率分析** | 三门概率统计与面板展示 | `frequency_probability_analysis.py` |
| **开奖抓取与历史备份** | 四站点每期自动抓取落库 | `crawler.py` + 外部 API |
| **当前期/倒计时** | 获取下注窗口与期号 | `current_period.py` |
| **下注发送（WSS）** | 将订单发送到群聊 | `sender.py` + WSS 凭证 |
| **订单与结算** | 订单状态流转、开奖后结算 | `bet_settlements.py` |
| **授权（激活码）** | 激活码校验控制下注发送 | `sender.py` 校验 `activation_codes` |
| **服务器模式/本地模式** | 客户端两种运行模式 | 客户端「帮助 → 服务器模式」 |
| **在线授权/激活** | 机器码 + 激活码登录 | `auth` 路由 |
| **管理端** | 管理员后台（admin 路由） | `api/routes/admin.py` |
| **运行统计** | 下注/结算/胜率统计 | `bet_statistics.py` + 客户端面板 |
| **倍投/止盈止损** | 客户端本地策略的辅助控制 | 客户端 `StrategyConfig` |
| **人工确认** | 订单需客户端确认才发送 | `require_confirmation` 字段 |

---

## 5. 当前生产状态（2026-08-08）

- **生效策略**：仅策略 1（pc28 / 50期 / 45% / 10元 / 测试1群 / 直接发送）。
- **算法模式**：`AI_DECISION_ENABLED=false`，worker 不构造 AI 客户端，频率达标直接下注。
- **订单总量**：645 笔（状态：618 sent / 27 failed）。
- **近期策略事件**：全部 `frequency_skip`（最高频率约 32-34% < 45% 阈值），下注未触发。
- **站点**：四站点开奖数据均自动落库（`draw_results` 3500+ 期），但仅 pc28 配置了策略。

---

## 6. 已知问题（复盘重点）

### ⚠️ 问题 1：user 1 激活码已过期，下注发送失败

- 用户 1（策略 1 归属，`activation_id=3`）的激活码 `expires_at = 2026-08-07 09:27:51`，**已过期**。
- 服务器当前时间：2026-08-08 14:21 UTC。
- 表现：08-08 02:22-02:36 有 27 笔订单因 `authorization is inactive` 发送失败（`bet_attempts` 表错误信息）。
- 根因：`sender.py:120` 发送前校验激活码，`authorization.revoked` 或 `expires_at <= now` 即拒绝。
- **影响**：即使策略 1 频率达标，下注也无法发送。
- **待处理**：需为用户 1 续期/重新生成激活码（更新 `activation_codes` 或走授权流程）。

### ⚠️ 问题 2：策略 2/3 已禁用，但配置保留

- 策略 2（1000元/门、2%阈值）几乎期期下注，策略 3（10元/门、25%阈值）达标率高。当前均禁用，未触发。

### ℹ️ 说明：客户端本地策略当前不可用

- 因 AI 停用 + 服务器模式，客户端 trend/flat/martingale 本地策略不生效；本地仅三门下注路径可用。

---

## 7. 复盘指引

排查「为什么没下注 / 下注失败」按以下顺序查：

1. 策略是否启用、频率是否达标 → `strategy_events`（`frequency_skip` 说明频率不足）。
2. 订单是否创建 → `bet_orders`（无订单 = 未触发；有订单看 `status`）。
3. 发送是否成功 → `bet_attempts.error_message`（`authorization is inactive` = 激活码过期）。
4. 是否 AI 模式 → `AI_DECISION_ENABLED` 配置（当前 false = 纯算法）。

查询示例：

```sql
-- 最近策略决策
SELECT site, period, event_type, message FROM strategy_events ORDER BY id DESC LIMIT 10;
-- 最近订单及发送结果
SELECT b.period, b.play_type, b.amount, b.status, a.error_message
FROM bet_orders b LEFT JOIN bet_attempts a ON a.order_id = b.id
ORDER BY b.id DESC LIMIT 10;
-- 激活码有效性
SELECT id, expires_at, revoked FROM activation_codes ORDER BY id;
```
