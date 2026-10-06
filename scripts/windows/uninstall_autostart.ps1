# 卸载开机自启：删除“启动”文件夹里的快捷方式（不影响当前正在运行的服务）

. "$PSScriptRoot\common.ps1"

$startupDir = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startupDir '物流追踪实时库.lnk'

if (Test-Path -LiteralPath $lnkPath) {
    Remove-Item -LiteralPath $lnkPath -Force
    Write-Host "已取消开机自启：$lnkPath"
} else {
    Write-Host '当前没有安装开机自启，无需卸载。'
}
