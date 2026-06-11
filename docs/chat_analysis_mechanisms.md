# 聊天分析机制说明

本文档基于当前工作区代码快照整理，回答以下问题：

1. 现在如何获取站点数据，频率多少，失败时怎么办
2. 现在如何读取数据库聊天记录
3. 现在如何统计每个群的下注信息
4. 现在如何屏蔽黑名单
5. “线路选择”“账号与数据源”“筛选条件”“屏蔽名单”以及右侧“期号筛选”的 UI 语义如何划分

`docs/ui_and_flow.md` 当前是占位文件，不能作为权威说明；本文件才是基于代码核对后的说明。

## 1. 站点数据获取

站点定义和抓取入口在 `app/utils/fetch_date.py`。

- 支持的线路是 `pc28`、`macao`、`australia`、`norway`。
- 每个线路都绑定了自己的外部接口、来源站点标签和默认开奖间隔 `_SITE_INTERVAL_SEC`。
- 启动分析页时，`app/ui/main_window_realtime.py` 的 `_refresh_site_cards()` 会调用 `fetch_all_draw_infos()`，并发抓取所有线路数据，填充左侧“线路选择”卡片。
- 主窗口显示后，`app/ui/main_window.py` 会启动两个定时器：
  - `_refresh_timer.start(5000)`：每 5 秒刷新一次当前激活线路的开奖信息。
  - `_countdown_timer.start(1000)`：每 1 秒更新一次倒计时显示。

当前激活线路的刷新链路如下：

1. `main_window_realtime._on_refresh_tick()`
2. `fetch_date.extract_draw_info(site)`
3. 对应站点的抓取函数，例如 `fetch_pc_28_date()`、`fetch_macao_date()`
4. 对应解析器，例如 `_parse_pc28()`、`_parse_macao()`
5. 回写到 `self._draw_infos[self._active_site]`

失败处理分两层：

- 网络失败或接口失败：`_on_refresh_tick()` 会记录异常日志，但保留当前内存里的旧开奖信息。
- 解析失败：`extract_draw_info()` 会尝试 `_extrapolate_fallback(site)`，基于上一份成功数据和线路默认间隔推导一个回退结果。

如果一条线路从来没有拿到过有效数据，那么 `_last_good_draw` 为空，回退结果只能是空 `DrawInfo(current_period="")`。这也是为什么首次启动时如果接口异常，界面上可能只看到空期号和空倒计时。

无法正常获取站点数据时，优先排查四类问题：

- 代理设置是否错误。代理配置通过 `fetch_date.set_proxy_settings()` 写入环境变量。
- 外部接口是否改了返回格式。比如 `pc28` 当前解析依赖 `issue[0]`；如果接口返回空数组，就会抛出 `PC28: API 返回空 issue 列表`。
- 站点可访问但字段名变了，导致解析器失效。
- 首次加载就失败，没有历史成功数据可回退。

## 2. 聊天数据库读取

“账号与数据源”由 `app/services/account_resolver.py` 和 `app/ui/main_window_data.py` 共同完成。

### 2.1 自动定位数据库

自动定位流程如下：

1. 从 `shared_preferences.json` 读取账户信息。
2. 解析出账号昵称、`accid`、`imAppid`。
3. 在 `TencentCloudChat/Config` 下拼接候选目录。
4. 检查 `im.db` 和 `msg_0.db` 是否同时存在。
5. 用 `im.db` 做一次账号校验，确认目录确实属于当前用户。

对应代码入口：

- `account_resolver.AccountResolver.resolve()`
- `_load_accounts()`
- `_candidate_dirs()`
- `_validate_db()`

如果自动定位失败，UI 会显示诊断信息，并允许用户在“手动数据源”里直接选择 `.db`、`.sqlite` 或 `.txt` 文件。

### 2.2 实际读取消息

消息读取入口是 `chat_service.ChatLogService.load_messages()`。

- 如果数据源后缀是 `.txt`，走 `load_messages_from_text()`。
- 否则走 `load_messages_from_sqlite()`。

SQLite 读取的关键特点：

- 只读连接：使用 `sqlite3.connect(file:... ?mode=ro, uri=True)`。
- 兼容多种表结构：会依次尝试 `message`、`msg` 等几种查询模板。
- 自动识别 `client_time` 单位：秒、毫秒、微秒都能兼容。
- 默认不是全库读取：如果没有显式时间范围，也没有增量游标，就自动套用最近 20 分钟窗口 `DEFAULT_SQLITE_LOAD_WINDOW`。
- 如果已经读过当前线路，会带上 `incremental_cursor_value` 和 `incremental_cursor_rand` 做增量读取。

对应代码入口：

- `main_window_data._build_load_options()`
- `chat_service.load_messages_with_cache()`
- `chat_service.load_messages_from_sqlite()`
- `chat_service._apply_sqlite_query_options()`

消息正文抽取并不是简单读某一个字段，而是会综合 `element_descriptions` 和 `content`，再尝试：

- 解析 JSON 结构里的文本字段
- 抽取多行消息中的有效文本
- 排除看起来像密文或无意义 blob 的内容

这部分逻辑在 `chat_service._extract_message_text()`。

## 3. 下注统计

下注统计入口是 `chat_service.analyze_bets()`。

当前统计流程是：

1. 先调用 `filter_blocked_messages()` 做屏蔽过滤。
2. 再调用 `extract_bet_visual_data()` 解析下注事件、回执事件和撤单事件。
3. 最后按玩法把 `visual_rows` 再汇总成 `StatsResult.totals`。

当前影响统计作用域的条件主要来自 `main_window_data._gather_parse_options()`：

- 左侧群组勾选
- 时间范围
- 屏蔽名单
- 当前线路
- 右侧“期号筛选”输入框 `period_input`

### 3.1 “每个群的下注信息”现在是怎么来的

当前代码并没有生成一个“每群一份 totals”的独立数据结构。

现在真实存在的是两层结果：

- `visual_rows`：每一条可视化下注行都会保留 `group`
- `StatsResult.totals`：对全部 `visual_rows` 再按玩法做一次总汇总

这意味着：

- 左侧群组筛选会缩小消息读取和统计范围，所以能间接做到“只看某几个群的 totals”。
- 但系统内部没有真正的“按群 totals map”，例如 `{group -> {play -> amount}}` 这种结构目前并不存在。

换句话说，当前实现支持“先筛选群，再看汇总”，但不支持“同一次统计结果里并列保留多个群各自的 totals”。

### 3.2 期号筛选怎样参与统计

右侧输入框当前挂在 `main_window_layout.period_input`，事件入口是 `main_window_realtime._on_period_input_changed()`。

- 默认情况下，它会跟随当前线路的“下一期”。
- 手动输入后，会把 `_manual_period_override` 设为 `True`。
- 之后 `_gather_parse_options()` 会把它作为 `period_filter` 传给下注分析。

在 `chat_service.extract_bet_visual_data()` 中，系统会用 `event.period` 和 `period_filter` 做精确比对，不匹配的事件会被过滤掉。

## 4. 屏蔽名单

当前 UI 里的“屏蔽名单”编辑器位于 `app/ui/main_window_layout.py`，行为在 `app/ui/main_window_blocking.py`。

现有界面实际支持的是：

- 选择一个群组
- 为这个群组保存一组名称
- 以 `blocked_names_by_group` 的形式持久化

对应的运行时过滤逻辑在 `chat_service.filter_blocked_messages()`：

- 先按 `blocked_names` 过滤用户名
- 再按 `blocked_user_ids` 过滤发送者 ID
- 最后再按 `_is_group_blocked_name(msg.group, msg.username)` 过滤群组规则

### 4.1 当前实现与已确认术语的偏差

你已经确认的术语是：

- `全局屏蔽名单`：适用于机器人等跨群固定账号
- `群组屏蔽名单`：只对单个群组生效

但当前实现与这个术语并不一致，原因是：

- UI 保存的是 `group_block_rules`
- 但 `main_window_blocking._blocked_names()` 会把所有群组规则里的名字扁平化
- `_gather_parse_options()` 又把这个扁平后的列表作为 `blocked_names` 传入分析流程

结果就是：名义上只属于某个群的屏蔽名称，会先被当成“全局屏蔽名单”过滤一次，然后再按群规则过滤一次。

这意味着当前代码里存在一个已知偏差：

- “群组屏蔽名单”实际上会泄漏成“伪全局屏蔽名单”。

文档上应该明确写明这是现状 bug，而不是把它包装成既有设计。

## 5. UI 语义划分

基于代码和你刚确认的术语，当前 UI 应按下面的语义理解。

### 5.1 左侧“线路选择”

语义：选择开奖站点，以及与该站点绑定的当前期、下一期、倒计时和开奖节奏。

它不负责：

- 选择聊天数据库
- 选择聊天账号

### 5.2 左侧“账号与数据源”

语义：先根据账号自动定位本地聊天数据库；失败后允许手动指定消息数据源。

它解决的是“读哪份聊天数据”，不是“按哪个站点解释开奖期号”。

### 5.3 左侧“筛选条件”

语义：定义统计作用域。

它当前至少包括：

- 时间范围
- 左侧群组勾选
- 右侧的期号筛选

虽然“期号筛选”控件摆在右侧，但从代码行为看，它已经参与消息统计，因此语义上属于筛选条件的一部分。

### 5.4 左侧“屏蔽名单”

语义：定义需要从统计中排除的人名规则。

你已经确认它应当分成两个概念：

- `全局屏蔽名单`
- `群组屏蔽名单`

但当前 UI 只提供了群组级编辑器，还没有单独的全局编辑器。

### 5.5 右侧“期号筛选”

规范语义：它是筛选条件中的期号条件。

当前行为：

- 默认跟随当前线路下一期
- 手动输入后覆盖默认值
- 切换线路时会被清空
- 设置持久化时只保存一个全局 `query_period_override`

这和已确认规范存在偏差。你已经确认，期号筛选应按线路分别记忆，而不是全局共享一个值。

### 5.6 右侧“可见群组”

规范语义：它只控制展示范围，不定义底层统计作用域。

这意味着：

- 左侧群组筛选决定 totals 和统计输入集
- 右侧“可见群组”只控制右侧图表和消息明细怎么看

当前代码与该规范部分一致、部分不一致：

- 一致：右侧群组勾选不会重新计算 `StatsResult.totals`
- 不一致：它会影响右侧消息明细视图 `_filtered_messages_for_view()` 的显示范围

## 6. 已确认但尚未对齐实现的点

下面这些点已经通过术语确认，但当前实现还没完全对齐：

1. 屏蔽名单应明确分成“全局屏蔽名单”和“群组屏蔽名单”，且不能互相泄漏作用域。
2. 左侧群组筛选决定统计作用域；右侧可见群组只决定展示作用域。
3. 右侧输入框的规范名称应固定为“期号筛选”。
4. 期号筛选应按线路分别记忆，而不是用一个全局 `query_period_override` 共享。
5. 当前系统支持“筛选到某个群后看 totals”，但尚未提供真正的“按群分别保存 totals”结构。
