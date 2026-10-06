# 放行防火墙 7650 端口：让局域网其他电脑能访问本系统（需要管理员权限）

param([int]$Port = 7650)

. "$PSScriptRoot\common.ps1"

if (-not (Test-IsAdmin)) {
    Write-Host '需要管理员权限，正在弹出授权窗口...'
    Start-Process -FilePath 'powershell.exe' `
        -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Port', "$Port" `
        -Verb RunAs
    exit 0
}

$ruleName = "物流追踪实时库 端口 $Port"

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "防火墙规则已存在：$ruleName"
} else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
        -Protocol TCP -LocalPort $Port -Profile Any -Description '物流追踪实时库局域网访问' | Out-Null
    Write-Host "已放行入站 TCP $Port：$ruleName"
}

# 顺便放行本项目的 python 解释器，避免以后换端口又要重加
$root = Get-ProjectRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$pyRuleName = '物流追踪实时库 python'
if (Test-Path -LiteralPath $python) {
    $pyRule = Get-NetFirewallRule -DisplayName $pyRuleName -ErrorAction SilentlyContinue
    if (-not $pyRule) {
        New-NetFirewallRule -DisplayName $pyRuleName -Direction Inbound -Action Allow `
            -Program $python -Profile Any -Description '物流追踪实时库虚拟环境解释器' | Out-Null
        Write-Host "已放行程序入站：$python"
    } else {
        Write-Host "防火墙规则已存在：$pyRuleName"
    }
}

foreach ($ip in Get-LocalIPv4) {
    Write-Host "其他电脑可访问：http://${ip}:$Port"
}
Write-Host '完成。如仍访问不通，请检查两台电脑是否在同一网段。'
