param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$TaskName = "QA Platforms Prod"
)

$ErrorActionPreference = "Stop"

$startScript = Join-Path $ProjectDir "scripts\windows\start-qa-platform-prod.ps1"
if (-not (Test-Path $startScript)) {
    throw "找不到启动脚本: $startScript"
}

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -ProjectDir `"$ProjectDir`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "启动 QA Platforms 生产 Docker 服务" `
    -Force | Out-Null

Write-Host "已注册开机/登录自启任务: $TaskName"
Write-Host "建议同时在 Docker Desktop Settings > General 启用 Start Docker Desktop when you sign in。"
