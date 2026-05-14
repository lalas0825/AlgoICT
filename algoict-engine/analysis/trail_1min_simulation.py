"""Simulate 1-min swing trail vs current 5-min trail for today's trades."""
import re

with open('engine.log', 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

# Parse all 1-min WS bars today
ws_re = re.compile(r'WS: CON\.F\.US\.MNQ\.M26 bar \[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}):00\+00:00\] '
                   r'O:([\d.]+) H:([\d.]+) L:([\d.]+) C:([\d.]+)')
bars = []
seen = set()
for l in lines:
    if not l.startswith('2026-05-14'): continue
    m = ws_re.search(l)
    if m:
        utc_h = int(m.group(2)[:2])
        utc_m = int(m.group(2)[3:5])
        edt_h = (utc_h - 4) % 24
        edt_min = utc_h * 60 + utc_m - 4 * 60  # for sorting
        key = f"{edt_h:02d}:{utc_m:02d}"
        if key in seen: continue
        seen.add(key)
        bars.append({
            'edt_ts': key,
            'edt_min': edt_min,
            'O': float(m.group(3)),
            'H': float(m.group(4)),
            'L': float(m.group(5)),
            'C': float(m.group(6)),
        })
bars.sort(key=lambda b: b['edt_min'])
ts_to_idx = {b['edt_ts']: i for i, b in enumerate(bars)}

# Trades (excluding dup #2) — same data as rs_left_on_table.py
trades = [
    ("#1 London", "long",  29612.25, 29596.00, 5, "02:12", 29596.00, "03:00"),
    ("#3 Ghost",  "short", 29568.75, 29584.75, 5, "08:15", 29515.75, "08:46"),
    ("#4 NY AM",  "short", 29487.50, 29505.75, 4, "09:02", 29469.25, "09:14"),
    ("#5 NY AM",  "short", 29547.75, 29565.50, 5, "09:34", 29565.50, "09:35"),
    ("#6 NY AM",  "long",  29602.50, 29582.50, 4, "10:17", 29622.50, "10:24"),
    ("#7 NY PM",  "long",  29732.75, 29719.00, 4, "13:06", 29719.00, "13:06"),
    ("#8 NY PM",  "long",  29661.25, 29626.00, 2, "13:32", 29696.50, "14:00"),
    ("#9 NY PM",  "long",  29683.50, 29664.00, 4, "14:32", 29664.00, "14:40"),
]


def simulate_trail(entry_idx, end_idx, entry_price, initial_stop, direction, max_bars=300):
    """Simulate trail with 1-min swings + ratchet. Returns (exit_price, exit_idx, exit_reason)."""
    stop = initial_stop
    R = abs(entry_price - initial_stop)
    peak_R = 0.0
    ratcheted = False
    last_swing_idx = -1  # index of last detected 1-min swing

    for i in range(entry_idx + 1, min(end_idx + 50, len(bars))):
        bar = bars[i]

        # 1. Stop hit check (intra-bar)
        if direction == "long":
            if bar['L'] <= stop:
                return stop, i, f"stop_hit @ {stop:.2f}"
        else:
            if bar['H'] >= stop:
                return stop, i, f"stop_hit @ {stop:.2f}"

        # 2. Peak R update (use bar high for long, low for short)
        if direction == "long":
            ex = bar['H'] - entry_price
        else:
            ex = entry_price - bar['L']
        bar_R = ex / R
        peak_R = max(peak_R, bar_R)

        # 3. Ratchet at peak ≥ 2R → lock +1R
        if peak_R >= 2.0 and not ratcheted:
            if direction == "long":
                ratchet_target = entry_price + R
                # Safety check: ratchet must be BELOW current bar's close (long stop sell)
                if ratchet_target > stop and ratchet_target < bar['C']:
                    stop = ratchet_target
                    ratcheted = True
            else:
                ratchet_target = entry_price - R
                # Safety check: ratchet must be ABOVE current bar's close (short stop buy)
                if ratchet_target < stop and ratchet_target > bar['C']:
                    stop = ratchet_target
                    ratcheted = True

        # 4. 1-min swing trail (3-bar pivot — bar i-1 confirmed at bar i)
        if i >= entry_idx + 2:
            mid = bars[i-1]
            prev = bars[i-2]
            curr = bars[i]
            if direction == "long":
                # 1-min swing low at i-1
                if mid['L'] < prev['L'] and mid['L'] < curr['L']:
                    sw = mid['L']
                    # Tighter (higher) and below current price
                    if sw > stop and sw < bar['C']:
                        stop = sw
            else:
                # 1-min swing high at i-1
                if mid['H'] > prev['H'] and mid['H'] > curr['H']:
                    sw = mid['H']
                    # Tighter (lower) and above current price
                    if sw < stop and sw > bar['C']:
                        stop = sw

    # Exhausted: exit at last bar close
    return bars[min(end_idx + 5, len(bars) - 1)]['C'], min(end_idx + 5, len(bars) - 1), "session_end_proxy"


print(f"{'Trade':<12} {'Dir':<6} {'Actual exit':>12} {'Actual R':>10} {'Sim 1m exit':>12} {'Sim R':>9} {'Sim P&L':>10} {'ΔP&L':>10}")
print('-' * 90)

actual_total = 0
sim_total = 0
for label, direction, entry, stop, contracts, fill_t, exit_p, exit_t in trades:
    entry_idx = ts_to_idx.get(fill_t)
    exit_idx = ts_to_idx.get(exit_t)
    if entry_idx is None or exit_idx is None:
        print(f"{label:<12}  bars not found: fill={fill_t} exit={exit_t}")
        continue

    R = abs(entry - stop)
    # Actual
    if direction == "long":
        actual_pts = exit_p - entry
    else:
        actual_pts = entry - exit_p
    actual_R = actual_pts / R
    actual_pnl = actual_pts * contracts * 2

    # Simulated 1-min trail
    sim_exit, sim_idx, reason = simulate_trail(entry_idx, exit_idx, entry, stop, direction)
    if direction == "long":
        sim_pts = sim_exit - entry
    else:
        sim_pts = entry - sim_exit
    sim_R = sim_pts / R
    sim_pnl = sim_pts * contracts * 2
    delta = sim_pnl - actual_pnl

    actual_total += actual_pnl
    sim_total += sim_pnl

    print(f"{label:<12} {direction:<6} {exit_p:>12.2f} {actual_R:>+10.2f} "
          f"{sim_exit:>12.2f} {sim_R:>+9.2f} ${sim_pnl:>+9.2f} ${delta:>+9.2f}")

print('-' * 90)
print(f"{'TOTAL':<60} ${actual_total:>+9.2f}    ${sim_total:>+9.2f}  Δ=${sim_total-actual_total:+.2f}")
