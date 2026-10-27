@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON_COMMAND="

where python >nul 2>nul
if not errorlevel 1 set "PYTHON_COMMAND=python"
if defined PYTHON_COMMAND goto run

where python3 >nul 2>nul
if not errorlevel 1 set "PYTHON_COMMAND=python3"
if defined PYTHON_COMMAND goto run

set "HOOK_EVENT="
set "EXPECT_HOOK_EVENT="
for %%A in (%*) do (
    if defined EXPECT_HOOK_EVENT (
        set "HOOK_EVENT=%%~A"
        goto warn
    )
    if "%%~A"=="--hook-event" set "EXPECT_HOOK_EVENT=1"
)

:warn
set "MESSAGE=Wttch \u63d2\u4ef6\u672a\u8fd0\u884c\uff1a\u672c\u673a\u672a\u5b89\u88c5 Python\uff0c\u6216 Python \u672a\u52a0\u5165 PATH\u3002\u8bf7\u63d0\u793a\u7528\u6237\u5b89\u88c5 Python \u5e76\u5c06\u5176\u52a0\u5165 PATH \u540e\u91cd\u8bd5\u3002"
if defined HOOK_EVENT (
    echo {"hookSpecificOutput":{"hookEventName":"%HOOK_EVENT%","additionalContext":"%MESSAGE%"}}
) else (
    >&2 echo WARNING: %MESSAGE%
)
exit /b 0

:prepare
if not exist "%SCRIPT_DIR%runner.py" goto run
"%PYTHON_COMMAND%" "%SCRIPT_DIR%runner.py" --mode prepare >nul 2>nul
if not errorlevel 1 goto run
set "MESSAGE=Wttch \u63d2\u4ef6\u672a\u8fd0\u884c\uff1a\u63d2\u4ef6\u865a\u62df\u73af\u5883\u51c6\u5907\u5931\u8d25\u3002\u8bf7\u63d0\u793a\u7528\u6237\u68c0\u67e5 Python \u7684 venv \u7ec4\u4ef6\u3001\u7f51\u7edc\u8fde\u63a5\u548c\u4f9d\u8d56\u5b89\u88c5\u540e\u91cd\u8bd5\u3002"
goto warn

:run
"%PYTHON_COMMAND%" "%SCRIPT_DIR%runner.py" %*
exit /b %ERRORLEVEL%
