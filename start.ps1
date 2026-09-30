# 本文件必须保存为 UTF-8 with BOM，否则 PowerShell 5.1 下中文提示会乱码。
# 且不要用 `type start.ps1 | powershell -` 这类管道方式调用（BOM 会污染脚本）。
param(
    [string]$PythonExe = "",
    [switch]$InstallDependencies,
    [switch]$InstallOnly,
    [switch]$Quiet
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$Requirements = Join-Path $Root 'requirements.txt'
$Stamp = Join-Path $Root '.venv\.dependencies-ready'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'

# ========== B1: 安全执行外部命令获取版本（局部降级 EAP）==========
function Invoke-PythonVersion {
    param([string]$Exe, [string[]]$PrefixArgs = @())
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = $null
    try {
        $allArgs = @($PrefixArgs) + @('--version')
        $output = & $Exe @allArgs 2>&1 | Out-String
        if ($null -eq $LASTEXITCODE -or $LASTEXITCODE -ne 0) { return $null }
        if ([string]::IsNullOrWhiteSpace($output)) { return $null }
        if ($output -match 'Python\s+(\d+)\.(\d+)') {
            return [version]"$($Matches[1]).$($Matches[2])"
        }
        return $null
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $prevEAP
    }
}

# ========== B2/B3: Python 自动探测（版本闸门 3.10~3.13，挑最新）==========
function Find-Python {
    $candidates = @()
    $foundAnyPython = $false
    $foundVersions = @()

    # 1. py launcher（Windows Python Launcher）
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        foreach ($ver in @('-3.12', '-3.11', '-3.10', '-3.13', '-3')) {
            $v = Invoke-PythonVersion -Exe 'py' -PrefixArgs @($ver)
            if ($v) {
                $foundAnyPython = $true
                $foundVersions += $v
                if ($v.Major -eq 3 -and $v.Minor -ge 10 -and $v.Minor -le 13) {
                    $candidates += @{ Exe = 'py'; Args = @($ver); Version = $v }
                }
            }
        }
    }

    # 2. PATH 中的 python（排除 0 字节 WindowsApps Store 占位别名）
    $pythonCmds = @(Get-Command python -All -ErrorAction SilentlyContinue)
    foreach ($cmd in $pythonCmds) {
        $path = $cmd.Source
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $item = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
        if (-not $item -or $item.Length -eq 0) { continue }
        $v = Invoke-PythonVersion -Exe $path
        if ($v) {
            $foundAnyPython = $true
            $foundVersions += $v
            if ($v.Major -eq 3 -and $v.Minor -ge 10 -and $v.Minor -le 13) {
                $candidates += @{ Exe = $path; Args = @(); Version = $v }
            }
        }
    }

    # 3. 常见安装路径回退
    $paths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python313\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe"
    )
    foreach ($p in $paths) {
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $item = Get-Item -LiteralPath $p -ErrorAction SilentlyContinue
        if (-not $item -or $item.Length -eq 0) { continue }
        $v = Invoke-PythonVersion -Exe $p
        if ($v) {
            $foundAnyPython = $true
            $foundVersions += $v
            if ($v.Major -eq 3 -and $v.Minor -ge 10 -and $v.Minor -le 13) {
                $candidates += @{ Exe = $p; Args = @(); Version = $v }
            }
        }
    }

    # B3: 挑满足区间的最新次版本
    if ($candidates.Count -eq 0) {
        if ($foundAnyPython) {
            $detected = ($foundVersions | Sort-Object -Descending | Select-Object -First 1)
            return @{ Status = 'wrong_version'; DetectedVersion = $detected }
        }
        return @{ Status = 'not_found' }
    }

    $best = $candidates | Sort-Object { $_.Version } -Descending | Select-Object -First 1
    return @{ Status = 'ok'; Exe = $best.Exe; Args = $best.Args; Version = $best.Version }
}

# ========== I: Python 缺失时的友好提示 ==========
function Show-NoPythonMessage {
    Write-Host ''
    Write-Host '  ==========================================' -ForegroundColor Red
    Write-Host '   [错误] 本机未安装 Python，无法启动' -ForegroundColor Red
    Write-Host '  ==========================================' -ForegroundColor Red
    Write-Host ''
    Write-Host '  本软件需要 Python 3.10 ~ 3.13（推荐 3.12）'
    Write-Host ''
    Write-Host '  方法一（推荐）：按 Win+R 输入 powershell 回车，复制粘贴：'
    Write-Host ''
    Write-Host '     winget install -e --id Python.Python.3.12' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '     若提示"winget 不是内部或外部命令"，请改用方法二。'
    Write-Host '     若提示需要管理员权限，请右键"以管理员身份运行"PowerShell。'
    Write-Host ''
    Write-Host '  方法二：浏览器打开 https://www.python.org/downloads/ 下载安装' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  *** 安装时务必勾选 "Add python.exe to PATH" ***' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  确认安装成功：关闭PowerShell，重新打开新的，输入 python --version'
    Write-Host '  显示 Python 3.12.x 即成功；若提示"不是内部或外部命令"需重装并勾PATH。'
    Write-Host ''
}

# ========== B5: 版本不合格专用提示 ==========
function Show-WrongVersionMessage {
    param([version]$Detected)
    Write-Host ''
    Write-Host '  ==========================================' -ForegroundColor Yellow
    Write-Host '   [错误] Python 版本不符，无法启动' -ForegroundColor Yellow
    Write-Host '  ==========================================' -ForegroundColor Yellow
    Write-Host ''
    if ($Detected) {
        Write-Host "  检测到 Python $($Detected.ToString())，但本软件需要 3.10 ~ 3.13（推荐 3.12）。"
    } else {
        Write-Host '  检测到 Python，但版本不在 3.10 ~ 3.13 范围内（推荐 3.12）。'
    }
    Write-Host ''
    Write-Host '  解决办法：安装 Python 3.12'
    Write-Host '     winget install -e --id Python.Python.3.12' -ForegroundColor Cyan
    Write-Host '     或从 https://www.python.org/downloads/ 下载' -ForegroundColor Cyan
    Write-Host '     安装时务必勾选 "Add python.exe to PATH"' -ForegroundColor Yellow
    Write-Host ''
}

# ========== 主逻辑 ==========
try {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        # 需要创建虚拟环境 - 先找可用的 Python
        $pythonInfo = $null
        if ($PythonExe -and $PythonExe.Trim()) {
            if (Test-Path -LiteralPath $PythonExe) {
                $pythonInfo = @{ Status = 'ok'; Exe = $PythonExe; Args = @(); Version = $null }
            } else {
                throw "指定的 Python 路径不存在：$PythonExe"
            }
        } else {
            $pythonInfo = Find-Python
        }

        if (-not $pythonInfo -or $pythonInfo.Status -eq 'not_found') {
            # -Quiet 仅抑制给最终用户的引导文案（由调用方 .bat 统一提示）；退出码语义不变
            if (-not $Quiet) { Show-NoPythonMessage }
            exit 2
        }
        if ($pythonInfo.Status -eq 'wrong_version') {
            if (-not $Quiet) { Show-WrongVersionMessage -Detected $pythonInfo.DetectedVersion }
            exit 3
        }

        $exeDisplay = $pythonInfo.Exe
        if ($pythonInfo.Args.Count -gt 0) { $exeDisplay += ' ' + ($pythonInfo.Args -join ' ') }
        if ($pythonInfo.Version) { $exeDisplay += " (版本 $($pythonInfo.Version))" }
        Write-Host "检测到 Python：$exeDisplay"

        # 创建虚拟环境
        $venvPath = Join-Path $Root '.venv'
        $allArgs = @($pythonInfo.Args) + @('-m', 'venv', $venvPath)
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $pythonInfo.Exe @allArgs 2>&1 | Out-Null
        $venvExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEAP
        if ($venvExit -ne 0) {
            # C: 失败时删除半成品 venv
            if (Test-Path -LiteralPath $venvPath) { Remove-Item -LiteralPath $venvPath -Recurse -Force -ErrorAction SilentlyContinue }
            throw "虚拟环境创建失败（退出码 $venvExit）。已清理残留，请重试。"
        }

        # C: 建 venv 后校验版本
        $venvVer = Invoke-PythonVersion -Exe $VenvPython
        if (-not $venvVer -or $venvVer.Major -ne 3 -or $venvVer.Minor -lt 10 -or $venvVer.Minor -gt 13) {
            if (Test-Path -LiteralPath $venvPath) { Remove-Item -LiteralPath $venvPath -Recurse -Force -ErrorAction SilentlyContinue }
            $verStr = if ($venvVer) { $venvVer.ToString() } else { '未知' }
            throw "虚拟环境中的 Python 版本($verStr)不在 3.10~3.13 范围，已清理。请安装正确版本后重试。"
        }
        Write-Host "虚拟环境创建成功（Python $($venvVer.ToString())）"
        $InstallDependencies = $true
    }

    # 安装/更新依赖（C: 空戳 null 安全）
    $RequiredHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
    $InstalledHash = ''
    if (Test-Path -LiteralPath $Stamp) {
        $rawStamp = Get-Content -LiteralPath $Stamp -Raw -ErrorAction SilentlyContinue
        if (-not [string]::IsNullOrWhiteSpace($rawStamp)) { $InstalledHash = $rawStamp.Trim() }
    }
    if ($InstallDependencies -or ($RequiredHash -ne $InstalledHash)) {
        Write-Host '正在安装依赖包（首次需要网络下载，约1-2分钟）...'
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $VenvPython -m pip --isolated --require-virtualenv --disable-pip-version-check --no-input install --only-binary=:all: --no-cache-dir -r $Requirements
        $pipExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEAP
        if ($pipExit -ne 0) {
            # C: pip 失败时删除 venv 以便下次自愈
            $venvPath = Join-Path $Root '.venv'
            $verInfo = Invoke-PythonVersion -Exe $VenvPython
            $verStr = if ($verInfo) { "Python $($verInfo.ToString())" } else { 'Python 版本未知' }
            if (Test-Path -LiteralPath $venvPath) { Remove-Item -LiteralPath $venvPath -Recurse -Force -ErrorAction SilentlyContinue }
            throw "依赖安装失败（$verStr，退出码 $pipExit）。已清理 .venv，请确认网络可用后重试。"
        }
        Set-Content -LiteralPath $Stamp -Value $RequiredHash -Encoding ASCII
    }

    if ($InstallOnly) { Write-Host '依赖准备完成。'; exit 0 }

    # 启动服务
    if (-not $env:BID_PORT) { $env:BID_PORT = '8000' }
    $Port = 0
    if (-not [int]::TryParse($env:BID_PORT, [ref]$Port) -or $Port -lt 1024 -or $Port -gt 65535) {
        throw 'BID_PORT 必须是 1024 至 65535 的整数。'
    }
    if (-not $env:BID_DATA_DIR) { $env:BID_DATA_DIR = Join-Path $Root 'data' }
    Write-Host "本地地址：http://127.0.0.1:$Port"
    Write-Host "数据保存在本机：$env:BID_DATA_DIR"
    Write-Host '请保持窗口打开；按 Ctrl+C 停止。'
    Push-Location -LiteralPath $Root
    try {
        & $VenvPython -m app
        if ($LASTEXITCODE -ne 0) { throw '服务启动失败，请确认端口未被占用以及数据目录可写。' }
    } finally { Pop-Location }
} catch {
    Write-Host ''
    Write-Host "错误：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host ''
    exit 1
}
