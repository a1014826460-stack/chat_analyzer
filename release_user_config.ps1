# StarTrace user release config.
# Admin usually only edits these two values.

$Version = "1.99.1"
$Notes = "1.99.1 更新：增强激活码验证机制，普通用户版需激活码运行，管理员版生成器新增复制激活码按钮"

# Usually unchanged unless server, path, or domain changes.
$Channel = "user"
$CdnBaseUrl = "https://www.twsaimahui.com/startrace/user"
$PrivateKey = "keys\update_private.pem"
$SshHost = "root@207.56.3.82"
$SshPort = "29618"
$RemoteDir = "/root/Marksix/deploy/startrace/user"
