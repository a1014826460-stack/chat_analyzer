# setup.exe 安装程序与服务器下载页设计

日期：2026-08-09
状态：待用户审阅

## 背景与目标

当前打包方式为 PyInstaller `--onefile` 生成**裸 exe**（用户版/管理员版），无安装程序。用户要求：

1. **打包为 setup.exe 安装程序**（带安装向导、快捷方式、卸载项）。
2. **服务器 IP 提供 download 页面**（`http://207.56.2.71:8080/download`），展示最新版 setup.exe 下载链接。
3. **客户端保持更新弹窗**（不新增客户端下载模块）：检测到新版本 → 下载 setup.exe → 运行安装向导。
4. **未来所有打包统一产出 setup.exe**。

## 已确认的需求决策

| 决策点 | 选择 |
| --- | --- |
| download 页面位置 | 服务器 IP 的 `/download` 页面（非客户端模块） |
| setup.exe 打包工具 | Inno Setup 6（需先安装到打包机 Windows） |
| 自动更新方式 | 客户端下载 setup.exe 后运行安装向导 |
| 客户端下载模块 | 不新增，保持现有更新弹窗 |
| 未来打包 | 用户版/管理员版统一产出 setup.exe |

## 现有代码定位

- 打包：`tools/build.py`（PyInstaller `--onefile`，产物 `dist/StarTrace-<ver>.exe`）。
- 客户端更新：`app/ui/main_window.py`（`_check_for_updates_async` → 弹窗 → `_download_update_worker` → `schedule_update_install`）；`app/services/update_service.py`（`download_server_artifact` 从服务端 `/v1/updates/files/` 下载）；`app/services/update_installer.py`（裸 exe 替换）。
- 服务端更新：`backend/server_api/api/routes/updates.py`（`/v1/updates/manifest` 读 `update_release_dir/latest.json`；`/v1/updates/files/{name}` 返回文件）；`update_release_dir=/srv/startrace/releases`（宿主 `/opt/startrace/backend/releases`）。
- 发布：`tools/release_manifest.py`（生成 latest.json）、`release_user_config.bat/ps1`（CDN base url 已改纯 IP）。

## 设计

### 1. 安装 Inno Setup 6

- 从官方（https://jrsoftware.org/isinfo.php）下载安装 **Inno Setup 6** 到打包机 Windows。
- 记录 `ISCC.exe` 路径（默认 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`）。

### 2. 打包流水线改造（`tools/build.py` + 新增 `.iss`）

流程：`PyInstaller 生成 exe → ISCC 编译 .iss → setup.exe`

| 版本 | PyInstaller 产物 | setup.exe 产物 |
| --- | --- | --- |
| 用户版 | `StarTrace-2.0.1.exe` | `StarTrace-Setup-2.0.1.exe` |
| 管理员版 | `StarTrace-Admin-2.0.1.exe` | `StarTrace-Admin-Setup-2.0.1.exe` |

新增 Inno Setup 脚本（`tools/installer/star_trace.iss` 模板，按版本/管理员版参数化）：
- 应用名：`StarTrace`（管理员版加 ` (Admin)`）。
- 版本：`{APP_VERSION}`。
- 安装目录：`{autopf}\StarTrace`（Program Files）。
- 开始菜单快捷方式、卸载项、桌面快捷方式（可选）。
- 编译输入：PyInstaller 生成的 exe。

`tools/build.py` 在 PyInstaller 成功后调用 `ISCC.exe` 编译，产出 setup.exe 到 `dist/`。

### 3. 服务器 download 页面（IP 访问）

- `backend/server_api/api/routes/updates.py` 新增 `GET /download` 路由，返回 HTML 页面：
  - 页面标题：StarTrace 下载中心。
  - 展示最新版本（读 `update_release_dir/latest.json`）、版本说明。
  - setup.exe 下载链接：`/v1/updates/files/StarTrace-Setup-<version>.exe`。
  - 说明文字（纯 IP 访问，无外链域名）。
- 通过 `http://207.56.2.71:8080/download` 访问。

### 4. 客户端更新链路改造

- 保持更新弹窗（`_check_for_updates_async` 现有流程）。
- `update_installer.py`：从"裸 exe 替换"改为"**启动 setup.exe 安装进程**"（`subprocess` 打开 setup.exe，用户走安装向导完成安装）。setup.exe 安装完成后，旧 exe 由安装程序处理退出/替换。
- `latest.json` 的 `url` 指向 `StarTrace-Setup-<version>.exe`（`http://207.56.2.71:8080/v1/updates/files/StarTrace-Setup-2.0.1.exe`）。

### 5. 发布

- 上传 `StarTrace-Setup-2.0.1.exe` + `latest.json` 到服务端 releases（`/opt/startrace/backend/releases/`）。
- 客户端自动更新：检测 2.0.1 → 下载 setup.exe → 运行安装向导。
- 服务器 `/download` 页面展示最新 setup.exe 下载链接。

### 6. 未来打包

- `tools/build.py` 默认产出 setup.exe（用户版/管理员版），手动分发与自动更新统一用安装包。

## 迁移与测试

- **服务端**：`/download` 路由返回 HTML 且包含正确 setup.exe 链接；`/v1/updates/manifest` 的 url 指向 setup.exe。
- **客户端**：`update_installer` 改为启动 setup.exe（测试 `schedule_update_install` 调用 `subprocess` 打开安装包）；更新下载仍是 `download_server_artifact`（文件名从 url 取）。
- **打包**：`tools/build.py` 产出 setup.exe；用 `ISCC.exe` 编译成功。

## 部署

```bash
# 服务端
scp dist/StarTrace-Setup-2.0.1.exe dist/latest.json root@207.56.2.71:/opt/startrace/backend/releases/
cd /opt/startrace/backend && docker compose up --build --force-recreate -d --wait api
```

## 兼容与回滚

- 客户端旧版本（1.97.0/1.99.8）更新到 setup.exe 版：需确认 update_installer 对 setup.exe 的处理（旧版 exe 替换逻辑与新 setup 安装不冲突）。
- 若 Inno Setup 不可用，保留 PyInstaller 裸 exe 产物作为回退（build.py 增加 `--no-setup` 开关）。
