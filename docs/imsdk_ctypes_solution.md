# ImSDK.dll ctypes 消息发送方案

## 概述

通过 Python ctypes 直接加载 `ImSDK.dll`（腾讯云 IM SDK），调用其 C API 完成登录和消息发送。无需 WuQuan 客户端运行，独立进程完成所有操作。

## 架构

```
┌──────────────────────────────────────────┐
│           Python Process (StarTrace)      │
│                                          │
│  MessageInjector (ctypes)                │
│    ├─ TIMInit()      初始化 SDK          │
│    ├─ TIMLogin()     登录 IM             │
│    ├─ TIMMsgSendMessage()  发送消息      │
│    ├─ TIMLogout()    登出                │
│    └─ TIMUninit()    清理 SDK            │
│                                          │
│  Windows Message Pump (后台线程)          │
│    └─ PeekMessage / DispatchMessage      │
│       (驱动 SDK 异步回调)                 │
└──────────────────────────────────────────┘
         │
         ▼
   ImSDK.dll (腾讯云 IM SDK)
         │
         ▼
   腾讯云 IM 服务器 (adminapisgp.im.qcloud.com)
```

## 凭据获取

### UserSig 位置

`shared_preferences.json` → `AccountManager_AccountList` → `loginResultEntity.token`

### UserSig 格式

`token` 字段是 zlib 压缩 + 自定义 base64 编码的 JSON：

```json
{
  "TLS.ver": "2.0",
  "TLS.identifier": "x1DuArYgV",
  "TLS.sdkappid": "20011216",
  "TLS.expire": 1296000,
  "TLS.time": 1782555821,
  "TLS.sig": "Tp/0yvlBkLBkbUHsVpdB6uKZANf3X3iFVt4sJo05PhA="
}
```

### Base64 解码

自定义变体 → 标准 base64 映射：

| 自定义字符 | 标准字符 | 说明 |
|-----------|---------|------|
| `*` | `+` | 自定义变体 |
| `-` | `+` | URL-safe base64 变体 |
| `_` | `/` | URL-safe base64 变体 |

```python
std = token.replace('*', '+').replace('-', '+').replace('_', '/')
decoded = base64.b64decode(std + padding)
sig = json.loads(zlib.decompress(decoded, wbits=15))
```

### 用户 IM ID 查找

1. `AccountResolver` 解析账号 → 获取 `im.db` 路径
2. 在 `im.db` 的 `userinfo` 表中按昵称搜索
3. 或在 `groupmemberinfo` 表中按群组 + 名片搜索
4. 获取 `user_id`（如 `0p1e7eB8E`）作为消息目标

## API 函数签名

### TIMInit

```c
int TIMInit(uint64_t sdk_app_id, const char* json_sdk_config);
```

```python
dll.TIMInit(20011216, json.dumps({
    'sdk_config_file_path': r'path/to/data',
}).encode())
```

### TIMLogin

```c
int TIMLogin(const char* user_id, const char* user_sig,
             TIMCommCallback cb, const void* user_data);
```

- `user_id`: IM 用户 ID（accid）
- `user_sig`: zlib 压缩的 UserSig（token 原始值）
- 异步操作，结果通过回调返回

### TIMMsgSendMessage

```c
int TIMMsgSendMessage(const char* conv_id, int conv_type,
                      const char* json_msg_param, char* msg_id_buffer,
                      TIMCommCallback cb, const void* user_data);
```

- `conv_id`: 会话 ID（群 ID 或用户 ID）
- `conv_type`: 1=C2C, 2=Group
- `json_msg_param`: 消息 JSON

**消息 JSON 格式：**
```json
{
  "message_elem_array": [
    {
      "elem_type": 0,
      "text_elem_content": "消息文本内容"
    }
  ]
}
```

### 回调类型

```python
TIMCommCallback = CFUNCTYPE(None, c_int32, c_char_p, c_void_p)
# 参数: (int32 code, const char* desc, void* user_data)
# code=0 表示成功
```

## Windows 消息泵

**关键：SDK 的异步回调依赖 Windows 消息循环！** 必须在后台线程中运行消息泵：

```python
import ctypes.wintypes

user32 = ctypes.windll.user32
msg = ctypes.wintypes.MSG()

def pump():
    while running:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.05)
```

## 完整流程

```
1. TIMInit(sdk_app_id, config)
2. TIMLogin(accid, token_raw, callback)
3. 消息泵等待回调 code=0
4. TIMMsgSendMessage(target, conv_type, json, buffer, callback)
5. 消息泵等待回调 code=0
6. TIMLogout(callback)
7. TIMUninit()
```

## 注意事项

1. **不要与 WuQuan 同时登录同一账号** — 会导致 WuQuan 被踢下线
2. **消息泵必须持续运行** — 否则回调永远不会触发
3. **UserSig 有效期** — 通常 15 天，过期后需重新获取 token
4. **发送到群需是该群成员** — 否则返回 10007 错误
5. **C2C 发送需目标用户存在** — 否则返回 6032 错误
6. **回调函数必须保持引用** — 防止 Python GC 回收导致崩溃
