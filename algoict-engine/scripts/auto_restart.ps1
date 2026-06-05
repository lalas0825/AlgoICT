# auto_restart.ps1
# ================
# AlgoICT bot AUTO-RESTART watchdog. Runs as a Scheduled Task every ~2 min,
# INDEPENDENT of any interactive/remote user session. If the bot is dead
# (health.json stale AND the .engine.lock PID is gone), it relaunches the bot
# in live mode (detached, confirmation piped), with anti-loop protection and a
# Telegram alert.
#
# Built 2026-06-05 after the bot vanished at ~00:53 CT with NO code traceback,
# NO OS power/sleep event (last sleep was 3/11), NO reboot (up since 5/31), and
# NO app-crash event -- and it coincided with the operator losing the Claude
# Code remote-control connection. That points to a session/network/machine
# event that killed the bot PROCESS. The external monitor ALERTS on bot_dead
# but does NOT relaunch, so the bot stayed dead ~3h and missed a London session.
# This watchdog closes that gap; and because it launches the bot from the Task
# Scheduler's background session, the relaunched bot is no longer tied to the
# operator's interactive/remote session (which likely caused the death).
#
#   Install/Enable/Disable/Uninstall via scripts\install_auto_restart.ps1
#   Tail:   Get-Content <EngineRoot>\.auto_restart.log -Tail 20 -Wait

param(
    [string]$EngineRoot = "C:\AI Projects\AlgoICT\algoict-engine",
    [string]$Python     = "C:\Python314\python.exe",
    [int]$StaleSec      = 120,   # health.json older than this = bot stopped writing
    [int]$MaxPerHour    = 4      # anti-loop: max relaunches per rolling hour
)

$ErrorActionPreference = 'Stop'
$health    = Join-Path $EngineRoot ".health.json"
$lock      = Join-Path $EngineRoot ".engine.lock"
$stateFile = Join-Path $EngineRoot ".auto_restart_state.json"
$logFile   = Join-Path $EngineRoot ".auto_restart.log"

function Log($m) {
    try { "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss')) $m" | Add-Content -Path $logFile -Encoding utf8 } catch {}
}

function Send-Telegram($text) {
    try {
        $envFile = Join-Path $EngineRoot ".env"
        if (-not (Test-Path $envFile)) { return }
        $lines = Get-Content $envFile -ErrorAction SilentlyContinue
        $tok  = ($lines | Where-Object { $_ -match '^TELEGRAM_BOT_TOKEN=' } | Select-Object -First 1)
        $chat = ($lines | Where-Object { $_ -match '^TELEGRAM_CHAT_ID='   } | Select-Object -First 1)
        if (-not $tok -or -not $chat) { return }
        $tok  = ($tok  -split '=', 2)[1].Trim()
        $chat = ($chat -split '=', 2)[1].Trim()
        if (-not $tok -or -not $chat) { return }
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$tok/sendMessage" -Method Post `
            -Body @{ chat_id = $chat; text = $text } -TimeoutSec 15 | Out-Null
    } catch {}
}

# 1. Bot alive? (health.json fresh) -> nothing to do.
$age = 99999   # default = "very stale" if health.json is missing entirely
if (Test-Path $health) {
    $age = [int]((Get-Date) - (Get-Item $health).LastWriteTime).TotalSeconds
    if ($age -lt $StaleSec) { exit 0 }
}

# 2. health stale -- is the bot PROCESS still alive (per .engine.lock)?
#    If alive, the bot is HUNG (not dead): do NOT relaunch from here (that is
#    the internal asyncio watchdog's + the monitor's job; relaunching a live
#    process could double-run / fight an open position). Only act on a CLEAN
#    death where the bot PID is gone.
$botPid = $null
if (Test-Path $lock) { $botPid = (Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 1) }
if ($botPid -and (Get-Process -Id ([int]$botPid) -ErrorAction SilentlyContinue)) {
    Log "health stale (${age}s) but bot PID $botPid ALIVE (hung?) -- not relaunching."
    exit 0
}

# --- Bot is DEAD (health stale + lock PID gone). Relaunch. ---

# 3. Anti-loop: cap relaunches in the rolling last hour.
$now  = Get-Date
$hist = @()
if (Test-Path $stateFile) { try { $hist = @((Get-Content $stateFile -Raw | ConvertFrom-Json)) } catch { $hist = @() } }
$hist = @($hist | Where-Object { $_ -and ([datetime]$_ -gt $now.AddHours(-1)) })
if ($hist.Count -ge $MaxPerHour) {
    Log "DEAD but $($hist.Count) restarts in last hour >= $MaxPerHour -- backing off (manual check needed)."
    Send-Telegram "[AlgoICT auto-restart] Bot DEAD but hit $MaxPerHour restarts/hour -- BACKING OFF. Manual intervention needed (possible crash loop)."
    exit 0
}

# 4. Relaunch live, detached, confirmation piped (the live-mode YES gate).
$ts  = Get-Date -Format "yyyy-MM-dd_HHmmss"
$out = Join-Path $EngineRoot "logs\live_auto_$ts.out"
$err = Join-Path $EngineRoot "logs\live_auto_$ts.err"
try {
    $logsDir = Join-Path $EngineRoot "logs"
    if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir -Force | Out-Null }
    # UNIQUE confirm file per relaunch. A bot launched with -RedirectStandardInput
    # keeps the stdin handle open for its whole life, locking the file. A fixed
    # name would make a later relaunch's Out-File throw and abort silently. A
    # random name sidesteps lock contention entirely.
    $confirm = Join-Path $env:TEMP ("algoict_live_confirm_" + [System.IO.Path]::GetRandomFileName() + ".txt")
    "YES I CONFIRM" | Out-File -FilePath $confirm -Encoding ascii
    $p = Start-Process -FilePath $Python -ArgumentList "main.py", "--mode", "live" `
            -WorkingDirectory $EngineRoot -RedirectStandardInput $confirm `
            -RedirectStandardOutput $out -RedirectStandardError $err `
            -WindowStyle Hidden -PassThru
    Log "RELAUNCHED bot (PID $($p.Id)) -- log $err"
    Send-Telegram "[AlgoICT auto-restart] Bot was DEAD -> relaunched LIVE (PID $($p.Id)). Confirm account=21551969 + User-Hub on startup."
    $hist += $now.ToString('o')
    $hist | ConvertTo-Json | Out-File $stateFile -Encoding utf8
} catch {
    Log "RELAUNCH FAILED: $($_.Exception.Message)"
    Send-Telegram "[AlgoICT auto-restart] Relaunch FAILED: $($_.Exception.Message)"
}
exit 0
