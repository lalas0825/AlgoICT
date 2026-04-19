# AlgoICT — BUILD_TASKS.md
### Sequential build guide for Claude Code
### Read CLAUDE.md first, then follow these tasks in order.
### Each task has: what to build, which skill to use, inputs, outputs, and done criteria.

---

## HOW TO USE THIS FILE

1. Load `/primer` at start of each session
2. Follow tasks IN ORDER — each depends on the previous
3. After every code change: `python -m pytest tests/ -v`
4. After every milestone: commit + update `.claude/memory/project/`
5. Never skip a task. Never jump ahead.

---

## MILESTONE 1: FOUNDATION (Tasks 1-8)
> Goal: Project scaffolded, data loaded, timeframes aggregating

### Task 1: Scaffold Project
**Skill:** `/sprint`
**Do:**
- Create full directory structure per CLAUDE.md (algoict-engine/, algoict-dashboard/, .claude/, data/)
- Create `requirements.txt`: pandas, numpy, ta-lib, scipy, supabase-py, anthropic, python-telegram-bot, pytest, flake8
- Create `config.py` with ALL constants from CLAUDE.md Risk Rules section
- Create `.env.example` with all keys listed in CLAUDE.md
- Create empty `__init__.py` in every Python package
**Done when:** `tree algoict-engine/` matches CLAUDE.md structure

### Task 2: Config Constants
**Skill:** `/python-engine`
**Do:**
- In `config.py`, define every constant as a named variable:
```python
# Risk
MAX_RISK_PER_TRADE = 250
KILL_SWITCH_LOSSES = 3
DAILY_PROFIT_CAP = 1500
HARD_CLOSE_CT = "15:00"
NEWS_BLACKOUT_MINUTES = 15
MAX_TRADES_MNQ = 3
MNQ_POINT_VALUE = 2.0
MAX_CONTRACTS_TOPSTEPX = 50
# Topstep
COMBINE_PROFIT_TARGET = 3000
COMBINE_MLL = 2000
COMBINE_DLL = 1000
# Kill Zones (EST)
NY_AM_START = "08:30"
NY_AM_END = "11:00"
SILVER_BULLET_START = "10:00"
SILVER_BULLET_END = "11:00"
# Timeframes
TF_LIST = ['1min', '5min', '15min', '1H', '4H', 'D', 'W']
# Confluence
MIN_CONFLUENCE = 7
MAX_CONFLUENCE = 20
# VPIN
VPIN_EXTREME = 0.70
VPIN_HIGH = 0.55
VPIN_ELEVATED = 0.45
VPIN_BUCKETS = 50
```
**Done when:** All constants from CLAUDE.md are in config.py, zero magic numbers elsewhere

### Task 3: Data Loader
**Skill:** `/python-engine`
**Input:** FirstRateData CSV files in `data/mnq_1min.csv`, `data/nq_1min.csv`
**Do:**
- Build `backtest/data_loader.py`
- Function `load_futures_data(filepath) -> pd.DataFrame` with DatetimeIndex (CT timezone)
- Validate: no gaps > 2 min during RTH, correct OHLCV dtypes, sorted ascending
- Function `load_sp500_daily(tickers) -> dict[str, pd.DataFrame]` using yfinance
- Print summary: date range, total candles, any gaps found
**Done when:** `python -c "from backtest.data_loader import load_futures_data; df = load_futures_data('data/mnq_1min.csv'); print(len(df))"` works

### Task 4: Timeframe Manager
**Skill:** `/python-engine`
**Input:** 1min DataFrame from data_loader
**Do:**
- Build `timeframes/tf_manager.py`
- Class `TimeframeManager` with method `aggregate(df_1min, target_tf) -> pd.DataFrame`
- Support: 5min, 15min, 1H, 4H, D, W
- Proper OHLCV aggregation (first O, max H, min L, last C, sum V)
- Cache aggregated frames to avoid recomputation
**Test:** `test_tf_manager.py` — verify 5min has 1/5 the candles, OHLCV is correct
**Done when:** All 6 timeframe aggregations produce correct candles, tests pass

### Task 5: Session Manager
**Skill:** `/python-engine`
**Do:**
- Build `timeframes/session_manager.py`
- `is_kill_zone(timestamp, zone='ny_am'|'silver_bullet') -> bool`
- `get_asian_range(date, df_1min) -> (high, low)` — 7PM-midnight EST prior day
- `get_london_session(date, df_1min) -> (high, low)` — 2AM-5AM EST
- All times in EST, configurable in config.py
**Test:** Verify known timestamps correctly identified as in/out of kill zones
**Done when:** Tests pass, session ranges match manual verification

### Task 6: HTF Bias
**Skill:** `/python-engine`
**Input:** Daily and Weekly aggregated DataFrames
**Do:**
- Build `timeframes/htf_bias.py`
- `determine_bias(df_daily, df_weekly) -> BiasResult`
- BiasResult: direction (bullish/bearish/neutral), premium_discount zone, key HTF levels
- Logic: if price below weekly OB/FVG = discount = bullish bias. Above = premium = bearish.
- Identify unmitigated weekly and daily FVGs and OBs as HTF levels
**Test:** Known weeks with clear bias (trending up/down)
**Done when:** Bias determination matches manual ICT analysis on sample weeks

### Task 7: Write Foundation Tests
**Skill:** `/python-engine`
**Do:**
- Ensure `test_tf_manager.py`, `test_session_manager.py`, `test_htf_bias.py` all exist and pass
- Run full suite: `python -m pytest tests/ -v`
**Done when:** ALL tests green

### Task 8: Init Memory
**Skill:** `/memory-manager`
**Do:**
- Create `.claude/memory/MEMORY.md` with project index
- Create `user/preferences.md` — Juan's trading preferences
- Create `reference/ict-rules.md` — placeholder for NotebookLM output
- Create `project/backtest-results.md` — empty template
- Create `feedback/loss-patterns.md` — empty template
**Done when:** Memory structure exists and is git-committed

---

## MILESTONE 2: ICT DETECTORS (Tasks 9-17)
> Goal: All 7 ICT pattern detectors working with multi-TF support

### Task 9: Swing Points Detector
**Skill:** `/python-engine`
**Do:**
- Build `detectors/swing_points.py`
- `SwingPointDetector` with configurable lookback per TF (N=2 for 5min, N=3 for 15min, N=5 for D/W)
- Detect swing highs and swing lows
- Track: price, timestamp, timeframe, whether broken or not
**Test:** Feed known price data with obvious swing points, verify detection
**Done when:** Tests pass with 100% accuracy on known data

### Task 10: Market Structure Detector
**Skill:** `/python-engine`
**Input:** Swing points from Task 9
**Do:**
- Build `detectors/market_structure.py`
- Detect: BOS (Break of Structure), CHoCH (Change of Character), MSS (Market Structure Shift)
- On 15min AND 5min timeframes
- Track current structure state: bullish/bearish/neutral
**Test:** Known MSS sequences from historical data
**Done when:** Correctly identifies BOS, CHoCH, MSS on test data

### Task 11: Fair Value Gap Detector
**Skill:** `/python-engine`
**Do:**
- Build `detectors/fair_value_gap.py`
- Detect FVGs on 5min, 15min, Daily
- Bullish FVG: candle[0].high < candle[2].low (gap up)
- Bearish FVG: candle[0].low > candle[2].high (gap down)
- Track: top, bottom, direction, TF, timestamp, mitigated status
- Update mitigation: when price fills 50%+ of the gap
**Test:** Known FVGs + mitigation scenarios
**Done when:** Detection + mitigation tracking correct

### Task 12: Order Block Detector
**Skill:** `/python-engine`
**Do:**
- Build `detectors/order_block.py`
- Detect OBs on all TFs
- Validation: must have sweep + FVG + BOS nearby + unmitigated
- Track: zone (high/low), TF, validation status
**Test:** Known OB setups
**Done when:** Tests pass

### Task 13: Liquidity Detector
**Skill:** `/python-engine`
**Do:**
- Build `detectors/liquidity.py`
- BSL/SSL (buy-side/sell-side liquidity) — clusters of equal highs/lows within 0.1%
- PDH/PDL/PWH/PWL (previous day/week high/low)
- Equal highs/lows detection
- Track: level, type, swept status
**Test:** Known liquidity levels + sweeps
**Done when:** Tests pass

### Task 14: Displacement Detector
**Skill:** `/python-engine`
**Do:**
- Build `detectors/displacement.py`
- Displacement candle: body > 2x ATR for that timeframe
- Track: direction, magnitude, timestamp
**Test:** Known displacement candles
**Done when:** Tests pass

### Task 15: Confluence Scorer
**Skill:** `/python-engine`
**Input:** All detectors from Tasks 9-14 + HTF bias
**Do:**
- Build `detectors/confluence.py`
- Score 0-20 using the table from CLAUDE.md
- Accept optional SWC, GEX, VPIN inputs (default to 0 if not available)
- Return: total score, breakdown per factor, trade/no-trade decision
**Test:** Mock data with known confluence scores
**Done when:** Scoring matches manual calculation, tests pass

### Task 16: All Detector Tests
**Skill:** `/python-engine`
**Do:**
- Ensure ALL test files exist and pass: swing, structure, fvg, ob, liquidity, confluence
- Run: `python -m pytest tests/ -v`
**Done when:** ALL green, zero failures

### Task 17: Commit Milestone 2
**Do:** `git add . && git commit -m "ICT detectors complete — 7 detectors, all tests pass"`

---

## MILESTONE 3: RISK + STRATEGIES (Tasks 18-24)
> Goal: Position sizing, risk rules, and 2 MNQ strategies coded

### Task 18: Position Sizer
**Skill:** `/python-engine`
**Do:**
- Build `risk/position_sizer.py`
- `calculate_position(risk=250, stop_points, point_value=2.0, max_contracts=50) -> PositionResult`
- floor() always round DOWN, remainder EXPANDS the stop
- Return: contracts, actual_stop, breathing_room
**Test:** Edge cases: fractional, max 50, min 1, very wide stop, very tight stop
**Done when:** Tests cover all edge cases

### Task 19: Risk Manager
**Skill:** `/python-engine`
**Do:**
- Build `risk/risk_manager.py`
- Track: daily_pnl, consecutive_losses, trades_today
- Kill switch: 3 consecutive losses → disable trading
- Profit cap: $1,500 daily → disable trading
- Hard close: 3:00 PM CT → flatten all
- News blackout: configurable windows from SWC
- Accept VPIN overrides (tighten stops, reduce size, halt)
- Accept SWC overrides (dynamic min_confluence, position multiplier)
**Test:** Simulate 3 consecutive losses → verify kill switch. Simulate $1,500 profit → verify cap.
**Done when:** All safety mechanisms verified

### Task 20: Topstep Compliance
**Skill:** `/python-engine`
**Do:**
- Build `risk/topstep_compliance.py`
- MLL: $2,000 trailing from balance high (end-of-day)
- DLL: $1,000 per day
- Max 50 MNQ contracts
- Close by 3:10 PM CT
- `check_compliance(balance, daily_pnl, positions, time) -> ComplianceResult`
**Test:** Scenarios that should trigger each rule
**Done when:** Tests pass

### Task 21: NY AM Reversal Strategy
**Skill:** `/python-engine`
**Input:** All detectors + risk manager
**Do:**
- Build `strategies/ny_am_reversal.py` — use `/prp` to plan first
- Follow the strategy definition in CLAUDE.md exactly
- Check: kill zone, HTF bias, 15min structure, 5min entry, confluence >= min
- Return Signal or None
- Max 2 trades per session
**Test:** Known historical setups where strategy should/shouldn't trigger
**Done when:** Strategy fires correctly on known setups

### Task 22: Silver Bullet Strategy
**Skill:** `/python-engine`
**Do:**
- Build `strategies/silver_bullet.py`
- 10:00-11:00 AM only, 1min FVG entry, +20-30 pts target, 100% close
- Max 1 trade per session, cancel if no fill by 10:50
**Test:** Known Silver Bullet setups
**Done when:** Tests pass

### Task 23: Strategy Tests
**Do:** Run all strategy tests + integration test (detector → strategy → risk check)
**Done when:** Full pipeline test passes

### Task 24: Commit Milestone 3
**Do:** `git commit -m "Risk engine + 2 strategies complete"`

---

## MILESTONE 4: BACKTESTER + COMBINE SIM (Tasks 25-32)
> Goal: Can backtest strategies and simulate the full Topstep Combine

### Task 25: Backtester Core
**Skill:** `/backtest`
**Do:**
- Build `backtest/backtester.py`
- Iterate historical data candle by candle
- Feed each candle to TF manager → detectors → strategies → risk manager
- Log every signal (executed or not) and every trade
- Output: list of trades with all metadata
**Done when:** Can run a full backtest on 1 year of data

### Task 26: Risk Audit
**Skill:** `/backtest`
**Do:**
- Build `backtest/risk_audit.py`
- Verify ZERO trades violate: $250 max risk, floor() sizing, kill switch, profit cap, time rules
- Report any violations with full detail
**Done when:** Audit runs and produces clean/violation report

### Task 27: Combine Simulator
**Skill:** `/backtest`
**Do:**
- Build `backtest/combine_simulator.py`
- Simulate exact Topstep $50K rules: starting $50K, MLL $2K trailing EOD, DLL $1K, target $3K
- Track daily P&L, running balance, trailing high, consistency (best day < 50%)
- Output: passed/failed, days to pass, all metrics from `/backtest` skill
**Done when:** Can simulate a full Combine and report pass/fail

### Task 28: Report Generator
**Skill:** `/backtest`
**Do:**
- Build `backtest/report.py`
- Generate: win rate, expectancy, Sharpe, max drawdown, profit factor, equity curve CSV
- Distribution: trades per KZ, per day of week, per confluence range
**Done when:** Report generates all metrics listed in `/backtest` skill

### Task 29: Run Baseline Backtests
**Skill:** `/backtest`
**Do:**
- Run NY AM Reversal on MNQ 2023-2025
- Run Silver Bullet on MNQ 2023-2025
- Run risk audit on both — ZERO violations
- Run Combine Simulator
- Save results to `.claude/memory/project/backtest-results.md`
**Done when:** Baseline numbers documented

### Task 30: SWC-A Historical
**Skill:** `/sentiment`
**Do:**
- Build `sentiment/economic_calendar.py` — parse CPI/NFP/FOMC dates from CSV
- Build `sentiment/confluence_adjuster.py` — dynamic min_confluence per event risk
- Tag all backtest days with event risk level
- Re-run backtests with Calendar Adjuster active — compare vs baseline
**Done when:** Comparison documented in memory

### Task 31: GEX-A Historical
**Skill:** `/gamma`
**Do:**
- Build `gamma/options_data.py` + `gex_calculator.py` + `regime_detector.py`
- Calculate historical GEX for backtest period
- Tag trades with GEX alignment — compare win rates aligned vs not
**Done when:** Comparison documented in memory

### Task 32: VPIN-A Historical
**Skill:** `/toxicity`
**Do:**
- Build `toxicity/volume_buckets.py` + `bulk_classifier.py` + `vpin_calculator.py`
- Calculate historical VPIN from 1min volume data
- Tag trades: VPIN level at execution time
- Calculate: $ lost during VPIN > 0.70 periods (shield value)
- Compare win rate during high VPIN vs low VPIN sessions
**Done when:** VPIN backtest value quantified and documented

---

## MILESTONE 5: LIVE CONNECTION (Tasks 33-40)
> Goal: Bot connected to TopstepX, executing on Practice Account

### Task 33: TopstepX Auth
**Skill:** `/python-engine`
**Do:**
- Build `brokers/topstepx.py` — JWT auth + token refresh
- Test: successfully authenticate and get account info
**Done when:** Auth works, token refreshes

### Task 34: TopstepX WebSocket
**Skill:** `/python-engine`
**Do:**
- Add WebSocket connection for real-time MNQ 1min data
- Parse incoming data into same DataFrame format as historical
- Handle reconnection on disconnect
**Done when:** Receiving live MNQ candles

### Task 35: TopstepX Orders
**Skill:** `/python-engine`
**Do:**
- Add REST: submit market/limit/stop orders
- Add: query positions, flatten all positions
- Test on Practice Account (NOT live)
**Done when:** Can submit and cancel orders on Practice

### Task 36: Heartbeat
**Skill:** `/python-engine`
**Do:**
- Build `core/heartbeat.py` — 5s writes to Supabase `bot_state.last_heartbeat`
- If write fails → flatten all positions immediately
- Dashboard-readable
**Done when:** Heartbeat writing, flatten tested

### Task 37: Main Entry Point
**Skill:** `/python-engine`
**Do:**
- Build `main.py` — orchestrates everything:
  1. Start heartbeat
  2. Connect TopstepX WebSocket
  3. Pre-market: run SWC scan (if modules ready)
  4. Pre-market: run GEX scan (if modules ready)
  5. Trading loop: new candle → TF manager → detectors → strategies → risk → execute
  6. Post-trade: log to Supabase, post-mortem if loss
  7. Hard close at 3:00 PM CT
- Modes: `--mode paper` (Practice) or `--mode live` (real Combine)
**Done when:** Bot runs on Practice, detects setups, logs signals

### Task 38: Supabase Setup
**Skill:** `/supabase-admin`
**Do:**
- Create Supabase project
- Create 7 tables per CLAUDE.md schema
- Set up RLS policies
- Build `db/supabase_client.py` — atomic writes for trades + bot_state
**Done when:** All tables created, writes working

### Task 39: Telegram Bot
**Skill:** `/python-engine`
**Do:**
- Build `alerts/telegram_bot.py`
- Alerts: trade execution, kill switch, profit cap, heartbeat failure, daily summary
- When SWC ready: daily mood briefing
- When GEX ready: GEX levels
- When VPIN ready: storm warning + flash crash
**Done when:** Receiving alerts on phone

### Task 40: Paper Trading Validation
**Do:**
- Run bot on Practice for minimum 5 trading days
- Compare: live signals vs what backtest would have generated
- Document any discrepancies
- Fix timing/detection issues
**Done when:** Live behavior matches backtest expectations

---

## MILESTONE 6: EDGE MODULES LIVE (Tasks 41-52)
> Goal: SWC, GEX, VPIN all running in real-time

### Task 41: SWC-B News Scanner
**Skill:** `/sentiment`
**Do:** Build `news_scanner.py` + `fedwatch.py` — fetch live data
**Done when:** Can fetch current headlines and FedWatch probabilities

### Task 42: SWC-B Mood Synthesizer
**Skill:** `/sentiment`
**Do:** Build `mood_synthesizer.py` — Claude API daily mood
**Done when:** Generates daily mood report pre-market

### Task 43: SWC-B Engine Integration
**Skill:** `/sentiment`
**Do:** Build `swc_engine.py`, integrate into `main.py` 6:00 AM scan, override risk_manager
**Done when:** Bot adjusts min_confluence on event days

### Task 44: GEX-B Live Scan
**Skill:** `/gamma`
**Do:** Build `gex_engine.py` + `gex_overlay.py` — fetch daily NQ options OI, calculate levels
**Done when:** Call wall, put wall, gamma flip calculated pre-market

### Task 45: GEX-B Confluence Integration
**Skill:** `/gamma`
**Do:** Build `gex_confluence.py`, integrate into `confluence.py`
**Done when:** Bonus points awarded when ICT + GEX align

### Task 46: VPIN-B Live Engine
**Skill:** `/toxicity`
**Do:** Connect `vpin_engine.py` to live TopstepX WebSocket
**Done when:** VPIN calculating in real-time from live trades

### Task 47: VPIN-B Shield
**Skill:** `/toxicity`
**Do:** Build `shield_actions.py` + `vpin_confluence.py`, integrate into `main.py`
**Done when:** VPIN > 0.70 = flatten + halt. Sweep + KZ quality bonus active.

### Task 48: Post-Mortem Agent
**Skill:** `/post-mortem`
**Do:** Build `agents/post_mortem.py` — Claude API analyzes every loss
**Done when:** Auto-analysis running, saving to Supabase, alerting Telegram

### Task 49: Full Pipeline Test
**Do:** Run bot 1 full week with ALL modules active on Practice
**Done when:** No crashes, all modules producing data, alerts flowing

### Task 50-52: Review + Document
- Review SWC accuracy, GEX wall accuracy, VPIN alerts
- Review post-mortem insights
- Save all findings to `.claude/memory/`

---

## MILESTONE 7: DASHBOARD (Tasks 53-60)
> Goal: Full dashboard deployed on Vercel

### Task 53: Dashboard Scaffold
**Skill:** `/bucle-agentico` → `frontend`
**Do:** Create `algoict-dashboard/` with Next.js 16, Feature-First architecture
**Reference:** `algoict_dashboard_mockup.jsx` for visual design
**Done when:** `npm run dev` shows blank dashboard

### Task 54: Main Dashboard Page
**Skill:** `frontend`
**Do:** Build main page with: PnLCard, PositionTable, RiskGauge, HeartbeatIndicator, VPINGauge, SentimentCard, GammaRegimeIndicator, ConfluenceScore — all reading from Supabase Realtime
**Done when:** Real-time data flowing from bot to dashboard

### Task 55: CandlestickChart
**Skill:** `frontend`
**Do:** Multi-TF chart with ICT annotations (FVG zones, OB zones, liquidity levels) + GEX overlay (call wall, put wall, gamma flip) + VPIN color coding
**Done when:** Chart renders with live data + annotations

### Task 56: Trades + Signals Pages
**Skill:** `frontend`
**Do:** Trade journal (filter by strategy/date/P&L), signals log (20-pt confluence breakdown)
**Done when:** Both pages showing historical data

### Task 57: Backtest + Post-Mortem Pages
**Skill:** `frontend`
**Do:** Backtest results + equity curve, post-mortem history + pattern insights
**Done when:** Pages rendering stored results

### Task 58: Strategy Lab Page
**Skill:** `frontend`
**Do:** CandidateCard, GateResults, SessionHistory components
**Done when:** Can view Lab candidates and session history

### Task 59: Controls Page
**Skill:** `frontend`
**Do:** Bot start/stop/pause, heartbeat monitor, VPIN shield status, kill switch status
**Done when:** Soft controls working via Supabase flags

### Task 60: Deploy + Mobile Test
**Skill:** `/vercel-deployer`
**Do:** Deploy to Vercel, test from phone at job site
**Done when:** Dashboard accessible on mobile with real-time data

---

## MILESTONE 8: SWING ENGINE (Tasks 61-65)

### Task 61-65: Swing HTF Strategy
**Skill:** `/python-engine`
**Do:**
- Build `alpaca_client.py`
- Build `strategies/swing_htf.py` — Weekly → Daily → 4H
- Sector filter (Tech, AI/Semis, Health, Industrials)
- Backtest on S&P 500 2+ years
- Paper trade on Alpaca 1 week
**Done when:** Swing strategy running on Alpaca paper

---

## MILESTONE 9: STRATEGY LAB (Tasks 66-75)

### Task 66-70: Lab Infrastructure
**Skill:** `/strategy-lab`
**Do:**
- Buy ES + YM data from FirstRateData
- Build: `data_splitter.py` (LOCKED test set), `walk_forward.py`, `stress_tester.py`, `cross_instrument.py`, `occam_checker.py`, `anti_overfit_gates.py`
- Tests for all components
**Done when:** 9 gates pipeline working on test data

### Task 71-75: Lab Active
**Skill:** `/strategy-lab`
**Do:**
- Build: `hypothesis_generator.py`, `lab_engine.py`, `candidate_manager.py`, `lab_report.py`
- Run first session (10 hypotheses)
- Run overnight batch (20 hypotheses)
- Review results, document in memory
**Done when:** Lab producing and filtering hypotheses

---

## MILESTONE 10: OPTIMIZATION + GO LIVE (Tasks 76-82)

### Task 76-78: Final Validation
- Run all 3 strategies + ALL modules 2 weeks paper
- Tune confluence weights from data
- Final 3-way backtest: ICT vs ICT+SWC vs ICT+SWC+GEX+VPIN

### Task 79: SWC-C Post-Release Scanner
**Skill:** `/sentiment`
**Do:** Build `release_monitor.py` — real-time economic release detection + post-release ICT scanner
**Done when:** Bot can trade the retrace after CPI/NFP spike

### Task 80: Final Combine Simulation
**Skill:** `/backtest`
**Do:** Run final Combine Simulator with ALL optimized parameters
**Done when:** Passes with margin

### Task 81: Go/No-Go Decision
**Do:**
- Review ALL data
- If pass → buy Topstep Combine ($49)
- If fail → 2 more weeks optimization

### Task 82: Start Real Combine
**Do:** Switch `main.py --mode live`, monitor daily

---

## DEPENDENCY CHAIN

```
M1 Foundation → M2 Detectors → M3 Risk+Strategies → M4 Backtester
                                                          ↓
                                                    M5 Live Connection
                                                          ↓
                                                    M6 Edge Modules
                                                          ↓
                                                    M7 Dashboard
                                                    M8 Swing (parallel)
                                                          ↓
                                                    M9 Strategy Lab
                                                          ↓
                                                    M10 Go Live
```

---

## RULES FOR CLAUDE CODE

1. **Read the relevant SKILL.md BEFORE coding.** Every custom skill has patterns, templates, and rules.
2. **TDD:** Write the test FIRST, then implement. Never the reverse.
3. **Tests after EVERY change:** `python -m pytest tests/ -v` — if it fails, fix before moving on.
4. **Never hardcode numbers.** Everything comes from `config.py`.
5. **Atomic commits.** One task = one commit. Message = task number + description.
6. **Memory updates.** After every milestone, update `.claude/memory/project/`.
7. **Risk values are SACRED.** Never modify risk constants without explicit human approval.
8. **Test Set is LOCKED.** Never access 2024-2025 data during Strategy Lab development.
9. **VPIN > 0.70 = STOP.** This override is absolute. No exceptions.

---

*"Follow the tasks. Trust the process. Build the machine."*

---

## MILESTONE 15-17 + CHART OVERLAY — post-M10 hardening (2026-04-13 → 04-19)

> Finished the live pipeline (SWC re-scans, VPIN halt, HTF bias v2, multi-KZ,
> trailing stop, _on_trade_closed SignalR wiring), validated 95% Combine pass
> rate, and shipped the full dashboard chart overlay. 1,442 tests passing.
> All work visible in `git log --oneline 7306daf..HEAD`.

### M15 — VPIN halt + SWC re-scans + ny_pm KZ
- VPIN temp halt at ≥0.70 with edge-detected Telegram alerts
- SWC pre-London + pre-NY AM re-scans (crosses Finnhub event changes)
- ny_pm kill zone added to ny_am_reversal KILL_ZONES tuple
- VPIN normalization alert fires once on True→False transition

### M16 — Live pipeline
- HTF bias v2: swing-structure primary, premium/discount secondary,
  weekly alignment multiplier, lookahead-free (last-completed bar only)
- Finnhub + Alpha Vantage wired as SWC data sources
- Dashboard auth + chart page baseline
- Supabase batch upsert for market_data

### M17a — FVG mitigation tuning
- `FVG_MITIGATION_RATIO = 0.75` — FVGs survive longer post-sweep
- `load_dotenv(override=True)` — .env wins over empty shell env vars

### M17b — MLL zones + signal dedup + audit aftermath (CRITICAL)
- 4-zone MLL ladder (normal 40% / warning 60% / caution 85% / stop).
  Validated: Combine rolling pass rate 1/10 → 19/20 on NY AM 2024.
- Single-instance PID lock (`.engine.lock`) — prevents 3-process zombie
  fires that cost 6× signal duplication on 2026-04-17
- `notify_trade_executed` split from `evaluate()` — KZ budget only
  advances on broker-confirmed fill
- `submit_limit_order` now validates against ±2% reference price —
  closes the "Invalid price outside allowed range" rejection path
- Rejected entries roll back `state.executed_signals` AND
  `strategy._last_evaluated_bar_ts` → same bar can retry
- `_flatten_all` (VPIN extreme / hard close / signalr exhausted) now
  synthesizes `_on_trade_closed` per position: risk.record_trade,
  MLL update, Supabase write, Telegram exit alert — all preserved.
  Previously silently lost on every flatten.
- Reconcile symbol normalization: `CON.F.US.MNQ.M26` vs `MNQ` no
  longer spams false ghost/orphan alerts
- `get_completed_bars(tf)` forming-bar guard wired into `_on_new_bar`
- `MAX_CONFLUENCE` derived from weight table (19, not 20 — source of
  truth single-sourced). All `/20` hardcoded strings removed.
- SWC mood gating wired into Claude path (not just heuristic fallback)
  — choppy day without event now actually penalises (9/0.75)
- VPIN hysteresis: activate ≥0.70, resume ≤0.55 (dead band prevents
  flapping)
- Trade management default reads `config.TRADE_MANAGEMENT` in both
  live and backtest → paridad
- IFVG `update_mitigation` now called in backtester (was dead code,
  caused FVG pool to grow monotonically vs live)
- Tests: 1353 → 1442 (+89), all green

### M17c — Dashboard chart overlay (4 phases)
**Migration:** `supabase/migrations/0003_bot_state_overlays.sql` adds
JSONB columns (fvg_top3, ifvg_top3, ob_top3, tracked_levels,
struct_last3, last_displacement) + scalars (bias_direction/zone,
daily/weekly_bias, active_kz, mll_zone, min_confluence, bot_status).

**Engine:** `main._populate_detector_overlay()` populates them every
5s from existing detectors. Best-effort try/except per sub-block.

**Dashboard `/chart`:**
- **Phase 1**: volume subpanel + kill-zone background shading
  (Intl-based CT projection, DST-safe) + 6 toggle checkboxes
- **Phase 2**: IFVG dashed rectangles + tracked_levels as horizontal
  priceLines (PDH/PDL blue, PWH/PWL purple, swept → zinc-500 dashed
  ✖) + MSS/BOS/CHoCH markers + displacement hook
- **Phase 3**: signal fire markers from `signals` table (FIRE + score)
- **Phase 4**: live info panel (bias, VPIN, SWC, MLL zone, P&L, KZ,
  min confluence, last displacement)

**Hooks:** `useChartAnnotations` (market_levels + trades),
`useBotStateOverlay` (bot_state JSONB Realtime), `useSignalsLive`
(signals Realtime).

### Status snapshot @ 2026-04-19
- **Tests:** 1,442 passing (engine), dashboard build ✓
- **Master HEAD:** `19d89cc`
- **Combine pass rate:** 95% (NY AM 2024 locked config)
- **Blockers para live trading:** ninguno técnico. Next step: aplicar
  migration 0003 a Supabase y arrancar bot con `python main.py --mode paper`.
- **Futuro (no blocker para Combine):** migrar repo fuera de OneDrive
  a `C:\dev\AlgoICT` (file-lock issues durante esta sesión).

---

*"Follow the tasks. Trust the process. Build the machine."*
