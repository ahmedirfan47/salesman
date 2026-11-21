# Installs the Salesman print agent as a scheduled task that starts with Windows and restarts if it stops.
# Run in PowerShell as Administrator from this folder:  powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path "$here\config.ini")) { throw "Create config.ini first (copy config.example.ini and fill it in)." }
$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "Python is not installed or not on PATH. Install Python 3.10+ from python.org." }
& python -m pip install -r "$here\requirements.txt"
& python "$here\salesman_print_agent.py" --test
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$here\salesman_print_agent.py`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -StartWhenAvailable
Register-ScheduledTask -TaskName "Salesman Print Agent" -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName "Salesman Print Agent"
Write-Host "Installed. The agent runs in the background and starts with Windows. Log: $here\print-agent.log"
