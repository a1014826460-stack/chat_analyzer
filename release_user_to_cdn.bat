@echo off
cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\release_user_to_cdn.ps1"
exit /b %ERRORLEVEL%
