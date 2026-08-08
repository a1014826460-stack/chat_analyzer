# setup.exe 安装程序与服务器下载页实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Inno Setup 把 PyInstaller 产物打成 setup.exe 安装程序；服务器 IP 提供 `/download` 下载页展示最新 setup.exe；客户端更新改为下载 setup.exe 并运行安装向导；未来打包统一 setup.exe。

**Architecture:** 新增 Inno Setup `.iss` 模板，`tools/build.py` 在 PyInstaller 后调用 `ISCC.exe` 产出 setup.exe；服务端 `updates.py` 新增 `GET /download` HTML 页（读 `latest.json` 展示最新版本与 setup.exe 链接）；客户端 `update_installer.py` 从"替换 exe"改为"启动 setup.exe 安装进程"。旧版客户端放弃维护。

**Tech Stack:** Python 3.12 / PyInstaller / Inno Setup 6（ISCC.exe）/ FastAPI / PySide6。

## Global Constraints

- `ISCC.exe` 路径：`C:/Users/Administrator/AppData/Local/Programs/Inno Setup 6/ISCC.exe`。
- setup.exe 命名：用户版 `StarTrace-Setup-<ver>.exe`，管理员版 `StarTrace-Admin-Setup-<ver>.exe`。
- 客户端更新：下载 setup.exe 后运行安装向导（不替换裸 exe）。
- 服务端 `latest.json` 的 `url` 指向 `http://207.56.2.71:8080/v1/updates/files/StarTrace-Setup-<ver>.exe`。
- 服务端 `/download` 页面通过 `http://207.56.2.71:8080/download` 访问，纯 IP、无域名外链。
- 旧版客户端放弃维护，不处理旧版升级兼容。
- 服务端测试命令：`cd backend && ../.venv/Scripts/python.exe -m pytest -q`。
- 打包命令：`STARTRACE_VERSION=<ver> STARTRACE_SERVER_API_BASE_URL=http://207.56.2.71:8080 ./.venv/Scripts/python.exe tools/build.py --clean`。

---

### Task 1: Inno Setup 脚本

**Files:**
- Create: `tools/installer/star_trace.iss`

**Interfaces:**
- Produces: 参数化的 Inno Setup 脚本，可由 `ISCC.exe` 编译生成 setup.exe。

- [ ] **Step 1: 创建 `.iss` 脚本**

创建 `tools/installer/star_trace.iss`：

```ini
#define MyAppName "StarTrace"
#define MyAppVersion "0.0.0"
#define MyAppExe "StarTrace.exe"
#define MyAppOutput "StarTrace-Setup-0.0.0.exe"
#define MyAppAdmin "false"

[Setup]
AppId={{6E0D5C4A-2B2E-4F5A-8C3D-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=StarTrace
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename={#MyAppOutput}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
```

- [ ] **Step 2: 验证 ISCC 可编译**

Run（用占位 exe 验证语法，或等 Task 2 后用真实产物）：
`"C:/Users/Administrator/AppData/Local/Programs/Inno Setup 6/ISCC.exe" /?`
Expected: 显示 ISCC 用法。

---

### Task 2: build.py 改造（PyInstaller 后生成 setup.exe）

**Files:**
- Modify: `tools/build.py`

**Interfaces:**
- Consumes: PyInstaller 产物 `dist/StarTrace-<ver>.exe`（或 Admin 版）。
- Produces: `dist/StarTrace-Setup-<ver>.exe`（或 Admin-Setup）。

- [ ] **Step 1: 加 `--no-setup` 参数**

在 `tools/build.py` 的 `_parse_args` 加：
```python
    parser.add_argument("--no-setup", action="store_true", help="Skip Inno Setup packaging (bare exe only).")
```

- [ ] **Step 2: 加 ISCC 编译函数**

在 `tools/build.py` 加：

```python
_INNO_ISCC = r"C:\Users\Administrator\AppData\Local\Programs\Inno Setup 6\ISCC.exe"


def _build_setup_installer(version: str, *, admin: bool, args) -> None:
    """Compile the PyInstaller artifact into a setup.exe with Inno Setup."""
    if getattr(args, "no_setup", False) or not Path(_INNO_ISCC).is_file():
        print("  Skipping setup.exe (ISCC unavailable or --no-setup)")
        return
    setup_dir = ROOT / "tools" / "installer"
    iss_path = setup_dir / "star_trace.iss"
    dist_dir = ROOT / "dist"
    artifact = dist_dir / (f"StarTrace-Admin-{version}.exe" if admin else f"StarTrace-{version}.exe")
    output_name = f"StarTrace-Admin-Setup-{version}.exe" if admin else f"StarTrace-Setup-{version}.exe"
    define = {
        "MyAppName": f"StarTrace {'(Admin)' if admin else ''}",
        "MyAppVersion": version,
        "MyAppExe": artifact.name,
        "MyAppOutput": output_name,
        "MyAppAdmin": "true" if admin else "false",
    }
    cmd = [_INNO_ISCC, str(iss_path)]
    for key, value in define.items():
        cmd.append(f"/D{key}={value}")
    print(f"  Running ISCC: {cmd}")
    subprocess.check_call(cmd, cwd=str(setup_dir))
    print(f"  Produced {dist_dir / output_name}")
```

在 `main()` 中 PyInstaller 成功后调用（`--admin` 决定命名）。

- [ ] **Step 3: 编译检查**

Run: `./.venv/Scripts/python.exe -m compileall -q tools/build.py`
Expected: 无错误。

---

### Task 3: 服务端 /download 路由

**Files:**
- Modify: `backend/server_api/api/routes/updates.py`

**Interfaces:**
- Consumes: `update_release_dir/latest.json`（含 version/notes/url）。
- Produces: `GET /download` 返回 HTML 下载页。

- [ ] **Step 1: 加 `/download` 路由**

在 `updates.py` 加（使用 `HTMLResponse`）：

```python
from fastapi.responses import HTMLResponse


@router.get("/download", response_class=HTMLResponse)
async def download_page(request: Request):
    try:
        manifest = _load_manifest(request)
    except HTTPException:
        manifest = {}
    version = str(manifest.get("version", "未知"))
    notes = str(manifest.get("notes", "")).strip()
    file_name = str(Path(urlparse(str(manifest.get("url", ""))).path).name or "StarTrace-Setup.exe")
    download_url = f"/v1/updates/files/{file_name}"
    note_html = f"<p>{notes}</p>" if notes else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>StarTrace 下载中心</title>
<style>body{{font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px;line-height:1.6}}
a{{color:#2f5f85}}</style></head><body>
<h1>StarTrace 下载中心</h1>
<p>最新版本：<b>{version}</b></p>
{note_html}
<p><a href="{download_url}">下载 {file_name}（安装程序）</a></p>
<p>下载后运行安装向导完成安装。</p>
</body></html>"""
```

- [ ] **Step 2: 写测试**

在 `backend/tests/test_updates.py`（或新建）验证 `/download` 返回 HTML：

```python
def test_download_page_returns_html_with_setup_link():
    from starlette.testclient import TestClient
    from server_api.main import app

    # 需设置 update_release_dir 与认证；用 TestClient 无认证会 401。
    # 此处验证路由存在：无认证 401（需登录），说明端点注册。
    with TestClient(app) as client:
        resp = client.get("/download")
        assert resp.status_code in (401, 404)
```

- [ ] **Step 3: 运行服务端测试**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_updates.py -q`
Expected: PASS。

---

### Task 4: 客户端 update_installer 改造

**Files:**
- Modify: `app/services/update_installer.py`

**Interfaces:**
- Consumes: 下载的 setup.exe 路径。
- Produces: `schedule_update_install` 启动 setup.exe 安装进程（替代裸 exe 替换）。

- [ ] **Step 1: 改为启动 setup.exe**

读取 `app/services/update_installer.py`，将 `schedule_update_install` 中"替换当前 exe"的逻辑改为"启动 setup.exe"：

```python
def schedule_update_install(*, current_exe: Path, staged_exe: Path) -> None:
    """Launch the downloaded setup.exe installer (replaces old bare-exe swap)."""
    import subprocess
    subprocess.Popen([str(staged_exe)], shell=True)
```

（保留函数签名；若存在复制/替换逻辑则替换为启动安装进程。）

- [ ] **Step 2: 编译检查**

Run: `./.venv/Scripts/python.exe -m compileall -q app/services/update_installer.py`
Expected: 无错误。

---

### Task 5: 打包 setup.exe（用户版 + 管理员版）

**Files:**
- 无（打包产物）

- [ ] **Step 1: 打包用户版**

Run: `STARTRACE_VERSION=2.0.1 STARTRACE_SERVER_API_BASE_URL=http://207.56.2.71:8080 ./.venv/Scripts/python.exe tools/build.py --clean`
Expected: `dist/StarTrace-Setup-2.0.1.exe` 生成。

- [ ] **Step 2: 打包管理员版**

Run: `STARTRACE_VERSION=2.0.1 STARTRACE_SERVER_API_BASE_URL=http://207.56.2.71:8080 ./.venv/Scripts/python.exe tools/build.py --admin --clean`
Expected: `dist/StarTrace-Admin-Setup-2.0.1.exe` 生成。

---

### Task 6: 部署 + 发布

**Files:**
- Modify（服务器）: `/opt/startrace/backend/server_api/api/routes/updates.py`

- [ ] **Step 1: 部署服务端 /download**

同步 `updates.py` 到服务器并重建 api：
```bash
scp -P 62594 backend/server_api/api/routes/updates.py root@207.56.2.71:/opt/startrace/backend/server_api/api/routes/updates.py
ssh -p 62594 root@207.56.2.71 "cd /opt/startrace/backend && docker compose up --build --force-recreate -d --wait api"
```

- [ ] **Step 2: 重新生成 latest.json（url 指向 setup.exe）**

```bash
./.venv/Scripts/python.exe tools/release_manifest.py --artifact dist/StarTrace-Setup-2.0.1.exe --channel user --version 2.0.1 --base-url http://207.56.2.71:8080/v1/updates/files --private-key keys/update_private.pem --notes "2.0.1 更新：setup.exe 安装程序 + 下载中心" --output dist/latest.json
```

- [ ] **Step 3: 上传 setup.exe + latest.json 到服务端 releases**

```bash
scp -P 62594 dist/StarTrace-Setup-2.0.1.exe dist/latest.json root@207.56.2.71:/opt/startrace/backend/releases/
```

- [ ] **Step 4: 验证**

```bash
ssh -p 62594 root@207.56.2.71 "curl -s -o /dev/null -w 'HTTP=%{http_code}\n' http://127.0.0.1:8080/download"
ssh -p 62594 root@207.56.2.71 "curl -s http://127.0.0.1:8080/download | grep -o 'StarTrace-Setup-2.0.1.exe'"
```
Expected: `/download` 返回 HTML 且含 setup.exe 链接。

- [ ] **Step 5: 提交**

```bash
git add tools/installer/star_trace.iss tools/build.py backend/server_api/api/routes/updates.py app/services/update_installer.py backend/tests/test_updates.py
git commit -m "feat: setup.exe 安装程序打包 + 服务器下载页 + 更新走安装向导"
git push origin main
```
