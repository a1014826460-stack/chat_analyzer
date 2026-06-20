# StarTrace 聊天分析器

用于加载聊天记录、过滤屏蔽用户、统计下注消息的桌面应用。

## 1. 环境准备

先创建或刷新本地虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. 本地运行

管理员模式调试启动：

```powershell
.\.venv\Scripts\python.exe app\main.py --admin --debug
```

普通用户模式启动：

```powershell
.\.venv\Scripts\python.exe app\main.py
```

## 3. 打包 EXE

### 普通用户版

```powershell
.\.venv\Scripts\python.exe tools\build.py --clean
```

也可以直接双击：

```powershell
build.bat
```

如果需要让打包后的程序自带在线更新地址和更新公钥读取能力，可以在项目根目录放以下任一种本地配置文件：

- `build_env.bat`
- `.env`

### 管理员版

```powershell
.\.venv\Scripts\python.exe tools\build.py --admin --clean
```

也可以直接双击：

```powershell
build_admin.bat
```

### 打包输出位置

打包完成后，生成的 exe 在：

```powershell
dist\
```

文件名由 `app/build_config.py` 中的版本号决定，例如：

- `dist\StarTrace-1.97.0.exe`
- `dist\StarTrace-Admin-1.97.0.exe`

### 本地构建配置示例

推荐做法：

1. 复制 `build_env.bat.example`
2. 重命名为 `build_env.bat`
3. 填入你自己的值

示例：

```bat
set "STARTRACE_CDN_BASE_URL=https://www.twsaimahui.com"
set "STARTRACE_UPDATE_PUBLIC_KEY_PEM=-----BEGIN PUBLIC KEY-----你的更新公钥-----END PUBLIC KEY-----"
```

## 4. 在线更新机制

程序启动后会自动检查更新。

更新地址来自：

- `app/build_config.py`
- 环境变量 `STARTRACE_CDN_BASE_URL`

要让客户端真正执行在线更新检查，还需要在运行或打包环境里提供：

- `STARTRACE_CDN_BASE_URL`
- `STARTRACE_UPDATE_PUBLIC_KEY_PEM`

程序会自动访问：

- 用户版：`{CDN_BASE_URL}/startrace/user/latest.json`
- 管理员版：`{CDN_BASE_URL}/startrace/admin/latest.json`

如果发现更高版本，会：

1. 下载新的 exe
2. 校验 `latest.json` 里的签名和 SHA-256
3. 弹窗提示安装
4. 退出旧程序
5. 用临时更新脚本替换 exe
6. 自动重启新版本

## 5. 如何打包并同步更新到 CDN

完整步骤请看：

- [docs/release-packaging.md](docs/release-packaging.md)

最短流程就是使用一键发布脚本：

```powershell
Copy-Item release_user_config.ps1.example release_user_config.ps1
notepad release_user_config.ps1
.\release_user_to_cdn.bat
```

管理员通常只需要在 `release_user_config.ps1` 里修改：

- `$Version`
- `$Notes`

脚本会自动：

1. 打包新的 exe
2. 生成新的 `latest.json`
3. 把 exe 上传到 CDN/网站静态目录
4. 把 `latest.json` 上传到对应目录

## 6. 当前项目说明

- 主打包方式仍然是 `PyInstaller`
- 用户版支持激活和离线使用
- 更新使用静态文件/CDN 模式，不依赖专用更新服务器
- 用户版更新清单和管理员版更新清单分开
