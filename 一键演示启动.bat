@echo off
setlocal enabledelayedexpansion
title BID-Demo-Server
color 0A
set "PYTHONIOENCODING=gbk"
echo.
echo  ============================================
echo       智能投标辅助平台 - 一键演示启动
echo  ============================================
echo.

:: --- 1. 定位项目根目录并切换（A: 管理员运行时 cwd 可能是 System32）---
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "PORT=8000"
set "APP_PID="
set "SYS_PY_FOUND="

:: --- 2. 无条件调用 start.ps1 确保依赖就绪（F: 幂等自愈）---
echo [准备] 检查运行环境与依赖...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start.ps1" -InstallDependencies -InstallOnly -Quiet
set "PS_RC=!errorlevel!"
:: E: 按退出码分流
if "!PS_RC!"=="2" goto :no_python
if "!PS_RC!"=="3" goto :wrong_python_version
if not "!PS_RC!"=="0" goto :dep_fail
echo [完成] 运行环境就绪。
echo.

:: --- 3. 确认虚拟环境存在 ---
if not exist "%VENV_PY%" (
    echo [错误] 虚拟环境异常，找不到：
    echo        %VENV_PY%
    echo        请删除 .venv 文件夹后重新双击本脚本。
    goto :fail
)

:: --- 4. 检查端口占用，自动回退（G: bind 试探 + 随机兜底）---
call :check_port 8000
if !PORT_OK!==1 goto :port_ready
echo [提示] 端口 8000 不可用，尝试 8080...
call :check_port 8080
if !PORT_OK!==1 goto :port_ready
echo [提示] 端口 8080 不可用，尝试 9000...
call :check_port 9000
if !PORT_OK!==1 goto :port_ready
echo [提示] 常用端口均不可用，尝试随机端口...
set /a "TRY_COUNT=0"
:random_port
set /a "TRY_COUNT+=1"
if !TRY_COUNT! GTR 10 goto :all_ports_fail
set /a "PORT=10000 + (!RANDOM! %% 10000)"
call :check_port !PORT!
if !PORT_OK!==1 goto :port_ready
goto :random_port

:all_ports_fail
echo.
echo [错误] 无法找到可用端口。
echo        请关闭占用端口的程序，或重启电脑后重试。
echo        如仍无法解决，请联系运维人员。
goto :fail

:port_ready
set "URL=http://127.0.0.1:!PORT!"

:: --- 5. 设置环境变量 ---
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "BID_PORT=!PORT!"
if not defined BID_DATA_DIR set "BID_DATA_DIR=%ROOT%data"

:: --- 6. 启动服务（D: 通过 Start-Process 获取真实 PID）---
echo [启动] 正在启动本地服务，端口 !PORT! ...
powershell.exe -NoProfile -Command "$p=(Start-Process -FilePath $env:VENV_PY -ArgumentList '-m','app' -WorkingDirectory $env:ROOT -WindowStyle Hidden -PassThru).Id; [IO.File]::WriteAllText((Join-Path $env:ROOT '_pid.tmp'),[string]$p)"
if exist "%ROOT%_pid.tmp" (
    set /p APP_PID=<"%ROOT%_pid.tmp"
    del "%ROOT%_pid.tmp" >nul 2>&1
)
if not defined APP_PID (
    echo [错误] 服务进程启动失败，无法获取进程ID。
    echo        请尝试删除 .venv 文件夹后重新双击本脚本。
    goto :fail
)

:: --- 7. 等待服务就绪（H: 单次PS调用，30秒上限，含进程存活检测）---
echo [等待] 服务初始化中，请稍候（最多30秒）...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(30); $ok=$false; $procId=0; [void][int]::TryParse($env:APP_PID,[ref]$procId); while((Get-Date) -lt $deadline){ try{ $r=Invoke-WebRequest -Uri ('http://127.0.0.1:'+$env:BID_PORT+'/api/health') -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){$ok=$true;break} }catch{}; if($procId -gt 0){ $alive=Get-Process -Id $procId -ErrorAction SilentlyContinue; if(-not $alive){break} }; Start-Sleep -Seconds 1 }; if($ok){exit 0}else{exit 1}"
if !errorlevel!==0 goto :ready

:: 健康检查失败：判断进程是否已退出
tasklist /fi "PID eq !APP_PID!" 2>nul | find "!APP_PID!" >nul
if !errorlevel! NEQ 0 (
    echo.
    echo [错误] 服务进程已意外退出（PID: !APP_PID!）。
    if exist "%ROOT%data\server.log" (
        echo.
        echo --- 服务日志末尾 ---
        powershell -NoProfile -Command "if(Test-Path '%ROOT%data\server.log'){Get-Content '%ROOT%data\server.log' -Tail 10}"
        echo --- 日志结束 ---
    )
    echo.
    echo 常见原因：端口被占用、依赖不完整、数据目录无写入权限。
    echo 解决办法：删除 .venv 文件夹后重新双击本脚本。
    goto :fail
)
goto :timeout_err

:: --- 8. 服务就绪 ---
:ready
echo.
echo  ============================================
echo  [OK] 服务已就绪，正在为您打开浏览器...
echo  ============================================
echo.
echo     访问地址：!URL!
echo     数据目录：!BID_DATA_DIR!
echo.
echo  若浏览器未自动打开，请手动复制上面的地址到浏览器。
echo.
echo  --------------------------------------------
echo  演示说明（L: 准确描述）：
echo    - 演示期间请勿关闭此黑色窗口，否则服务会中断
echo    - 结束后请回到本窗口按任意键正常停止服务
echo    - 按任意键 = 停止服务并关闭窗口
echo  --------------------------------------------
echo.
color 0B
start "" "!URL!"
timeout /t 3 /nobreak >nul 2>&1 || ping -n 4 127.0.0.1 >nul

:: --- 9. 保持窗口活跃 ---
:runloop
echo [%date% %time%] 服务运行中... 按任意键停止并关闭窗口
pause >nul
echo 正在停止服务...
call :kill_app
echo 已停止。感谢使用。
ping -n 3 127.0.0.1 >nul
endlocal
exit /b 0

:: ============ 错误处理 ============

:timeout_err
color 0E
echo.
echo  [错误] 服务启动超时（30秒内未就绪）。
echo.
echo  常见原因及解决办法：
echo     - 端口被其他程序占用 - 重启电脑后重试
echo     - 数据目录无写入权限 - 右键"以管理员身份运行"
echo     - 依赖不完整 - 删除 .venv 文件夹后重新双击本脚本
echo.
echo  也可尝试手动在浏览器打开 !URL! 看是否已可用
echo.
call :kill_app
goto :fail

:no_python
color 0C
echo.
echo  +==========================================+
echo     [错误] 本机未安装Python，无法启动
echo  +==========================================+
echo.
echo  本软件需要 Python 3.10 ~ 3.13（推荐 3.12）
echo.
echo  请按以下步骤安装 Python（只需安装一次）：
echo.
echo  方法一（推荐）：
echo     按 Win+R 输入 powershell 回车，然后复制粘贴：
echo.
echo     winget install -e --id Python.Python.3.12
echo.
echo     若提示"winget 不是内部或外部命令"或"无法识别为 cmdlet"，
echo     说明系统较老不支持 winget，请改用方法二。
echo     若提示需要管理员权限，请右键"以管理员身份运行"PowerShell再试。
echo.
echo  方法二：
echo     浏览器打开下面的网址，点击下载安装：
echo.
echo     https://www.python.org/downloads/
echo.
echo  *** 安装时务必勾选 "Add python.exe to PATH" ***
echo  （安装界面最下方的复选框，非常重要）
echo.
echo  --------------------------------------------
echo  如何确认安装成功：
echo     1. 安装完成后，关闭当前 PowerShell 窗口
echo     2. 重新按 Win+R 输入 powershell 回车（必须打开新的）
echo     3. 输入 python --version 回车
echo     4. 若显示 Python 3.12.x 即成功
echo     5. 若提示"不是内部或外部命令"，说明安装时没勾PATH，
echo        需要重新安装并勾选 "Add python.exe to PATH"
echo  --------------------------------------------
echo.
echo  确认安装成功后，重新双击本脚本即可启动。
echo.
goto :fail

:wrong_python_version
color 0E
echo.
echo  +==========================================+
echo     [错误] Python版本不符，无法启动
echo  +==========================================+
echo.
echo  检测到本机已安装 Python，但版本不在支持范围内。
echo  本软件需要 Python 3.10 ~ 3.13（推荐 3.12）。
echo.
echo  解决办法：安装 Python 3.12
echo     按 Win+R 输入 powershell 回车，复制粘贴：
echo.
echo     winget install -e --id Python.Python.3.12
echo.
echo     或从官网下载：https://www.python.org/downloads/
echo     安装时务必勾选 "Add python.exe to PATH"
echo.
echo  如何确认安装成功：
echo     1. 关闭当前 PowerShell，重新按 Win+R 输入 powershell 回车
echo     2. 输入 python --version 回车
echo     3. 显示 Python 3.12.x 即成功
echo.
echo  确认后重新双击本脚本即可。
echo.
goto :fail

:dep_fail
color 0C
echo.
echo  [错误] 依赖安装失败。常见原因：
echo     - 网络不通，无法下载依赖包
echo     - 杀毒软件拦截了安装过程
echo     - Python 版本不兼容（需要 3.10 ~ 3.13）
echo.
echo  解决办法：
echo     1. 确认电脑能上网
echo     2. 临时关闭杀毒软件的实时防护
echo     3. 删除 .venv 文件夹后重新双击本脚本
echo.
goto :fail

:fail
:: 防御性清理：防止 Start-Process 已拉起服务但 PID 回读失败时留下孤儿进程（幂等安全）
call :kill_app
echo.
color 0C
echo  --------------------------------------------
echo  程序未能正常启动，请根据上方提示排查问题。
echo  如仍无法解决，请截图此窗口发给技术支持。
echo  --------------------------------------------
echo.
echo  按任意键关闭窗口...
pause >nul
endlocal
exit /b 1

:: ============ 子过程 ============

:: D: 安全停止服务（按真实PID + 映像名校验 + 树杀）
:kill_app
if not defined APP_PID goto :kill_by_port
tasklist /fi "PID eq !APP_PID!" /fi "IMAGENAME eq python.exe" 2>nul | find "!APP_PID!" >nul
if !errorlevel!==0 (
    taskkill /f /t /pid !APP_PID!
) else (
    echo [提示] 服务进程已不在，未执行停止。
)
goto :eof

:: D: 兜底 - 按端口+映像名清理（APP_PID 未取到时）
:kill_by_port
if not defined PORT goto :eof
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":!PORT! " ^| findstr "LISTENING"') do (
    tasklist /fi "PID eq %%p" /fi "IMAGENAME eq python.exe" 2>nul | find "%%p" >nul
    if !errorlevel!==0 taskkill /f /t /pid %%p
)
goto :eof

:: G: 端口检测（netstat预筛 + 真实bind试探）
:check_port
set "PORT=%~1"
set "PORT_OK=0"
:: G1: netstat 快速预筛（errorlevel 0=找到LISTENING, 1=没找到, 2=出错）
netstat -ano 2>nul | findstr ":%~1 " | findstr "LISTENING" >nul 2>&1
if !errorlevel!==0 goto :eof
if !errorlevel! EQU 2 goto :eof
:: G2: 真实 bind 试探（检测 WinNAT 保留端口）
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import socket;s=socket.socket();s.bind(('127.0.0.1',%~1));s.close()" >nul 2>&1
    if !errorlevel!==0 set "PORT_OK=1"
) else (
    set "PORT_OK=1"
)
goto :eof
