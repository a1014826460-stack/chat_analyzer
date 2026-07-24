@echo off
rem StarTrace user release config.
rem Admin usually only edits the first two values: version and notes.

set "STARTRACE_RELEASE_VERSION=1.99.8"
set "STARTRACE_RELEASE_NOTES=1.99.8 更新：PC28 新开奖源、历史条数按站点适配，实战统计改为三列布局"

rem Usually unchanged unless server, path, or domain changes.
set "STARTRACE_RELEASE_CHANNEL=user"
set "STARTRACE_RELEASE_CDN_BASE_URL=https://www.twsaimahui.com/startrace/user"
set "STARTRACE_RELEASE_PRIVATE_KEY=keys\update_private.pem"
set "STARTRACE_RELEASE_SSH_HOST=root@207.56.3.82"
set "STARTRACE_RELEASE_SSH_PORT=29618"
set "STARTRACE_RELEASE_REMOTE_DIR=/root/Marksix/deploy/startrace/user"
