# monitor.ps1
# ============
# External AlgoICT health monitor. Runs every 60s via Windows Task
# Scheduler (see install_monitor.ps1). Reads .health.json written by the
# bot, checks state thresholds, and alerts via Telegram (+ local log
# fallback) when anything looks wrong.
#
# KEY PROPERTY: this script is INDEPENDENT of the bot process. If the
# bot crashes or deadlocks, .health.json stops updating, the monitor
# notices mtime staleness, and fires "BOT DEAD" regardless of the bot.
# That's the whole point -- the bot can't alert on its own death.
#
# 2026-04-24 -- initial cut. Canal A: same Telegram bot as the engine
# (credentials read from .env). Fallback: append every alert to
# .monitor_alerts.log so you have a record even if Telegram is down.
#
# What this monitor catches that the in-process alerts cannot:
#   * Bot process crashed or deadlocked (Python exception / async hang)
#   * Bot is running but get_positions returning stale data (Bug J rerun)
#   * Local/broker position divergence (phantom positions like 2026-04-24)
#   * WS feed silently dead (last_bar_age stuck climbing)
#
# Alert dedup: same condition re-fires at most every 15 min.
# Resolve: when a condition clears, a single "RESOLVED" alert fires.

param(
    [string]$EngineRoot = "C:\AI Projects\AlgoICT\algoict-engine",
    [int]$StaleThresholdSec = 60,       # .health.json mtime older than this = BOT DEAD
    [int]$HeartbeatThresholdSec = 90,   # ts inside JSON older than this = BOT HUNG
    [int]$BarAgeThresholdSec = 1200,    # last_bar_age_s older than this = WS FEED DEAD
                                        # 20 min is conservative -- won't false-fire during
                                        # CME daily break (16-17 ET) or overnight quiet
                                        # but catches a real dropped SignalR feed
    [int]$AlertDedupMin = 15,           # don't re-alert same condition more than once per N min
    [int]$MaxConsecutiveAlerts = 3      # 2026-04-24 post-weekend-flood: after N alerts of the
                                        # same code without resolution, go quiet (assume the
                                        # operator is aware / shutdown is intentional) and
                                        # only re-alert when the condition resolves and re-fires.
                                        # 3 alerts at 15 min dedup = ~45 min total noise then silence.
)

$ErrorActionPreference = 'Continue'

# -- Paths ----------------------------------------------------------
$healthFile = Join-Path $EngineRoot ".health.json"
$stateFile  = Join-Path $EngineRoot ".monitor_state.json"
$alertLog   = Join-Path $EngineRoot ".monitor_alerts.log"
$envFile    = Join-Path $EngineRoot ".env"


# -- .env parser (needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID) -----
function Read-EnvFile {
    param([string]$Path)
    $result = @{}
    if (-not (Test-Path $Path)) { return $result }
    foreach ($line in (Get-Content $Path -ErrorAction SilentlyContinue)) {
        $trim = $line.Trim()
        if ($trim -eq '' -or $trim.StartsWith('#')) { continue }
        $eq = $trim.IndexOf('=')
        if ($eq -lt 1) { continue }
        $key = $trim.Substring(0, $eq).Trim()
        $val = $trim.Substring($eq + 1).Trim().Trim('"').Trim("'")
        $result[$key] = $val
    }
    return $result
}

$envVars = Read-EnvFile -Path $envFile
$tgToken  = $envVars["TELEGRAM_BOT_TOKEN"]
$tgChatId = $envVars["TELEGRAM_CHAT_ID"]


# -- State persistence ---------------------------------------------
function Get-MonitorState {
    if (Test-Path $stateFile) {
        try {
            return (Get-Content $stateFile -Raw -ErrorAction Stop | ConvertFrom-Json)
        } catch {
            # Corrupted state file -- start fresh.
        }
    }
    return [pscustomobject]@{
        last_alerts       = @{}
        # 2026-04-24: alert_counts[code] = number of CONSECUTIVE alerts
        # fired for that code without an intervening resolve. Used to
        # throttle long-running conditions (e.g. bot off all weekend)
        # so the user isn't flooded every 15 min with the same alert.
        alert_counts      = @{}
        active_conditions = @()
        last_check_ts     = $null
    }
}

function Get-AlertProp {
    # Helper: read a property from PSCustomObject or hashtable (state files
    # come back as PSCustomObject after ConvertFrom-Json).
    param($Container, [string]$Key)
    if ($null -eq $Container) { return $null }
    if ($Container -is [hashtable]) {
        if ($Container.ContainsKey($Key)) { return $Container[$Key] }
        return $null
    }
    if ($Container.PSObject.Properties[$Key]) {
        return $Container.$Key
    }
    return $null
}

function Set-AlertProp {
    param($Container, [string]$Key, $Value)
    if ($Container -is [hashtable]) {
        $Container[$Key] = $Value
    } else {
        if ($Container.PSObject.Properties[$Key]) {
            $Container.$Key = $Value
        } else {
            $Container | Add-Member -NotePropertyName $Key -NotePropertyValue $Value -Force
        }
    }
}

function Remove-AlertProp {
    param($Container, [string]$Key)
    if ($Container -is [hashtable]) {
        $Container.Remove($Key) | Out-Null
    } elseif ($Container.PSObject.Properties[$Key]) {
        $Container.PSObject.Properties.Remove($Key)
    }
}

function Save-MonitorState {
    param($State)
    try {
        $State | ConvertTo-Json -Depth 6 | Out-File -FilePath $stateFile -Encoding utf8 -Force
    } catch {
        Write-Host "WARN: failed to save monitor state: $_"
    }
}


# -- Alert channels ------------------------------------------------
function Send-TelegramAlert {
    param([string]$Text)
    if (-not $tgToken -or -not $tgChatId) { return $false }
    try {
        $payload = @{
            chat_id = $tgChatId
            text    = $Text
        } | ConvertTo-Json -Compress
        $uri = "https://api.telegram.org/bot$tgToken/sendMessage"
        $null = Invoke-RestMethod -Uri $uri -Method Post -Body $payload `
            -ContentType 'application/json' -TimeoutSec 5 -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Write-LocalAlert {
    param([string]$Text)
    try {
        $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Text"
        Add-Content -Path $alertLog -Value $line -Encoding UTF8
    } catch { }
}

function Fire-Alert {
    param(
        [string]$Code,       # short key like "user_hub_dead" (for dedup)
        [string]$Message,    # human-readable
        $State               # current monitor state (mutated)
    )
    $now = Get-Date
    $nowIso = $now.ToString('o')

    # Ensure alert_counts container exists (back-compat with old state files).
    if ($null -eq $State.alert_counts) {
        $State | Add-Member -NotePropertyName alert_counts -NotePropertyValue @{} -Force
    }

    # 2026-04-24 post-weekend-flood: cap consecutive alerts. After
    # $MaxConsecutiveAlerts notifications without resolution, go quiet
    # for this code. The local log keeps recording silently. The user
    # gets a final "going quiet" message on the Nth+1 attempt so they
    # know suppression is active.
    $count = [int](Get-AlertProp -Container $State.alert_counts -Key $Code)
    if ($count -ge $MaxConsecutiveAlerts) {
        # Silently update the log (no Telegram) so we still have evidence.
        Write-LocalAlert -Text "$Code | tg=false (suppressed: count=$count >= $MaxConsecutiveAlerts) | $Message"
        Set-AlertProp -Container $State.alert_counts -Key $Code -Value ($count + 1)
        return
    }

    # Dedup: don't re-fire same code more than once per $AlertDedupMin
    $last = Get-AlertProp -Container $State.last_alerts -Key $Code
    if ($last) {
        try {
            $lastDt = [datetime]::Parse($last)
            if (($now - $lastDt).TotalMinutes -lt $AlertDedupMin) {
                return  # throttled
            }
        } catch { }
    }

    # If this is the alert that crosses the threshold, append a hint so
    # the user knows we'll be silent until resolution.
    $finalMessage = $Message
    if (($count + 1) -ge $MaxConsecutiveAlerts) {
        $finalMessage += "`n[note] Going quiet on '$Code' until resolved (max=$MaxConsecutiveAlerts consecutive)."
    }

    $sent = Send-TelegramAlert -Text $finalMessage
    Write-LocalAlert -Text "$Code | tg=$sent | count=$($count + 1) | $Message"

    Set-AlertProp -Container $State.last_alerts -Key $Code -Value $nowIso
    Set-AlertProp -Container $State.alert_counts -Key $Code -Value ($count + 1)
}

function Fire-Resolve {
    param([string]$Code, [string]$Message, $State)
    $text = "[OK] RESOLVED -- $Message"
    $sent = Send-TelegramAlert -Text $text
    Write-LocalAlert -Text "resolve:$Code | tg=$sent | $Message"
    # Clear last-alert timestamp + consecutive count so a future
    # recurrence alerts immediately AND gets the full N alerts again.
    Remove-AlertProp -Container $State.last_alerts -Key $Code
    if ($null -ne $State.alert_counts) {
        Remove-AlertProp -Container $State.alert_counts -Key $Code
    }
}


# -- Main ----------------------------------------------------------
$state = Get-MonitorState
if ($state.active_conditions -isnot [array]) {
    $state.active_conditions = @()
}

# Track which conditions are active THIS tick so we can fire resolve
# for the ones that were active last tick but aren't now.
$nowActive = @()

# Check 1: Does .health.json exist?
if (-not (Test-Path $healthFile)) {
    Fire-Alert -Code "health_missing" `
               -Message ("[ALERT] .health.json MISSING at $healthFile. Bot is not running, never started, or cannot write to disk.") `
               -State $state
    $nowActive += "health_missing"
} else {
    # Check 2: Is the file fresh? (mtime)
    $mtimeAge = (Get-Date) - (Get-Item $healthFile).LastWriteTime
    if ($mtimeAge.TotalSeconds -gt $StaleThresholdSec) {
        Fire-Alert -Code "bot_dead" `
                   -Message ("[ALERT] BOT DEAD -- .health.json not updated in {0:F0}s (threshold ${StaleThresholdSec}s). Bot process likely crashed or deadlocked. Check PID + task manager." -f $mtimeAge.TotalSeconds) `
                   -State $state
        $nowActive += "bot_dead"
    } else {
        # File is fresh -- parse JSON and run state checks
        $health = $null
        try {
            $health = Get-Content $healthFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        } catch {
            Fire-Alert -Code "health_malformed" `
                       -Message "[ALERT] .health.json exists but cannot be parsed: $_" `
                       -State $state
            $nowActive += "health_malformed"
        }

        if ($health) {
            # Check 3: Heartbeat timestamp inside JSON (covers case where
            # file mtime updates but bot writes stale data -- unlikely but cheap)
            try {
                $healthTs = [datetime]::Parse($health.ts)
                $tsAge = [datetime]::UtcNow - $healthTs.ToUniversalTime()
                if ($tsAge.TotalSeconds -gt $HeartbeatThresholdSec) {
                    Fire-Alert -Code "heartbeat_stale" `
                               -Message ("[ALERT] Bot heartbeat stale: health.ts is {0:F0}s old (threshold ${HeartbeatThresholdSec}s)." -f $tsAge.TotalSeconds) `
                               -State $state
                    $nowActive += "heartbeat_stale"
                }
            } catch { }

            # Check 4: WS feed alive? last_bar_age_s should stay small during market.
            # 2026-04-24 post-audit fix: use actual ET timezone conversion
            # with DST awareness instead of hardcoded UTC hours. Previous
            # version was hardcoded for EST (UTC-5) and would false-fire
            # during EDT (UTC-4) period, March-November — most of the year.
            #
            # CME MNQ futures trade Sun 17:00 ET → Fri 16:00 ET, with a
            # daily 16:00-17:00 ET break. Outside those hours, no bars
            # are expected.
            $cmeClosed = $false
            try {
                $etTz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
                $etNow = [System.TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow, $etTz)
                $etDow = $etNow.DayOfWeek
                $etHour = $etNow.Hour
                if ($etDow -eq 'Saturday') {
                    $cmeClosed = $true
                } elseif ($etDow -eq 'Friday' -and $etHour -ge 16) {
                    $cmeClosed = $true       # Fri after 4 PM ET
                } elseif ($etDow -eq 'Sunday' -and $etHour -lt 17) {
                    $cmeClosed = $true       # Sun before 5 PM ET
                } elseif ($etHour -eq 16) {
                    $cmeClosed = $true       # daily 4-5 PM ET break
                }
            } catch {
                # TimeZone DB missing on minimal Windows builds — fall back
                # to no suppression (risk: false-fire during breaks, but
                # at least doesn't MISS a real stale feed).
                $cmeClosed = $false
            }
            if (-not $cmeClosed -and
                $health.last_bar_age_s -ne $null -and
                $health.last_bar_age_s -gt $BarAgeThresholdSec) {
                Fire-Alert -Code "ws_feed_stale" `
                           -Message ("[ALERT] WS feed stale: last bar is {0:F0}s old. SignalR may have dropped." -f $health.last_bar_age_s) `
                           -State $state
                $nowActive += "ws_feed_stale"
            }

            # Check 5: User Hub alive? (only matters if we expect it -- i.e. bot has positions or could take trades)
            # 60s uptime grace: User Hub subscribes ~5-15s after launch,
            # so don't false-fire during legitimate startup transients.
            $uptime = [int]($health.uptime_s | ForEach-Object { if ($_ -ne $null) { $_ } else { 0 } })
            if ($uptime -ge 60 -and
                $health.broker -and $health.broker.user_hub_alive -eq $false) {
                Fire-Alert -Code "user_hub_dead" `
                           -Message "[ALERT] User Hub DEAD -- no real-time fill events. Poll-path fallback may miss fills." `
                           -State $state
                $nowActive += "user_hub_dead"
            }

            # Check 6: Position divergence (local vs broker) -- THE Bug J check
            if ($health.positions) {
                $local  = [int]$health.positions.local_count
                $broker = [int]$health.positions.broker_count_cached
                # broker_count_cached = -1 means reconciler hasn't run yet, skip
                if ($broker -ge 0 -and $local -ne $broker) {
                    Fire-Alert -Code "position_divergence" `
                               -Message ("[CRITICAL] POSITION DIVERGENCE: local={0} broker={1}. Real position may be UNPROTECTED or bot may be tracking a ghost. Check broker GUI immediately." -f $local, $broker) `
                               -State $state
                    $nowActive += "position_divergence"
                }
            }

            # Check 7: Kill switch active (Telegram alert already fires from
            # the bot on transition, but monitor re-alerts if bot's alert
            # never delivered). Throttled via dedup.
            if ($health.risk -and $health.risk.kill_switch_active -eq $true) {
                Fire-Alert -Code "kill_switch" `
                           -Message ("[ALERT] Kill switch ACTIVE. Daily PnL={0} consecutive_losses={1}. Bot has halted new entries." -f $health.risk.daily_pnl, $health.risk.consecutive_losses) `
                           -State $state
                $nowActive += "kill_switch"
            }

            # Check 8: MLL zone in caution or stop
            if ($health.risk -and $health.risk.mll_zone -in @("caution", "stop")) {
                Fire-Alert -Code "mll_danger" `
                           -Message ("[WARN] MLL zone = {0}. Drawdown approaching Topstep MLL limit. daily_pnl={1}" -f $health.risk.mll_zone, $health.risk.daily_pnl) `
                           -State $state
                $nowActive += "mll_danger"
            }
        }
    }
}

# -- Resolve conditions that cleared ------------------------------
if ($state.active_conditions) {
    foreach ($cond in $state.active_conditions) {
        if ($cond -notin $nowActive) {
            Fire-Resolve -Code $cond -Message "$cond cleared" -State $state
        }
    }
}

$state.active_conditions = $nowActive
$state.last_check_ts = (Get-Date).ToString('o')
Save-MonitorState -State $state
