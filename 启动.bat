@echo off
rem ============================================================
rem  GPW Battery —— 启动脚本（无控制台窗口）
rem  直接双击本文件即可运行；如需开机自启，右键托盘图标勾选。
rem ============================================================
setlocal
set "HERE=%~dp0"

set "PYW="
for %%P in (pythonw.exe) do if not defined PYW if exist "%%~$PATH:P" set "PYW=%%~$PATH:P"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if not defined PYW if exist "C:\Users\youyou\.workbuddy-ai\binaries\python\versions\3.13.12\pythonw.exe" set "PYW=C:\Users\youyou\.workbuddy-ai\binaries\python\versions\3.13.12\pythonw.exe"

if not defined PYW (
    echo [错误] 没有找到 pythonw.exe
    echo 请先安装 Python 3.9 或更高版本，或用记事本修改本文件里的路径。
    pause
    exit /b 1
)

start "" "%PYW%" "%HERE%gpw_battery.py"
exit /b 0
