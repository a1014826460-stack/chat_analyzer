@echo off
setlocal EnableExtensions EnableDelayedExpansion

if exist "build_env.bat" call "build_env.bat"

if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /I "%%~A"=="STARTRACE_CDN_BASE_URL" set "STARTRACE_CDN_BASE_URL=%%~B"
        if /I "%%~A"=="STARTRACE_UPDATE_PUBLIC_KEY_PEM" set "STARTRACE_UPDATE_PUBLIC_KEY_PEM=%%~B"
    )
)

endlocal & (
    if defined STARTRACE_CDN_BASE_URL set "STARTRACE_CDN_BASE_URL=%STARTRACE_CDN_BASE_URL%"
    if defined STARTRACE_UPDATE_PUBLIC_KEY_PEM set "STARTRACE_UPDATE_PUBLIC_KEY_PEM=%STARTRACE_UPDATE_PUBLIC_KEY_PEM%"
)
