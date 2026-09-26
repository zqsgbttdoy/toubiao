param(
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    [switch]$InstallDependencies,
    [switch]$InstallOnly
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$Requirements = Join-Path $Root 'requirements.txt'
$Stamp = Join-Path $Root '.venv\.dependencies-ready'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
try {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        if (-not (Test-Path -LiteralPath $PythonExe)) {
            throw '未找到Python3.12，请先安装或使用-PythonExe指定解释器绝对路径。'
        }
        & $PythonExe -m venv (Join-Path $Root '.venv')
        if ($LASTEXITCODE -ne 0) { throw '虚拟环境创建失败。' }
        $InstallDependencies = $true
    }
    $RequiredHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
    $InstalledHash = if (Test-Path -LiteralPath $Stamp) { (Get-Content -LiteralPath $Stamp -Raw).Trim() } else { '' }
    if ($InstallDependencies -or ($RequiredHash -ne $InstalledHash)) {
        Write-Host '首次或依赖更新安装：仅向项目.venv安装锁定包，下载需要网络；正常运行无云服务依赖。'
        & $VenvPython -m pip --isolated --require-virtualenv --disable-pip-version-check --no-input install --only-binary=:all: --no-cache-dir -r $Requirements
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请确认首次安装时网络可用后重试。' }
        Set-Content -LiteralPath $Stamp -Value $RequiredHash -Encoding ASCII
    }
    if ($InstallOnly) { Write-Host '依赖准备完成，未启动服务。'; exit 0 }
    if (-not $env:BID_PORT) { $env:BID_PORT = '8000' }
    $Port = 0
    if (-not [int]::TryParse($env:BID_PORT, [ref]$Port) -or $Port -lt 1024 -or $Port -gt 65535) {
        throw 'BID_PORT必须是1024至65535的整数。'
    }
    if (-not $env:BID_DATA_DIR) { $env:BID_DATA_DIR = Join-Path $Root 'data' }
    Write-Host "本地地址：http://127.0.0.1:$Port"
    Write-Host "数据保存在本机：$env:BID_DATA_DIR"
    Write-Host '请保持窗口打开；按Ctrl+C停止。外部AI未接入，输出仅供人工复核。'
    Push-Location -LiteralPath $Root
    try {
        & $VenvPython -m app
        if ($LASTEXITCODE -ne 0) { throw '服务启动失败，请确认端口未被占用以及数据目录可写。' }
    } finally { Pop-Location }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
