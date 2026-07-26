# 历史频率概率与动态压三门实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于当前站点历史开奖记录展示 13/14 与八种玩法概率，并让动态压三门依据同一分析和最低置信度决定是否发送三门下注。

**Architecture:** 新建纯计算的 FrequencyProbabilityAnalyzer，以扩展后的 DrawResult.total 和规范化复合玩法标签为输入，产出不可变快照。AutoBetService 在刷新历史及处理三门下注前计算快照；主窗口在启动、站点切换和显式刷新时把快照交给面板。原始和值在抓取、SQLite 缓存和读取链路中完整保存。

**Tech Stack:** Python 3、dataclasses、SQLite、PySide6、pytest。

---

### Task 1: 保存原始和值到历史结果链路

**Files:**
- Modify: app/models/auto_bet.py
- Modify: app/services/history_fetchers.py
- Modify: app/services/draw_result_store.py
- Test: tests/test_draw_result_provider.py

- [ ] **Step 1: 写入失败测试。** 新增 test_history_fetcher_and_store_preserve_numeric_draw_total：模拟 sum=13 的历史记录，断言 HistoryFetcher 返回 DrawResult("1001", "pc28", "小单", total=13)，再写入 DrawResultStore 并断言读回 total 为 13。
- [ ] **Step 2: 验证 RED。** 运行 python -m pytest tests/test_draw_result_provider.py::test_history_fetcher_and_store_preserve_numeric_draw_total -q；预期因 DrawResult 缺少 total 或缓存未保存字段失败。
- [ ] **Step 3: 最小实现。** 给 DrawResult 添加 total: int | None = None；HistoryFetcher 传入已解析的 total；DDL 添加 result_total INTEGER；_init_db 用 PRAGMA table_info(draw_results) 检查旧数据库，缺列时执行 ALTER TABLE ADD COLUMN；插入、查询和 _row_to_result 都处理 result_total。
- [ ] **Step 4: 验证 GREEN。** 重跑同一测试，预期 PASS。
- [ ] **Step 5: 提交。** git add app/models/auto_bet.py app/services/history_fetchers.py app/services/draw_result_store.py tests/test_draw_result_provider.py；git commit -m "feat: preserve draw totals in history cache"。

### Task 2: 实现纯历史频率分析服务

**Files:**
- Create: app/services/frequency_probability_analysis.py
- Create: tests/test_frequency_probability_analysis.py

- [ ] **Step 1: 写入失败测试。** 用小单(13)、大双(14)、大单(15)、小双(12) 调用分析器，断言实际样本 4、13/14 各 25.0、小/单各 50.0、排除小单、保留 (大双, 小双, 大单)。另写 target_period 过滤后样本缩小及阈值不达标不下注的测试。
- [ ] **Step 2: 验证 RED。** 运行 python -m pytest tests/test_frequency_probability_analysis.py -q；预期模块不存在失败。
- [ ] **Step 3: 最小实现。** 定义 COMPOSITE_PLAY_ORDER=(小单, 大双, 小双, 大单) 和 PLAY_ORDER=(小, 单, 大, 双, 小单, 大双, 小双, 大单)。创建 frozen FrequencyProbabilityAnalysis，包含站点、目标期、分析时间、请求期数、实际样本、数值样本、13/14 概率、玩法概率、排除项、三门、最高概率、阈值、should_bet、reason。目标期存在时排除同一期和未来期记录，再取窗口最后 N 条。复合结果派生大小、单双、复合项；13/14 仅对合法 total 计数。以 (概率, 固定顺序索引) 排除最低门；无复合样本不下注；任一保留门达到阈值才下注。
- [ ] **Step 4: 增加边界测试并验证 GREEN。** 覆盖样本不足、未知结果、零样本、并列固定排除、无效和值、任一门达标和全部未达标。运行 python -m pytest tests/test_frequency_probability_analysis.py -q，预期 PASS。
- [ ] **Step 5: 提交。** git add app/services/frequency_probability_analysis.py tests/test_frequency_probability_analysis.py；git commit -m "feat: analyze historical draw probabilities"。

### Task 3: 让动态压三门复用分析并执行置信度门槛

**Files:**
- Modify: app/services/auto_bet_service.py
- Modify: tests/test_auto_bet_runtime.py

- [ ] **Step 1: 写入失败测试。** 断言任一保留门达到阈值时，每个目标群组三门均生成下注；所有保留门低于阈值时 _analyze_many 返回空；目标期历史被过滤；决策原因含样本、排除项、三门概率和阈值。
- [ ] **Step 2: 验证 RED。** 运行 python -m pytest tests/test_auto_bet_runtime.py -k three_doors -q；预期旧逻辑因无条件下注失败。
- [ ] **Step 3: 最小实现。** 增加 refresh_frequency_analysis(site=None, target_period="") 与只读 frequency_analysis 属性，从已有 provider、配置和分析器生成/保存快照。三门处理及 _analyze_many 只消费 selected_plays、should_bet、reason；保持站点、期号、群组去重，且每个群组三门全部下注。
- [ ] **Step 4: 验证 GREEN。** 运行 python -m pytest tests/test_auto_bet_runtime.py -q，预期 PASS。
- [ ] **Step 5: 提交。** git add app/services/auto_bet_service.py tests/test_auto_bet_runtime.py；git commit -m "feat: gate dynamic three-door bets by frequency confidence"。

### Task 4: 在自动下注面板展示完整概率快照

**Files:**
- Modify: app/ui/auto_bet_panel.py
- Modify: tests/test_auto_bet_runtime.py

- [ ] **Step 1: 写入失败测试。** 构造分析快照并调用 panel.update_frequency_analysis(analysis)，断言标签包含实际样本、13/14、八种玩法、排除项、三个下注玩法、阈值和本期将下注/不下注。
- [ ] **Step 2: 验证 RED。** 运行 python -m pytest tests/test_auto_bet_runtime.py -k frequency_probabilities -q；预期面板 API 不存在失败。
- [ ] **Step 3: 最小实现。** 在实战统计前加入只读 QGroupBox("概率分析") 和 update_frequency_analysis()。固定显示站点、目标期、更新时间、配置/实际样本、13/14、八种玩法、三门排除/保留、阈值、最高概率和状态。None 显示“暂无可用历史概率分析”；所有外部文本先转义或使用纯文本。
- [ ] **Step 4: 验证 GREEN。** 运行 python -m pytest tests/test_auto_bet_runtime.py -q，预期 PASS。
- [ ] **Step 5: 提交。** git add app/ui/auto_bet_panel.py tests/test_auto_bet_runtime.py；git commit -m "feat: show frequency probabilities in auto-bet panel"。

### Task 5: 接入主窗口刷新生命周期

**Files:**
- Modify: app/ui/main_window_data.py
- Modify: app/ui/main_window_realtime.py
- Modify: tests/test_draw_result_provider.py

- [ ] **Step 1: 写入失败测试。** 测试 _refresh_auto_bet_frequency_analysis() 在服务未运行时可把已有缓存快照交给面板；测试 _on_auto_bet_tick() 在 service.tick() 后发布新快照。
- [ ] **Step 2: 验证 RED。** 运行 python -m pytest tests/test_draw_result_provider.py -k frequency_analysis -q；预期刷新钩子缺失。
- [ ] **Step 3: 最小实现。** 实现 _refresh_auto_bet_frequency_analysis(site, target_period="")，仅当服务已有历史 provider 时计算并更新面板。自动下注在完成缓存初始化后调用一次；自动期处理后发布快照；站点切换和已有刷新路径更新展示。停止时不新增计时器或网络请求，只响应已有站点切换、手动刷新、开奖刷新事件。
- [ ] **Step 4: 验证 GREEN。** 运行 python -m pytest tests/test_draw_result_provider.py tests/test_auto_bet_runtime.py tests/test_history_records.py -q，预期 PASS。
- [ ] **Step 5: 提交。** git add app/ui/main_window_data.py app/ui/main_window_realtime.py tests/test_draw_result_provider.py；git commit -m "feat: refresh auto-bet frequency analysis with draw updates"。

### Task 6: 文档与最终验证

**Files:**
- Modify: README.md
- Modify: docs/ui_and_flow.md

- [ ] **Step 1: 更新文档。** 说明概率使用当前站点历史期数窗口；13/14 只展示；压三门排除最低复合玩法；任一保留门达到最低置信度后才同时下注三门。
- [ ] **Step 2: 运行完整测试。** python -m pytest -q；预期 PASS，无新增警告。
- [ ] **Step 3: 检查改动。** git diff --check；git status --short；预期无空白错误且不改动用户原有文件。
- [ ] **Step 4: 提交。** git add README.md docs/ui_and_flow.md；git commit -m "docs: describe frequency-based three-door betting"。
