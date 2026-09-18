# Registra una tarea programada que arranca el motor al iniciar sesión en Windows.
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$exe = Join-Path $root ".venv\Scripts\sergio-brain.exe"
$action = New-ScheduledTaskAction -Execute $exe -Argument "serve"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -Hidden -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "SergioBrain" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Tarea 'SergioBrain' registrada. Se ejecuta 'sergio-brain serve' al iniciar sesión. Quitar: Unregister-ScheduledTask -TaskName SergioBrain"
