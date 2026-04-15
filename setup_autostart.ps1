$taskName = "TelegramClaudeBot"
$scriptPath = "E:\workspace\telegram-claude-bot\start_bot.vbs"
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $scriptPath
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
Write-Host "✅ 任务计划 [$taskName] 注册成功，下次登录时自动启动"
