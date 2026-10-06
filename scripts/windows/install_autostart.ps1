# 安装开机自启：在“启动”文件夹放一个快捷方式，登录后自动在后台拉起服务

. "$PSScriptRoot\common.ps1"

$root = Get-ProjectRoot
$startupDir = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startupDir '物流追踪实时库.lnk'
$target = Join-Path $root 'autostart.bat'

if (-not (Test-Path -LiteralPath $target)) {
    Write-Host "未找到 $target，无法安装开机自启。"
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $target
$lnk.WorkingDirectory = $root
$lnk.WindowStyle = 7
$lnk.Description = '物流追踪实时库开机自启（后台运行）'
$lnk.Save()

Write-Host "已安装开机自启：$lnkPath"
Write-Host '下次登录 Windows 后会自动在后台启动服务，无需手工双击 start.bat。'
Write-Host '取消自启请双击“开机自启_卸载.bat”。'
