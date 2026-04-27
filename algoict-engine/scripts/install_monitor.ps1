# install_monitor.ps1
# ====================
# Register the AlgoICT health monitor as a Windows Scheduled Task
# that fires every 60 seconds, indefinitely.
#
# The monitor is INDEPENDENT of the bot -- it runs as its own PowerShell
# process, reads .health.json, and alerts via Telegram (+ local log
# fallback) when the bot is dead, feed is stale, positions diverge
# from broker, kill switch trips, or MLL zone escalates.
#
# Usage:
#   # Install (creates the task)
#   powershell -ExecutionPolicy Bypass -File scripts\install_monitor.ps1
#
#   # Uninstall (remove the task)
#   powershell -ExecutionPolicy Bypass -File scripts\install_monitor.ps1 -Uninstall
#
#   # Verify after install
#   Get-ScheduledTask -TaskName AlgoICT-Monitor
#   schtasks /Query /TN AlgoICT-Monitor /V /FO LIST
#
#   # Force an immediate run (for testing)
#   Start-ScheduledTask -TaskName AlgoICT-Monitor
#
#   # Check what the monitor wrote (local alert log)
#   Get-Content C:\AI Projects\AlgoICT\algoict-engine\.monitor_alerts.log -Tail 50

param(
    [switch]$Uninstall,
    [switch]$Enable,
    [switch]$Disable,
    [string]$TaskName = "AlgoICT-Monitor",
    [string]$EngineRoot = "C:\AI Projects\AlgoICT\algoict-engine"
)

$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $EngineRoot "scripts\monitor.ps1"

if ($Uninstall) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "OK: task '$TaskName' removed."
    } catch {
        Write-Host "INFO: task '$TaskName' was not registered (nothing to remove)."
    }
    exit 0
}

if ($Disable) {
    # Convenience: stop monitor without uninstalling. Use this when you
    # intentionally take the bot offline (weekends, maintenance) so the
    # monitor doesn't fill your Telegram with "bot dead" alerts.
    # Re-enable with `-Enable` when you relaunch the bot.
    try {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        # Also clear stale state so the next enable starts fresh.
        $stateFile = Join-Path $EngineRoot ".monitor_state.json"
        if (Test-Path $stateFile) { Remove-Item $stateFile -Force }
        Write-Host "OK: monitor DISABLED. State cleared."
        Write-Host "Re-enable with:"
        Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_monitor.ps1 -Enable"
    } catch {
        Write-Error "Failed to disable: $_"
        exit 1
    }
    exit 0
}

if ($Enable) {
    try {
        Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        Write-Host "OK: monitor ENABLED. Will run every 60s."
        Write-Host "Tail alerts: Get-Content '$EngineRoot\.monitor_alerts.log' -Tail 20 -Wait"
    } catch {
        Write-Error "Failed to enable: $_"
        exit 1
    }
    exit 0
}

# Verify prerequisites
if (-not (Test-Path $scriptPath)) {
    Write-Error "monitor.ps1 not found at $scriptPath"
    exit 1
}

$envFile = Join-Path $EngineRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Warning ".env not found at $envFile -- monitor will log alerts locally only (no Telegram)."
}

# Build the scheduled task.
# 2026-04-26: switched from direct powershell.exe to a VBScript wrapper
# (run_monitor_silent.vbs) because Task Scheduler's `-WindowStyle Hidden`
# still flashes a black PowerShell window for ~100ms on launch (known
# Windows quirk). The VBS wrapper uses WSHShell.Run with windowStyle=0
# which hides the window completely.
$vbsPath = Join-Path $EngineRoot "scripts\run_monitor_silent.vbs"
if (-not (Test-Path $vbsPath)) {
    Write-Error "run_monitor_silent.vbs not found at $vbsPath"
    exit 1
}
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$vbsPath`""

# Trigger: start now, repeat every 1 minute, for up to 10 years.
# (Task Scheduler rejects [TimeSpan]::MaxValue as out-of-range.)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)).Repetition

# Settings: allow start on battery, no time limit, restart on failure
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew

# Register / replace
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "AlgoICT external health monitor -- reads .health.json every 60s, alerts via Telegram on divergence / bot death / WS stale / kill switch / MLL danger." `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "OK: task '$TaskName' registered."
Write-Host ""
Write-Host "Verify with:"
Write-Host "   Get-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "Force a test run:"
Write-Host "   Start-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "Tail the alert log:"
Write-Host "   Get-Content '$EngineRoot\.monitor_alerts.log' -Tail 20 -Wait"
Write-Host ""
Write-Host "Pause monitor while bot is off (no Telegram flood during weekends):"
Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_monitor.ps1 -Disable"
Write-Host ""
Write-Host "Resume monitor after relaunching bot:"
Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_monitor.ps1 -Enable"
Write-Host ""
Write-Host "Uninstall completely:"
Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_monitor.ps1 -Uninstall"
