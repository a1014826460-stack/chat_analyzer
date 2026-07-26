from __future__ import annotations

# 管理员版本：构建时由 build_admin.bat 设为 True，包含激活码生成等管理功能。
IS_ADMIN_VERSION = False

# 生产版本：构建时由构建脚本设为 True。
# 为 True 时：强制激活检查、启用保护壳、隔离生产配置路径。
# 为 False 时：跳过激活、跳过保护壳、使用开发配置路径（开发调试用）。
IS_PRODUCTION = False

# 发布版本标识：每次正式打包由构建脚本注入，用于隔离用户数据和激活状态。
BUILD_ID = ""
