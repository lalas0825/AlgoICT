# install_auto_restart.ps1
# =========================
# Register the AlgoICT AUTO-RESTART watchdog as a Windows Scheduled Task
# that fires every 2 minutes, indefinitely.
#
# Unlike the health MONITOR (which only ALERTS on bot death), this watchdog
# RELAUNCHES the bot when it dies. Because Task Scheduler runs it in its own
# background session, the relaunched bot is INDEPENDENT of the operator's
# interactive / Claude-Code-remote session -- which is what we believe killed
# the bot at ~00:53 CT on 2026-06-05 (no traceback, no power/sleep, no reboot,
# but the operator lost remote-control at the same moment).
#
# auto_restart.ps1 is conservative: it only relaunches on a CLEAN death
# (health.json stale AND .engine.lock PID gone). If the bot is merely HUNG
# (PID still alive) it does nothing -- that is the internal asyncio watchdog's
# and the monitor's job. Anti-loop cap: max 4 relaunches per rolling hour.
#
# Usage:
#   # Install (creates the task)
#   powershell -ExecutionPolicy Bypass -File scripts\install_auto_restart.ps1
#
#   # Uninstall (remove the task)
#   powershell -ExecutionPolicy Bypass -File scripts\install_auto_restart.ps1 -Uninstall
#
#   # Pause while the bot is intentionally offline (weekend / maintenance)
#   powershell -ExecutionPolicy Bypass -File scripts\install_auto_restart.ps1 -Disable
#
#   # Resume
#   powershell -ExecutionPolicy Bypass -File scripts\install_auto_restart.ps1 -Enable
#
#   # Verify after install
#   Get-ScheduledTask -TaskName AlgoICT-AutoRestart
#
#   # Force an immediate run (for testing -- does nothing if the bot is alive)
#   Start-ScheduledTask -TaskName AlgoICT-AutoRestart
#
#   # Check what the watchdog did
#   Get-Content C:\AI Projects\AlgoICT\algoict-engine\.auto_restart.log -Tail 50

param(
    [switch]$Uninstall,
    [switch]$Enable,
    [switch]$Disable,
    [string]$TaskName = "AlgoICT-AutoRestart",
    [string]$EngineRoot = "C:\AI Projects\AlgoICT\algoict-engine"
)

$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $EngineRoot "scripts\auto_restart.ps1"

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
    # Convenience: stop the watchdog without uninstalling. Use this when you
    # intentionally take the bot offline (weekends, maintenance) so the
    # watchdog doesn't relaunch a bot you deliberately stopped.
    # Re-enable with `-Enable` when you relaunch the bot.
    try {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        # Also clear restart-history state so the next enable starts fresh.
        $stateFile = Join-Path $EngineRoot ".auto_restart_state.json"
        if (Test-Path $stateFile) { Remove-Item $stateFile -Force }
        Write-Host "OK: auto-restart DISABLED. Restart history cleared."
        Write-Host "Re-enable with:"
        Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_auto_restart.ps1 -Enable"
    } catch {
        Write-Error "Failed to disable: $_"
        exit 1
    }
    exit 0
}

if ($Enable) {
    try {
        Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        Write-Host "OK: auto-restart ENABLED. Will check every 2 min."
        Write-Host "Tail log: Get-Content '$EngineRoot\.auto_restart.log' -Tail 20 -Wait"
    } catch {
        Write-Error "Failed to enable: $_"
        exit 1
    }
    exit 0
}

# Verify prerequisites
if (-not (Test-Path $scriptPath)) {
    Write-Error "auto_restart.ps1 not found at $scriptPath"
    exit 1
}

$envFile = Join-Path $EngineRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Warning ".env not found at $envFile -- watchdog will still relaunch but cannot send Telegram alerts."
}

# Build the scheduled task.
# Use a VBScript wrapper (run_auto_restart_silent.vbs) for the same reason
# the monitor does: WSHShell.Run windowStyle=0 hides the powershell window
# completely (Task Scheduler's -WindowStyle Hidden still flashes ~100ms).
$vbsPath = Join-Path $EngineRoot "scripts\run_auto_restart_silent.vbs"
if (-not (Test-Path $vbsPath)) {
    Write-Error "run_auto_restart_silent.vbs not found at $vbsPath"
    exit 1
}
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$vbsPath`""

# Trigger: start now, repeat every 2 minutes, for up to 10 years.
# 2 min (not 1) because a relaunched bot needs ~60-90s to warm up and write
# its first .health.json; checking every 2 min avoids a false "still dead"
# read racing the warmup. (Task Scheduler rejects [TimeSpan]::MaxValue.)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Days 3650)).Repetition

# Settings: allow start on battery, short time limit, ignore overlap.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
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
    -Description "AlgoICT auto-restart watchdog -- every 2 min, relaunches the bot LIVE if it died cleanly (health.json stale + .engine.lock PID gone). Anti-loop cap 4/hour. Session-independent (survives operator session/remote drops)." `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "OK: task '$TaskName' registered."
Write-Host ""
Write-Host "Verify with:"
Write-Host "   Get-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "Force a test run (does NOTHING if the bot is alive -- safe):"
Write-Host "   Start-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "Tail the watchdog log:"
Write-Host "   Get-Content '$EngineRoot\.auto_restart.log' -Tail 20 -Wait"
Write-Host ""
Write-Host "Pause while the bot is intentionally off (weekend / maintenance):"
Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_auto_restart.ps1 -Disable"
Write-Host ""
Write-Host "Resume after relaunching the bot:"
Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_auto_restart.ps1 -Enable"
Write-Host ""
Write-Host "Uninstall completely:"
Write-Host "   powershell -ExecutionPolicy Bypass -File scripts\install_auto_restart.ps1 -Uninstall"
