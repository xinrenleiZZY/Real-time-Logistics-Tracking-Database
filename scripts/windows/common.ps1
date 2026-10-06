# 公共函数：项目根目录定位、端口探测、健康检查、日志写入

function Get-ProjectRoot {
    $dir = if ($PSScriptRoot) { $PSScriptRoot } elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { (Get-Location).Path }
    return (Split-Path -Parent (Split-Path -Parent $dir))
}

function Test-ServiceListening {
    # 优先用 TCP 直连判断（不依赖管理员权限，比 Get-NetTCPConnection 稳定）
    param([int]$Port = 7650, [int]$TimeoutMs = 1500)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if ($async.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            $client.EndConnect($async)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        try { $client.Close() } catch { }
    }
}

function Get-PortOwnerPid {
    param([int]$Port = 7650)
    $pattern = ":{0}\s" -f $Port
    $pids = @()
    $pids += & netstat -ano 2>$null |
        Select-String -Pattern $pattern |
        Select-String -Pattern 'LISTENING' |
        ForEach-Object { ($_.Line -split '\s+')[-1] }
    if (-not $pids) {
        try {
            $pids += Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess
        } catch { }
    }
    return @($pids | Where-Object { $_ } | Select-Object -Unique)
}

function Test-ServiceHealthy {
    param([int]$Port = 7650)
    try {
        $resp = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/healthz" -f $Port) -UseBasicParsing -TimeoutSec 3
        return ($resp.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Write-ServiceLog {
    param([string]$Message, [string]$LogFile)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    if ($LogFile) {
        try { Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8 } catch { }
    }
    Write-Host $line
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-LocalIPv4 {
    $ips = @()
    try {
        $ips += Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
            Select-Object -ExpandProperty IPAddress
    } catch { }
    if (-not $ips) {
        $ips += & ipconfig 2>$null |
            Select-String -Pattern 'IPv4' |
            ForEach-Object { ($_.Line -split ':')[-1].Trim() } |
            Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' -and $_ -notlike '127.*' -and $_ -notlike '169.254.*' }
    }
    # 常见内网网段优先展示，避免把虚拟网卡/VPN 排在前面
    $ranked = @($ips | Select-Object -Unique | Sort-Object @{ Expression = {
        if ($_ -like '192.168.*') { 0 } elseif ($_ -like '10.*') { 1 } elseif ($_ -match '^172\.(1[6-9]|2[0-9]|3[01])\.') { 2 } else { 3 }
    } })
    return $ranked
}
