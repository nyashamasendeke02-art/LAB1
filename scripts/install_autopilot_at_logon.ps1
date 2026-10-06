# Optional (D39): start the LAB1 autopilot automatically at Windows logon.
# Run once in PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\install_autopilot_at_logon.ps1
# Remove with:              Unregister-ScheduledTask -TaskName "LAB1 autopilot" -Confirm:$false
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$root\scripts\start_autopilot.cmd`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Register-ScheduledTask -TaskName "LAB1 autopilot" -Action $action -Trigger $trigger -Description "Keeps the LAB1 robolab queue moving (docs: scripts/autopilot.py)" -Force
