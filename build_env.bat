@echo off
rem StarTrace 本地发布配置
rem 该文件会被 build.bat / build_user.bat / build_admin.bat 自动读取
rem 对应更新私钥文件路径：keys\update_private.pem

rem 发布版本号
set "STARTRACE_VERSION=1.99.1"

rem 构建编号，可按日期或批次递增
set "STARTRACE_BUILD_ID=startrace_202606200001"

rem 在线更新地址根域名
set "STARTRACE_CDN_BASE_URL=https://www.twsaimahui.com"

rem 更新公钥，客户端用它验证 latest.json 的签名
set "STARTRACE_UPDATE_PUBLIC_KEY_PEM=-----BEGIN PUBLIC KEY-----MCowBQYDK2VwAyEAYbaOBamAggVGjyvskyeekFIj4GPHGJq97IuRhhBrNGE=-----END PUBLIC KEY-----"
