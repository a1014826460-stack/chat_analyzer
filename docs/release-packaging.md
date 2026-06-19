# StarTrace 打包与 CDN 更新说明

本文档说明：

1. 如何打包普通用户版和管理员版 exe
2. 如何生成 `latest.json`
3. 如何把新版本同步到 CDN / 网站静态目录
4. 如何验证客户端能自动更新

---

## 1. 打包命令

### 1.1 普通用户版

```powershell
.\.venv\Scripts\python.exe tools\build.py --clean
```

### 1.2 管理员版

```powershell
.\.venv\Scripts\python.exe tools\build.py --admin --clean
```

### 1.3 输出目录

打包完成后，exe 默认在：

```powershell
dist\
```

例如：

- `dist\StarTrace-1.97.0.exe`
- `dist\StarTrace-Admin-1.97.0.exe`

版本号来自：

- `app/build_config.py`
- 或环境变量 `STARTRACE_VERSION`

### 1.4 打包前的本地配置文件

现在 `build.bat`、`build_user.bat`、`build_admin.bat` 会自动按以下顺序读取本地配置：

1. `build_env.bat`
2. `.env`

推荐优先使用：

```text
build_env.bat
```

你可以直接复制：

```text
build_env.bat.example
```

然后改名为：

```text
build_env.bat
```

示例内容：

```bat
@echo off
set "STARTRACE_CDN_BASE_URL=https://www.twsaimahui.com"
set "STARTRACE_UPDATE_PUBLIC_KEY_PEM=-----BEGIN PUBLIC KEY-----你的更新公钥-----END PUBLIC KEY-----"
```

如果你更喜欢 `.env`，也可以写成：

```text
STARTRACE_CDN_BASE_URL=https://www.twsaimahui.com
STARTRACE_UPDATE_PUBLIC_KEY_PEM=-----BEGIN PUBLIC KEY-----你的更新公钥-----END PUBLIC KEY-----
```

---

## 2. 用户版推荐发布顺序

建议顺序：

1. 用 PyInstaller 打包普通用户版
2. 如需加壳，对用户版 exe 执行加壳
3. 对最终 exe 做签名（如果你有代码签名证书）
4. 生成 `latest.json`
5. 上传 exe 和 `latest.json` 到 CDN / 网站静态目录

---

## 3. 管理员版推荐发布顺序

建议顺序：

1. 用 PyInstaller 打包管理员版
2. 对 exe 做签名
3. 如需管理员版自动更新，再生成管理员版 `latest.json`
4. 上传 exe 和 `latest.json`

---

## 4. 用户版加壳

当前项目默认提供了一个轻量免费方案：`UPX`。

注意：

- `UPX` 更偏向压缩/轻量保护，不是强对抗级防逆向方案
- 如果客户机器上出现杀毒误报、启动异常、白屏或闪退，建议先取消 `UPX`

执行命令：

```powershell
.\.venv\Scripts\python.exe tools\protect_with_upx.py dist\StarTrace-1.97.0.exe --backup
```

如果你最后发布的是加壳后的 exe，那么后续生成 `latest.json` 时，`--artifact` 必须指向“最终实际给客户下载的 exe”。

---

## 5. 生成 latest.json

`latest.json` 是客户端自动更新读取的更新清单。

生成命令示例：

```powershell
.\.venv\Scripts\python.exe tools\release_manifest.py `
  --artifact dist\StarTrace-1.97.0.exe `
  --channel user `
  --version 1.97.0 `
  --base-url https://www.twsaimahui.com/startrace/user `
  --private-key C:\keys\update_private.pem `
  --notes "修复回执群统计与自动更新" `
  --output dist\latest.json
```

### 参数说明

- `--artifact`
  你的最终发布 exe 路径
- `--channel`
  `user` 或 `admin`
- `--version`
  当前版本号
- `--base-url`
  该版本 exe 所在的 CDN 目录 URL，不是 `latest.json` 文件本身
- `--private-key`
  更新签名私钥 PEM 文件路径
- `--notes`
  更新说明
- `--output`
  直接输出为 `latest.json`

### 管理员版示例

```powershell
.\.venv\Scripts\python.exe tools\release_manifest.py `
  --artifact dist\StarTrace-Admin-1.97.0.exe `
  --channel admin `
  --version 1.97.0 `
  --base-url https://www.twsaimahui.com/startrace/admin `
  --private-key C:\keys\update_private.pem `
  --notes "管理员版更新" `
  --output dist\latest-admin.json
```

---

## 6. CDN / 网站目录结构

客户端默认按下面路径取更新：

### 用户版

- `${CDN_BASE_URL}/startrace/user/latest.json`
- `${CDN_BASE_URL}/startrace/user/StarTrace-<version>.exe`

### 管理员版

- `${CDN_BASE_URL}/startrace/admin/latest.json`
- `${CDN_BASE_URL}/startrace/admin/StarTrace-Admin-<version>.exe`

如果你当前使用的是：

- 域名：`https://www.twsaimahui.com`

那么用户版示例路径就是：

- `https://www.twsaimahui.com/startrace/user/latest.json`
- `https://www.twsaimahui.com/startrace/user/StarTrace-1.97.0.exe`

---

## 7. 如何同步到 CDN / 网站静态目录

你现在这种模式，本质上不需要专门的 CDN 控制台也能做。
只要你的站点目录能通过域名访问到静态文件即可。

### 7.1 需要上传的文件

以用户版 `1.97.0` 为例，只需要上传这两个文件：

1. `dist\StarTrace-1.97.0.exe`
2. `dist\latest.json`

### 7.2 服务器目标目录

如果你的网站根目录下已经允许放静态文件，那么目标目录应该是：

```text
/网站根目录/startrace/user/
```

最终线上要变成：

```text
/网站根目录/startrace/user/latest.json
/网站根目录/startrace/user/StarTrace-1.97.0.exe
```

### 7.3 用 SCP 上传

你可以在本机 PowerShell 执行：

```powershell
scp -P 29618 dist\StarTrace-1.97.0.exe root@207.56.3.82:/网站根目录/startrace/user/StarTrace-1.97.0.exe
scp -P 29618 dist\latest.json root@207.56.3.82:/网站根目录/startrace/user/latest.json
```

如果你知道真实网站根目录，比如是：

- `/www/wwwroot/www.twsaimahui.com`

那么命令可以写成：

```powershell
scp -P 29618 dist\StarTrace-1.97.0.exe root@207.56.3.82:/www/wwwroot/www.twsaimahui.com/startrace/user/StarTrace-1.97.0.exe
scp -P 29618 dist\latest.json root@207.56.3.82:/www/wwwroot/www.twsaimahui.com/startrace/user/latest.json
```

### 7.4 先创建目录

如果服务器上还没有该目录，先登录服务器创建：

```bash
mkdir -p /www/wwwroot/www.twsaimahui.com/startrace/user
```

管理员版同理：

```bash
mkdir -p /www/wwwroot/www.twsaimahui.com/startrace/admin
```

---

## 8. 客户端如何自动更新

程序启动后会：

1. 读取当前版本号
2. 请求对应渠道的 `latest.json`
3. 校验签名
4. 比较版本号
5. 下载对应 exe
6. 校验 SHA-256
7. 弹窗提示安装
8. 退出旧版本并替换 exe
9. 自动重启

如果程序当前是开发模式运行，也就是你用：

```powershell
.\.venv\Scripts\python.exe app\main.py
```

那么它不会真的替换 `python.exe`，只会下载并提示路径。

真正自动替换只会发生在打包后的 exe 版本里。

---

## 9. 发布后如何验证

建议按下面顺序验证：

1. 先本地打包出新 exe
2. 用 `release_manifest.py` 生成 `latest.json`
3. 把 exe 和 `latest.json` 上传到线上目录
4. 浏览器直接访问：
   - `https://www.twsaimahui.com/startrace/user/latest.json`
   - `https://www.twsaimahui.com/startrace/user/StarTrace-1.97.0.exe`
5. 确认两个地址都能正常打开/下载
6. 在一台旧版本客户端上启动程序
7. 确认出现更新提示
8. 确认下载成功、校验成功、替换成功、自动重启成功

---

## 10. 你现在最常用的一套命令

### 打包普通用户版

```powershell
.\.venv\Scripts\python.exe tools\build.py --clean
```

### 生成用户版 latest.json

```powershell
.\.venv\Scripts\python.exe tools\release_manifest.py `
  --artifact dist\StarTrace-1.97.0.exe `
  --channel user `
  --version 1.97.0 `
  --base-url https://www.twsaimahui.com/startrace/user `
  --private-key C:\keys\update_private.pem `
  --notes "本次更新说明" `
  --output dist\latest.json
```

### 上传到服务器

```powershell
scp -P 29618 dist\StarTrace-1.97.0.exe root@207.56.3.82:/www/wwwroot/www.twsaimahui.com/startrace/user/StarTrace-1.97.0.exe
scp -P 29618 dist\latest.json root@207.56.3.82:/www/wwwroot/www.twsaimahui.com/startrace/user/latest.json
```

---

## 11. 注意事项

- `latest.json` 里的 `version` 必须高于客户端当前版本，否则不会提示更新
- `latest.json` 里的下载地址必须和实际上传的 exe 文件名一致
- 如果你重新加壳、重新签名、重新打包，必须重新生成 `latest.json`
- 绝对不要把更新私钥放进用户版程序
- 如果访问的是域名路径，就说明你的“CDN”在这里可以直接理解为“域名可访问的静态文件目录”
