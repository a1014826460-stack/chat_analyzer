@echo off
rem StarTrace user release config.
rem Admin usually only edits the first two values: version and notes.

set "STARTRACE_RELEASE_VERSION=1.99.7"
set "STARTRACE_RELEASE_NOTES=1.99.6 更新：自动下注使用下期期号，AI 历史数据严格过滤目标期及未来期"

rem Usually unchanged unless server, path, or domain changes.
set "STARTRACE_RELEASE_CHANNEL=user"
set "STARTRACE_RELEASE_CDN_BASE_URL=https://www.twsaimahui.com/startrace/user"
set "STARTRACE_RELEASE_PRIVATE_KEY=keys\update_private.pem"
set "STARTRACE_RELEASE_SSH_HOST=root@207.56.3.82"
set "STARTRACE_RELEASE_SSH_PORT=29618"
set "STARTRACE_RELEASE_REMOTE_DIR=/root/Marksix/deploy/startrace/user"
