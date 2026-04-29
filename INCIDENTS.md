# AlgoICT — Incident Playbook

> Living record of production bugs, root causes, fixes, and how to verify
> each is still closed. Use as a diagnostic reference when something new
> breaks (chances are it's related to a bug already seen).

**Conventions**
- **Symptom** — what the user / logs showed
- **Root cause** — one-line diagnosis
- **Repro** — minimum steps to reproduce (or observational evidence if the race can't be scripted)
- **Fix** — file:function:line reference
- **Verify** — command or grep to confirm the fix is still in place
- **Tags** — searchable labels

---

## Phase 1 — 2026-04-22 (Foundational wiring)

### #001 — Phantom fill attributed +$2,154 "win"
- **Severity**: 🔴 Critical
- **Tags**: `phantom` · `fill-detection` · `risk`
- **Symptom**: Bot reported "TARGET HIT +$2,154" on NY AM 2026-04-22, but broker showed no position, no fill. Daily PnL advanced fictitiously.
- **Root cause**: `_poll_position_status` unconditionally inferred an exit when broker reported "no position + local tracked position" — didn't check whether `entry_order.filled_price is None` (limit never filled).
- **Fix**: `main.py:_poll_position_status` — branch explicitly on `filled_price is None` → CASE 1 (entry never filled, cancel resting brackets + clean state, no P&L) vs CASE 2 (filled + closed between polls, infer exit).
- **Verify**: `grep -n "entry_filled_price is None" algoict-engine/main.py`
- **Regression test**: `tests/test_trade_closed_wiring.py::TestOnBrokerFillStop`

### #002 — NY AM blocked after London (MAX_MNQ_TRADES_PER_DAY)
- **Severity**: 🟠 High
- **Tags**: `config` · `silent-block`
- **Symptom**: London took 3 trades, then bot stopped firing for NY AM entire day. No alert, no error.
- **Root cause**: `MAX_MNQ_TRADES_PER_DAY = 3` was a global cap across ALL kill zones. London filled it; NY AM was silently blocked.
- **Fix**: `config.py` — `MAX_MNQ_TRADES_PER_DAY = 15` (real filter lives in kill_switch + MLL + VPIN, not trade count).
- **Verify**: `grep "MAX_MNQ_TRADES_PER_DAY" algoict-engine/config.py` → 15

### #003 — SB never saw its own triggers (timeframe mismatch)
- **Severity**: 🔴 Critical
- **Tags**: `detectors` · `wiring`
- **Symptom**: Silver Bullet strategy defined FVG entry on 1-min + structure on 5-min, but live engine only ran FVG detector on 5-min and structure on 15-min. SB evaluate() always got empty detector output.
- **Root cause**: `main.py:_update_detectors` didn't call the 1-min FVG detector or 5-min structure detector — only the TFs used by NY AM Reversal.
- **Fix**: `main.py:_update_detectors` — added 1-min FVG + 5-min structure passes.
- **Verify**: `grep -n "timeframe.*1min\|timeframe.*5min" algoict-engine/main.py | grep -E "fvg|structure"`

### #004 — MLL trailing peak never advanced
- **Severity**: 🟠 High
- **Tags**: `risk` · `topstep`
- **Symptom**: After profitable weeks, MLL headroom was measured from the starting balance ($50K) instead of the running peak. MLL would stop trades earlier than it should.
- **Root cause**: `risk.end_of_day()` was never called — the EOD peak updater was dead code.
- **Fix**: `main.py:_reset_for_new_day` — call `components.risk.end_of_day()` before `reset_daily()`.
- **Verify**: `grep -n "components.risk.end_of_day()" algoict-engine/main.py`

---

## Phase 2 — 2026-04-23 V9 (Session recency + phantom cleanup)

### #005 — Bug A — stale cross-session structure events satisfied fresh setups
- **Severity**: 🔴 Critical
- **Tags**: `detectors` · `session-boundary`
- **Symptom**: NY AM 2026-04-23 fired phantom shorts on bull trends. Forensic: structure detector held events from previous days during warm-up; strategies consumed them as "confirmation".
- **Root cause**: `structure.get_events(timeframe=...)` returned all history, not just today's events.
- **Fix**: `strategies/silver_bullet.py` + `ny_am_reversal.py` — `session_start = ts.normalize()` filter: `fresh_events = [e for e in structure_events if e.timestamp >= session_start]`.
- **Verify**: `grep -n "session_start = ts.normalize" algoict-engine/strategies/`

### #006 — Bug B/C — phantom cleanup too aggressive (KZ-unaware TTL)
- **Severity**: 🔴 Critical
- **Tags**: `phantom` · `limit-orders`
- **Symptom**: Fire at 11:37 placed limit SELL @ 27,139.25; bar 11:41 had H=27,140.75 — would have filled. But the 11:38 poll already marked it phantom and cancelled.
- **Root cause**: `_poll_position_status` CASE 1 cancelled unfilled limits after 1 bar without respecting `LIMIT_ORDER_TTL_BARS` or KZ window.
- **Fix**: `main.py:_poll_position_status` — `if bars_pending < ttl_bars and still_in_kz: continue` before cleanup.
- **Verify**: `grep -n "still_in_kz" algoict-engine/main.py`

### #007 — Bug D — concurrent fires within same bar
- **Severity**: 🔴 Critical
- **Tags**: `concurrency` · `single-position`
- **Symptom**: 5 SB fires in ~3 minutes during NY AM 2026-04-23. Each fired a limit SELL + stop BUY bracket at the same FVG. Multiple orders alive simultaneously.
- **Root cause**: `_evaluate_strategies` didn't check `state.open_positions` before firing. Same bar could fire again if limit hadn't confirmed fill.
- **Fix**: `main.py:_evaluate_strategies` — `if state.open_positions: continue` guard before strategy.evaluate().
- **Verify**: `grep -n "single-position rule" algoict-engine/main.py`

### #008 — PWH/PDH showed forming bar instead of last completed
- **Severity**: 🟠 High
- **Tags**: `detectors` · `liquidity`
- **Symptom**: Bot logged PWH @ 27,138 but Topstep chart showed 26,883. User caught it.
- **Root cause**: `detectors/liquidity.py:get_pwh_pwl` used `df_weekly.iloc[-1]` — which includes the current forming week. Forming bar's running high ≠ last week's PWH.
- **Fix**: Added `as_of_ts` param; filters completed sessions only before `iloc[-1]`: `completed = df_weekly[df_weekly.index.map(lambda t: t.date()) < current_monday.date()]`.
- **Verify**: `grep -n "as_of_ts" algoict-engine/detectors/liquidity.py`
- **Regression**: `scripts/verify_pwh_fix.py`

---

## Phase 3 — 2026-04-24 AM (Trail + API contract)

### #009 — Bug E — trail stop fired on unfilled entry
- **Severity**: 🔴 Critical
- **Tags**: `trail` · `phantom`
- **Symptom**: Limit entry at 27,377.50 submitted 12:09 CT, never filled. Bot sent "Trailing Stop Updated 27,404 → 27,267" at 12:10 CT. Telegram misled user into thinking position was active.
- **Root cause**: `_manage_open_positions` iterated `state.open_positions` without checking whether `entry_order.filled_price` was set.
- **Fix**: `main.py:_manage_open_positions` — `entry_filled_price = getattr(entry_order, "filled_price", None); if entry_filled_price is None: continue`.
- **Verify**: `grep -n "Bug E fix" algoict-engine/main.py`

### #010 — Bug F — trail stop placed on wrong side of price
- **Severity**: 🔴 Critical
- **Tags**: `trail` · `broker-reject`
- **Symptom**: For SHORT at entry 27,377, trail logic moved stop to 27,267 (below price 27,369). Broker rejected with `errorCode=2 Order price is outside allowed range`. Old stop was ALREADY CANCELLED before replacement → position naked.
- **Root cause**: Trail tightening gate (`sp.price < current_stop` for shorts) didn't also require `new_stop > current_price`.
- **Fix**: `main.py:_manage_open_positions` — after computing `new_stop`, validate vs `last_close`:
  - LONG: `new_stop < last_close - 0.25pt`
  - SHORT: `new_stop > last_close + 0.25pt`
- **Verify**: `grep -n "Bug F fix" algoict-engine/main.py`

### #011 — Bug G — stale bear MSS satisfied bear setup mid-bull trend
- **Severity**: 🔴 Critical
- **Tags**: `detectors` · `structure` · `invalidation`
- **Symptom**: NY AM 12:09 CT fired SHORT using MSS bear from 08:55 CT — but 7 bull BOS events happened between 10:00 and 11:05 CT, invalidating any bearish structure.
- **Root cause**: Bug A (session recency) keeps the event alive (still "today"); no invalidation rule. The gate accepted the stale bear MSS because no opposite-direction invalidator was checked.
- **Fix**: `strategies/silver_bullet.py` + `ny_am_reversal.py`:
  ```
  opposite_dir = "bullish" if bias_dir == "bearish" else "bearish"
  invalidators = [e for e in fresh_events
                  if e.type in ("MSS","BOS","CHoCH")
                  and e.direction == opposite_dir
                  and e.timestamp > last_struct.timestamp]
  if invalidators: return None  # reject
  ```
- **Verify**: `grep -n "5min_struct_invalidated\|15min_struct_invalidated" algoict-engine/strategies/`

### #012 — Bug H — target order submitted in trailing mode, broker rejected
- **Severity**: 🟠 High
- **Tags**: `target` · `broker-reject`
- **Symptom**: SB target = PDL 26,680 (697pts away = 2.51% deviation). Broker rejected (>2% cap). Error log spammed every fire.
- **Root cause**: `_execute_signal` submitted a target limit regardless of `TRADE_MANAGEMENT` mode.
- **Fix**: `main.py:_execute_signal` — skip target submit when `mode != "fixed"`. Trailing stop handles exit.
- **Verify**: `grep -n "Bug H fix" algoict-engine/main.py`

### #013 — Bug I — Telegram trail alert sent despite broker rejection
- **Severity**: 🟠 High
- **Tags**: `telegram` · `trail` · `UX`
- **Symptom**: Trail alert "stop moved" sent to user even when broker returned `status=rejected`. Position naked but user thought it was protected.
- **Root cause**: Trail logic ignored `new_stop_order.status` after submit.
- **Fix**: `main.py:_manage_open_positions` — check `status == "rejected"` → log ERROR + `send_emergency_alert("POSITION UNPROTECTED")` + do NOT send the normal trail alert.
- **Verify**: `grep -n "Bug I fix\|POSITION UNPROTECTED" algoict-engine/main.py`

### #014 — Orphan cleanup was silent — user got no notification
- **Severity**: 🟠 High
- **Tags**: `telegram` · `orphan`
- **Symptom**: Reconciler detected orphan → cancelled orders → wiped local state → no alert. User kept seeing stale fire/trail alerts from earlier, thought position was still running.
- **Root cause**: Reconciler's orphan cleanup path only logged; no Telegram call.
- **Fix**: `main.py:_reconcile_positions` — `send_emergency_alert("Phantom/orphan resolved — ...")` after cleanup.
- **Verify**: `grep -n "Phantom/orphan resolved" algoict-engine/main.py`

### #015 — Bug J — `get_positions` hit non-existent endpoint (404 silently → bot blind)
- **Severity**: 🔴🔴🔴 **CATASTROPHIC**
- **Tags**: `broker-api` · `contract-drift`
- **Symptom**: **Bot reported "no open positions" all day 2026-04-24 while user had a real SHORT 3 MNQ from 27,377.50 at broker.** Reconciler mis-classified real position as orphan, wiped local state, kept running. User lost ~$171 when closing manually.
- **Root cause**: `brokers/topstepx.py:get_positions` called `GET /Position/account/{id}` which returns 404 on every TopstepX ProjectX endpoint. The 404 was handled as "no positions" (empty list).
- **Fix**: Switch to `POST /Position/searchOpen` with body `{"accountId": int}`. Response: `{"positions":[{contractId, type, size, averagePrice}], "success": true}`. Map `type=1 → long, type=2 → short` to signed contracts.
- **Verify**:
  - Code: `grep -n "/Position/searchOpen" algoict-engine/brokers/topstepx.py`
  - Tests: `tests/test_topstepx.py::TestGetPositions` (4 tests)
  - **Integration**: `TOPSTEPX_INTEGRATION=1 pytest tests/test_topstepx_live_contract.py::TestPositionEndpointContract -v`
- **Related**: Health monitor catches this now via `position_divergence` check.

### #016 — Bug K — User Hub `SubscribeAccounts` wrong signature
- **Severity**: 🔴🔴 Critical
- **Tags**: `broker-api` · `websocket`
- **Symptom**: User Hub disconnected immediately on every connect with `CompletionMessage error`. Every launch showed "3 consecutive failures → stopping reconnect. Engine will use position polling for fill detection." Polling was also broken (Bug J).
- **Root cause**: Called `conn.send("SubscribeAccounts", [self._account_id])` — but ProjectX spec says `SubscribeAccounts()` takes no args. Also missing `SubscribeOrders/Positions/Trades(int accountId)` calls for fill events.
- **Fix**: `brokers/topstepx.py:_connect_user_hub_and_listen._on_open`:
  ```python
  conn.send("SubscribeAccounts", [])
  conn.send("SubscribeOrders", [int(self._account_id)])
  conn.send("SubscribePositions", [int(self._account_id)])
  conn.send("SubscribeTrades", [int(self._account_id)])
  ```
- **Verify**: Log line `User hub: subscribed to Accounts/Orders/Positions/Trades for account ...`.

### #017 — Bug L — poll-path detected fill but didn't send "Trade Opened"
- **Severity**: 🟠 High
- **Tags**: `telegram` · `fill-detection`
- **Symptom**: User got FIRE alert + Trail alert but NO "Trade Opened" alert despite a real fill at broker.
- **Root cause**: `_on_broker_fill` only fires via User Hub (dead per Bug K). Poll-path in `_poll_position_status` detected fills but didn't trigger the trade_opened Telegram.
- **Fix**: `main.py:_poll_position_status` — when broker shows position that matches local state AND `entry_fill_confirmed=False`, mark confirmed + stamp `filled_price` from broker avgPrice + `send_trade_opened`.
- **Verify**: `grep -n "Bug L fix" algoict-engine/main.py`

---

## Phase 4 — 2026-04-24 PM (12 bugs from parallel code audit)

### #018 — C1 — signals DB writes fail NOT NULL constraint (dashboard blank forever)
- **Severity**: 🔴 Critical
- **Tags**: `database` · `schema-drift`
- **Symptom**: Dashboard `/signals` page blank. Log showed `null value in column "direction" of relation "signals" violates not-null constraint` on every write.
- **Root cause**: `main._execute_signal` wrote `"signal_type": signal.direction` — but schema column is `direction` NOT NULL (no `signal_type` column). Retry path stripped `signal_type` as "missing column" → never retried with correct field.
- **Fix**: `main.py` + `db/supabase_client.py:write_signal` — write `"direction": signal.direction` + all schema columns (strategy, kill_zone, ICT flags).
- **Verify**: `grep -n "\"direction\": signal.direction" algoict-engine/main.py`

### #019 — C2 — detector state not cleared on day reset
- **Severity**: 🔴 Critical
- **Tags**: `detectors` · `session-boundary`
- **Symptom**: Bot restart mid-day + phantom events from yesterday could "satisfy" today's setup. Session-recency filters (Bug A, C5) partially cover but warm-up replays bars with stale detector instances if cache not cleared.
- **Root cause**: `_reset_for_new_day` reset risk/strategy counters but never called `.clear()/.reset()` on detectors.
- **Fix**: `main.py:_reset_for_new_day` — loop over structure/fvg/ob/swing/displacement detectors and call their `clear()/reset()` method.
- **Verify**: `grep -n "Bug C2" algoict-engine/main.py`

### #020 — C3 — Kill switch Telegram alert was defined but never called
- **Severity**: 🔴 Critical
- **Tags**: `telegram` · `risk`
- **Symptom**: After 3 consecutive losses, kill switch activated (logged at WARNING) but no Telegram alert. User saw fire alerts going quiet and had to check logs to understand.
- **Root cause**: `alerts/telegram_bot.py:send_kill_switch_alert` existed but had zero callers across the codebase.
- **Fix**: `risk/risk_manager.py:record_trade` now returns a status dict with `kill_switch_triggered: bool` on transition. `main.py:_on_trade_closed` checks this and calls `send_kill_switch_alert(reason)`.
- **Verify**: `grep -rn "send_kill_switch_alert" algoict-engine/` (should see a caller in main.py).

### #021 — C4 — CHoCH/MSS/BOS invalidator asymmetry
- **Severity**: 🔴 Critical
- **Tags**: `strategy-gate` · `structure`
- **Symptom**: A stale bear CHoCH could never be invalidated by subsequent bull CHoCH (only MSS/BOS counted as invalidators), so `aligned` gate and `invalidators` gate didn't match.
- **Root cause**: `aligned` filter accepted `("MSS", "BOS", "CHoCH")` but invalidator filter only checked `("MSS", "BOS")`.
- **Fix**: `strategies/silver_bullet.py` + `ny_am_reversal.py` — invalidator filter now also includes `"CHoCH"` (symmetric).
- **Verify**: `grep -n '"MSS", "BOS", "CHoCH"' algoict-engine/strategies/`
- **Decision**: kept CHoCH in aligned (not removed) to preserve 7-year $673K backtest edge; only symmetrized the invalidator.

### #022 — C5 — displacement events missed session-recency filter
- **Severity**: 🔴 Critical
- **Tags**: `detectors` · `session-boundary`
- **Symptom**: NY AM Reversal could satisfy its displacement gate using yesterday's final-hour displacement events (same bug family as Bug A).
- **Root cause**: `detectors["displacement"].get_recent()` had no session_start filter in `ny_am_reversal.py`.
- **Fix**: `strategies/ny_am_reversal.py`:
  ```python
  all_disps = self.detectors["displacement"].get_recent(n=20, ...)
  displacements = [d for d in all_disps if d.timestamp >= session_start][:5]
  ```
- **Verify**: `grep -n "Bug C5" algoict-engine/strategies/ny_am_reversal.py`

### #023 — C6 — `record_trade` double-booking from triple-path detection
- **Severity**: 🔴 Critical
- **Tags**: `risk` · `idempotency`
- **Symptom**: Same exit could book P&L 2-3x (User Hub fill + poll-path inference + reconciler orphan cleanup). daily_pnl drifted, MLL zone jumped, kill switch tripped early.
- **Root cause**: `record_trade(pnl, kill_zone=None)` had no dedup key.
- **Fix**: Added optional `order_id` param + `_recorded_order_ids: set` in RiskManager. Duplicate calls short-circuit with `recorded=False`. `_on_trade_closed` skips downstream Telegram/Supabase on duplicate.
- **Verify**: `grep -n "_recorded_order_ids" algoict-engine/risk/risk_manager.py`
- **Regression**: `tests/test_trade_closed_wiring.py` — mock.ANY on order_id.

### #024 — C7 — `end_of_day` only called at next morning's reset
- **Severity**: 🟠 High
- **Tags**: `risk` · `topstep`
- **Symptom**: Hard close at 15:00 CT flattened but didn't ratchet Topstep MLL peak. If bot crashed overnight, session's profits never updated the trailing watermark.
- **Root cause**: `end_of_day()` was only called inside `_reset_for_new_day` (next morning).
- **Fix**: `main.py:_on_new_bar` hard-close path — `await _flatten_all(); components.risk.end_of_day()` immediately.
- **Verify**: `grep -n "end_of_day advanced post hard-close" algoict-engine/main.py`

### #025 — C8 — `cancel_order` return value ignored at 6 callsites
- **Severity**: 🟠 High
- **Tags**: `broker-api` · `silent-failure`
- **Symptom**: Broker could reject a cancel (order already filled, race condition, network blip) and the bot's local state still assumed success. Ghost orders could fill later and open reverse positions.
- **Root cause**: `broker.cancel_order` returns `bool`; all 6 callers ignored the return.
- **Fix**: 6 sites in `main.py` now check `if not ok:`:
  - `_on_broker_fill` counter-order cancel → `send_emergency_alert("REVERSE POSITION MAY OPEN")`
  - Reconciler orphan cleanup → ERROR log with list of failures
  - Trail stop replace → skip replace if old cancel failed (avoids double stops)
  - TTL sweep → WARNING log
  - Pre-flatten → WARNING log
- **Verify**: `grep -c "Bug C8" algoict-engine/main.py` (should be ≥5).

### #026 — H1 — Reconciler mis-classified real fresh positions as orphans
- **Severity**: 🟠 High
- **Tags**: `reconciler` · `race-condition`
- **Symptom**: Broker fill event arrived at T=0; broker's internal position-record update lagged by ~100-500ms. Reconciler running in that window saw "local yes, broker no" and orphan-cleaned a REAL position.
- **Root cause**: No grace period between position creation and orphan eligibility.
- **Fix**: `main.py:_reconcile_positions` — skip orphan cleanup for positions with `opened_at` age < 5 seconds.
- **Verify**: `grep -n "_RECONCILE_GRACE_SEC" algoict-engine/main.py`

### #027 — H2 — User Hub fill path didn't stamp `filled_price`
- **Severity**: 🟠 High
- **Tags**: `fill-detection`
- **Symptom**: User Hub fired fill event → set `entry_fill_confirmed=True` but NOT `entry_order.filled_price`. Trail logic then saw `filled_price is None` (Bug E gate) and skipped trailing.
- **Root cause**: Only the poll path (later added) stamped filled_price.
- **Fix**: `main.py:_on_broker_fill` — also mutate `entry_order.filled_price = float(fill_price)` on entry fill confirmation.
- **Verify**: `grep -n "Bug H2" algoict-engine/main.py`

### #028 — H3 — Poll-path exception silent
- **Severity**: 🟠 High
- **Tags**: `silent-failure` · `observability`
- **Symptom**: If `get_positions()` throws (network, auth, API hiccup), poll path exited via bare `except: return`. Fills went undetected, stops unmanaged, positions naked — with zero log signal.
- **Fix**: `main.py:_poll_position_status` — escalate to `WARNING` log with tracked position count.
- **Verify**: `grep -n "Bug H3" algoict-engine/main.py`

### #029 — H4 — VPIN alerts ignored TELEGRAM_VERBOSITY
- **Severity**: 🟡 Medium
- **Tags**: `telegram` · `UX`
- **Symptom**: `quiet` users got 5-10 VPIN state-change alerts per day regardless of verbosity.
- **Fix**: `alerts/telegram_bot.py:send_vpin_alert` — gate on `_should_send("vpin", (level,), min_verbosity=...)`. `extreme` + `normalized` bypass (always critical); `high`/`elevated` fire at `normal`; `calm`/`normal` only at `verbose`. Added `vpin: 600` to `TELEGRAM_THROTTLE_SEC` so oscillation doesn't flood.
- **Verify**: `grep -n "_should_send.*vpin" algoict-engine/alerts/telegram_bot.py`

### #030 — H10 — Broken swings returned as structure event candidates
- **Severity**: 🟠 High
- **Tags**: `detectors` · `structure`
- **Symptom**: `_latest_unconsumed_swing` could return a swing already marked `broken=True` (price closed through it). A new BOS event would fire on that zombie swing, producing spurious structure events that strategy gates consumed.
- **Fix**: `detectors/market_structure.py:_latest_unconsumed_swing` — add `and not getattr(sp, "broken", False)` to candidates filter.
- **Verify**: `grep -n "Bug H10" algoict-engine/detectors/market_structure.py`

### #031 — H11 — Hard close had no Telegram alert
- **Severity**: 🟡 Medium
- **Tags**: `telegram` · `UX`
- **Symptom**: User got individual WIN/LOSS alerts but no consolidated "session closed" message at 15:00 CT.
- **Fix**: `main.py:_on_new_bar` hard-close path — `send_emergency_alert("HARD CLOSE @ 3:00 PM CT — flattening N positions")` before the flatten.
- **Verify**: `grep -n "HARD CLOSE @ 3:00 PM CT" algoict-engine/main.py`

---

## Phase 5 — 2026-04-24 night (Batch 4 — systemic hardening)

Not bugs per se, but guardrails that turn entire classes of future bugs into alerts.

### #A — Fail-loud config accessor
- **What**: `config.cfg(name, default)` replaces `getattr(config, name, default)` and **WARNS once** when a missing key falls back to its default.
- **Why**: A renamed or deleted config key silently ran with a stale hardcoded default forever. Future bugs of this shape surface in logs immediately.
- **Scanner**: `scripts/audit_config_defaults.py` reports any `cfg()`/`getattr()` call site whose key isn't defined in `config.py`. Exit code 1 on drift → CI gate.
- **Verify**: `python scripts/audit_config_defaults.py` (should print `OK: all config accessor keys are defined`).

### #B — TopstepX live contract tests
- **What**: `tests/test_topstepx_live_contract.py` — 5 opt-in tests that hit the real TopstepX API with read-only ops (auth, `/Position/searchOpen`, `/Order/searchOpen`, `/Contract/search`). Includes a **regression test that `GET /Position/account/{id}` still returns 404** so we notice if the broker ever "fixes" it.
- **Why**: Bug J (404 endpoint) + Bug K (wrong WS signature) would have been caught in CI on day 1 instead of surviving for days in production.
- **Run**: `TOPSTEPX_INTEGRATION=1 pytest tests/test_topstepx_live_contract.py -v`

### #C — Health JSON + external monitor
- **What**: Bot writes `.health.json` every 10s (`core/health.py:HealthWriter`). PowerShell monitor (`scripts/monitor.ps1`) runs every 60s via Windows Task Scheduler, alerts via Telegram + local log fallback on:
  - `bot_dead` / `heartbeat_stale` / `ws_feed_stale` / `user_hub_dead`
  - `position_divergence` (local vs broker — Bug J regression catch)
  - `kill_switch` / `mll_danger`
- **Why**: The bot can't alert on its own death or divergence. This is the missing independent watchdog.
- **Install**: `powershell -ExecutionPolicy Bypass -File scripts\install_monitor.ps1`
- **Verify**: `Get-ScheduledTask -TaskName AlgoICT-Monitor` → State=Ready.
- **Logs**: `Get-Content .monitor_alerts.log -Tail 20 -Wait`

### #D — Silent `.debug` escalation in critical paths
- **What**: Reconciler `get_positions` failure + KZ counter rollback failure escalated from `logger.debug` to `logger.warning`.
- **Why**: During Bug J the 404 cascaded silently. These paths now emit visible log lines.

### #E — Reconciler 5-second grace period
- **What**: `main.py:_reconcile_positions` — skip orphan cleanup for positions opened <5s ago.
- **Why**: Broker position-record update can lag a fill event by ~100-500ms. Without grace, reconciler could wipe a real fresh position.

---

## Diagnostic flow — when something breaks in production

**First check (30s)**:
```bash
# Is the bot alive?
tasklist | grep python

# Is the health snapshot fresh?
cat algoict-engine/.health.json | grep ts

# Any recent monitor alerts?
Get-Content algoict-engine/.monitor_alerts.log -Tail 20
```

**Second check (2 min)**:
```bash
# Tail the engine log for critical/error lines
Get-Content algoict-engine/engine.log -Tail 50 | Select-String "CRITICAL|ERROR|NAKED|ORPHAN|phantom"

# Verify broker state matches local
# (manually log into Topstep TWX or hit /Position/searchOpen from a shell)
```

**Third check — is it a known bug?**
Grep this file by symptom keyword:
```bash
grep -i "phantom\|stale\|naked\|orphan\|divergence" INCIDENTS.md
```

If yes → apply the verify command for that bug to confirm the fix is still in place. If the fix regressed (someone reverted it), `git log -p -- <file>` will show when.

If no → this is a new bug. Capture:
1. Exact timestamp from log
2. `.health.json` snapshot at time of failure
3. Engine log window (±5 min around failure)
4. Broker GUI state

Then add a new #NNN entry to this file with symptom / root cause / fix / verify.

---

## Phase 6 — 2026-04-29 (Connection resilience)

### #032 — WS market hub silent death (London KZ blackout)
- **Severity**: 🔴 Critical
- **Tags**: `ws` · `signalr` · `connection-loss` · `silent-failure`
- **Symptom**: Bot ran the entire London KZ (01:00-04:00 CT) blind on 2026-04-29. Last bar received at 00:13 CT; bot still "alive" per heartbeat (User Hub on a separate connection that detected and reconnected). Asian-session AH@27,294 swept at 23:10 CT (DOWN-wick, bullish setup) — bot saw the sweep but then went silent. Daily P&L $0, 0 trades, 0 evaluations during London.
- **Root cause**: SignalR market hub TCP connection forcibly closed by remote at 01:12 ET (`WinError 10054 ConnectionResetError`). The third-party `signalrcore` library logged the error internally but **did NOT fire our `_on_close` / `_on_error` callbacks**. The `disconnected` asyncio.Event never set, the listener loop kept spinning waiting for bars that would never arrive, and `_ws_listener_loop`'s reconnect logic never triggered (it depends on a return-from-listener or exception, neither of which happened).
- **Repro**: hard to script — depends on signalrcore swallowing the underlying ConnectionResetError. Observational evidence: search engine.log for `Receive error: [WinError 10054]` followed by NO subsequent `SignalR: market hub disconnected` line.
- **Fix**: `brokers/topstepx.py:_signalr_connect_and_listen` — added independent stale-bar watchdog inside the inner while loop. Tracks `last_emit_ts` (atomic float in a list, no lock — see #033). If no bars emit for `WS_BAR_STALE_THRESHOLD_S` (default 600s = 10 min) AND the CME is not in a known closed window (`_cme_market_closed_now()` mirrors monitor.ps1 schedule), forces `disconnected.set()` to break the inner loop. Outer `_ws_listener_loop` then runs its retry/backoff and reconnects.
- **Verify**: `grep -n "WATCHDOG — no bars" algoict-engine/brokers/topstepx.py`
- **Commit**: `d2b69f6` (watchdog) + `55fc604` (deadlock fix, see #033)

### #033 — WS watchdog deadlock — bot zombie 30+ min
- **Severity**: 🔴 Critical (self-inflicted while fixing #032)
- **Tags**: `deadlock` · `threading-lock` · `non-reentrant` · `asyncio-freeze`
- **Symptom**: First relaunch with the #032 watchdog froze 30+ min after boot. Process alive in tasklist, `.health.json` mtime stuck at first-bar timestamp, engine.log last entry was a `WS: ... bar [...]` line followed by complete silence. External monitor fired `bot_dead` alert at 60s threshold, then again at 15min throttle.
- **Root cause**: My #032 watchdog patch added `with bar_lock: last_emit_ts[0] = time.time()` inside `_emit_bar`. But `_emit_bar` is called from inside the bar-flush path which already holds `bar_lock`:

  ```python
  with bar_lock:                            # ← outer lock held
      for cid, s in list(bar_state.items()):
          if s["count"] > 0 and s["minute_ts"] < current_minute:
              old = _flush_bar(cid)
              if old:
                  _emit_bar(old)             # ← tried bar_lock again
                                             #   threading.Lock is NOT
                                             #   reentrant → freeze
  ```

  `threading.Lock` is non-reentrant. Same thread acquiring it twice blocks forever. Asyncio loop trapped inside `_emit_bar` → no more bar processing, no health.json updates, no strategy evals.
- **Repro**: launch bot with the d2b69f6 version of `_emit_bar`. As soon as the bar-flush path emits one bar, the loop deadlocks. Bot is alive in tasklist but does nothing.
- **Fix**:
  1. Drop `with bar_lock` from `_emit_bar` — `last_emit_ts[0] = time.time()` is a single-attribute write to a list element, atomic under CPython's GIL.
  2. (Defensive #034) Convert `bar_lock` from `threading.Lock` to `threading.RLock` so any future nested acquisition by the same thread doesn't freeze. `RLock` allows reentrant acquisition with no perf penalty in uncontended path.
- **Verify**: `grep -n "Atomic store — DO NOT wrap in" algoict-engine/brokers/topstepx.py` and `grep -n "threading.RLock" algoict-engine/brokers/topstepx.py`
- **Commit**: `55fc604` (lock removed) + (RLock conversion in same commit family)

### #034 — DEFENSIVE: asyncio liveness watchdog (separate thread)
- **Severity**: 🟢 Hardening (no incident yet — preventive)
- **Tags**: `defensive` · `asyncio-freeze` · `watchdog` · `self-recovery`
- **Why**: #033 proved that an asyncio deadlock leaves the process technically alive but completely non-functional. The bot can't detect its own asyncio freeze (the very loop that would detect it is the one that's frozen). External monitor catches it eventually but only after 60s+, and a paused or disabled monitor would miss it entirely.
- **Mechanism**: Independent `threading.Thread` (daemon, pure threading no asyncio) checks an `_ASYNCIO_HEARTBEAT_TS` shared float every 30s. An asyncio task updates the timestamp every 5s. If the timestamp hasn't advanced in 90s → `os._exit(2)` — bypasses Python cleanup (which may also hang if asyncio is hung) and lets the OS reap the process. External monitor + Telegram alert fires within 60s. User (or task scheduler) relaunches with fresh state.
- **Trade-off**: 90s window between freeze and self-kill is intentional — short enough that one missed bar window is rare, long enough to absorb legitimate slow ops (e.g. Supabase backpressure during warmup batch upserts).
- **Verify**: `grep -n "Asyncio liveness watchdog started" algoict-engine/main.py` and check for `[INFO] Asyncio liveness watchdog started (threshold=90s` in engine.log on next launch.
- **Commit**: same family as #033 (defensive companion)

### #035 — DEFENSIVE: bar_lock RLock conversion
- **Severity**: 🟢 Hardening
- **Tags**: `defensive` · `lock` · `reentrancy`
- **Why**: After #033 burned us with a non-reentrant `threading.Lock` deadlock, any future patch that adds a `with bar_lock:` inside a function called from the lock-held flush path would hit the same trap. RLock is reentrant — same-thread nested acquisition just bumps a counter, no deadlock. Same throughput as Lock for single-acquisition (the common case). Pure upside.
- **Verify**: `grep -n "bar_lock = threading.RLock" algoict-engine/brokers/topstepx.py`

---

## Summary

| Phase | Date | Bugs fixed | Critical |
|---|---|---|---|
| 1 | 2026-04-22 | 4 (#001-004) | 2 |
| 2 | 2026-04-23 V9 | 4 (#005-008) | 3 |
| 3 | 2026-04-24 AM | 9 (#009-017) | 5 |
| 4 | 2026-04-24 PM | 14 (#018-031) | 7 |
| 5 | 2026-04-24 night | 5 hardening systems | — |
| 6 | 2026-04-29 | 2 incidents (#032-033) + 2 hardening (#034-035) | 2 |

**Total: 33 numbered incidents + 7 defensive systems + 2 earlier foundational.**

The gap between "counted 31 here" and "33 in the commit messages" is because #002-#004 were batched as wiring fixes and some minor issues (like the `.engine.lock` fix from 2026-04-17) predate this log. All listed above were verified closed as of commit `4293eee`.
