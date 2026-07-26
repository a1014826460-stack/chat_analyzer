# SQLite 消息读取与加密恢复状态

## 当前实现

StarTrace 通过 `app/services/account_resolver.py` 定位聊天客户端账号和本地消息数据库，再由 `app/services/chat_service.py` 读取 SQLite 消息记录。消息解析支持文本字段、结构化消息描述和可恢复的 JSON 文本；解析后的记录进入筛选、下注事件识别和统计流程。

## 使用入口

- `AccountResolver.resolve(username)`：根据账号解析本地配置、IM 数据库和消息数据库。
- `ChatLogService.load_messages(...)`：按 `ParseOptions` 读取和过滤消息。
- `ChatLogService.extract_bet_visual_data(...)`：将消息解析为可视化下注事件。

## 已知限制

本仓库未保存一份可独立复现的 SQLite 加密密钥派生说明。若某个客户端数据库无法直接读取，应用会保留诊断信息而不是尝试修改源数据库。历史恢复材料保存在：

`docs/archive/recovery/corrupted_docs_data_20260610_0215/`

其中内容仅用于追溯，不作为当前实现或密钥配置的来源。
