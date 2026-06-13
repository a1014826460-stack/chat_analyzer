# 下注统计核心逻辑

本文记录聊天下注统计从数据库到右侧统计面板的核心数据链路。

## 1. 数据库读取

入口是 `MainWindowDataMixin._load_filtered_messages()`，它会构造 `ParseOptions` 并调用 `ChatLogService.load_messages_with_cache()`。

SQLite 数据库读取逻辑在 `ChatLogService.load_messages_from_sqlite()`：

- 主消息库通常是 `msg_0.db`。
- 同目录 `im.db.groupinfo` 用于把 `message.sid` 这类群组编号映射成真实群名。
- 群组筛选使用 `ParseOptions.group_ids`，例如 `900361932`。
- 默认读取最近 5 分钟消息；如果启用高级时间筛选，则使用用户选择的开始/结束时间。
- `账号与数据源` 的用户名只用于定位数据库和保存设置，不参与聊天消息 sender 过滤。

## 2. 解析参数

`MainWindowDataMixin._gather_parse_options()` 会收集：

- 左侧群组筛选选中的 `group_ids` 和群名。
- 右侧查询期数 `period_filter`。
- 当前线路 `site` 和对应开奖间隔。
- 全局屏蔽名单和群组屏蔽名单。

注意：`ParseOptions.username` 固定为空，避免把登录账号名误当成聊天发送者过滤条件。

## 3. 消息解析

`ChatLogService.analyze_bets()` 先过滤黑名单，再调用 `extract_bet_visual_data()` 生成右侧表格行。

核心解析路径：

- 星座类群名，如 `摩羯座`，走 `_resolve_receipt_group_bet_events()`。
- 普通群走 `_resolve_direct_group_bet_events()`。
- 多行机器人回执格式会解析为下注事件：

```text
@用户 :
下注期数: 1040954
下注内容:
------------
大单2800(4.28赔率)
13.500(12.0赔率)
------------
余额：53747
```

其中：

- `@用户` 是实际下注人。
- `下注期数` 是统计期号。
- `大单2800` 解析为玩法 `大单`、金额 `2800`。
- `13.500` 解析为玩法 `13`、金额 `500`。

## 4. 去重和汇总

解析出的事件会按以下规则进入统计：

- 只保留当前查询期数匹配的事件。
- 同一下注人、同一期号、同一玩法，保留金额更大的最新回执值。
- 取消消息会删除对应下注。
- 整期汇总榜、在线人数积分榜不会当作下注，避免重复统计。

最终输出：

- `visual_rows`：右侧明细表格。
- `StatsResult.totals`：按玩法汇总。
- `StatsResult.totals_by_group`：按群组再按玩法汇总。

## 5. 为什么之前会显示空

之前 `_gather_parse_options()` 把账号输入框里的用户名传给了 `ParseOptions.username`。

这会导致数据库读取阶段只保留发送者等于该用户名的消息。但机器人回执的发送者通常是机器人 ID，例如 `TfPISL2u5`，不是用户输入的账号名，所以有效下注消息被全部过滤，右侧显示“当前期未找到下注记录”。

修复后，账号用户名不再过滤聊天消息。
