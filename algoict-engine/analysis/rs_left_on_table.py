"""Compute R-multiples and 'R left on table' for today's trades."""
import re

with open('engine.log', 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

# Today's trades (excluding the duplicate #2)
# Format: (label, direction, entry_actual, stop, contracts, fill_time_edt, exit_price, exit_time_edt, kz)
# Note: Trade #7 — limit fired at 29737.50 but FILLED at 29732.75 (small slippage). Use actual fill.
trades = [
    ("#1 London", "long",  29612.25, 29596.00, 5, "02:12:27", 29596.00, "03:00:03", "london"),
    ("#3 Ghost",  "short", 29568.75, 29584.75, 5, "08:15:42", 29515.75, "08:46:01", "london"),
    ("#4 NY AM",  "short", 29487.50, 29505.75, 4, "09:02:08", 29469.25, "09:14:28", "ny_am"),
    ("#5 NY AM",  "short", 29547.75, 29565.50, 5, "09:34:31", 29565.50, "09:35:49", "ny_am"),
    ("#6 NY AM",  "long",  29602.50, 29582.50, 4, "10:17:21", 29622.50, "10:24:28", "ny_am"),
    ("#7 NY PM",  "long",  29732.75, 29719.00, 4, "13:06:01", 29719.00, "13:06:22", "ny_pm"),
    ("#8 NY PM",  "long",  29661.25, 29626.00, 2, "13:32:23", 29696.50, "14:00:52", "ny_pm"),
    ("#9 NY PM",  "long",  29683.50, 29664.00, 4, "14:32:01", 29664.00, "14:40:57", "ny_pm"),
]

# Verify Trade #7/#8/#9 entries from log
print("=== Verifying NY PM trade entries from log ===")
for t in trades[5:8]:
    label = t[0]
    # Find EXECUTING signal preceding the exit
    pass

# Get WS 1-min OHLC bars
ws_re = re.compile(r'WS: CON\.F\.US\.MNQ\.M26 bar \[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}):00\+00:00\] '
                   r'O:([\d.]+) H:([\d.]+) L:([\d.]+) C:([\d.]+)')
bars = []
seen_ts = set()
for l in lines:
    if not l.startswith('2026-05-14'): continue
    m = ws_re.search(l)
    if m:
        utc_time = m.group(2)  # HH:MM in UTC
        utc_h = int(utc_time[:2])
        utc_m = int(utc_time[3:5])
        # EDT = UTC - 4 (during DST)
        edt_h = (utc_h - 4) % 24
        edt_ts = f"{edt_h:02d}:{utc_m:02d}"
        if edt_ts in seen_ts: continue
        seen_ts.add(edt_ts)
        bars.append({
            'edt_ts': edt_ts,
            'O': float(m.group(3)),
            'H': float(m.group(4)),
            'L': float(m.group(5)),
            'C': float(m.group(6)),
        })
bars.sort(key=lambda b: b['edt_ts'])
print(f"Loaded {len(bars)} bars for 2026-05-14")

# For each trade, find bars between fill and exit and compute MFE
def find_bar_idx(target_ts):
    """Find the bar index whose edt_ts matches target (HH:MM)."""
    for i, b in enumerate(bars):
        if b['edt_ts'] == target_ts:
            return i
    return None

print()
print(f"{'Trade':<14} {'Dir':<6} {'Entry':>9} {'Stop':>9} {'Exit':>9} {'R':>6} "
      f"{'MFE pt':>7} {'Peak R':>7} {'Capt R':>7} {'Left R':>7} {'P&L':>9}")
print('-' * 100)

total_left = 0
hit_2r = 0
hit_1r = 0
trades_count = 0

for label, direction, entry, stop, contracts, fill_t, exit_p, exit_t, kz in trades:
    R = abs(entry - stop)
    fill_hm = fill_t[:5]  # HH:MM
    exit_hm = exit_t[:5]
    fill_idx = find_bar_idx(fill_hm)
    exit_idx = find_bar_idx(exit_hm)

    if fill_idx is None or exit_idx is None:
        print(f"{label:<14} {direction:<6} {entry:>9.2f} {stop:>9.2f} {exit_p:>9.2f}  "
              f"(bars not found: fill={fill_hm}, exit={exit_hm})")
        continue

    if fill_idx > exit_idx:
        fill_idx, exit_idx = exit_idx, fill_idx

    # Compute MFE through bars[fill_idx:exit_idx+1]
    if direction == "long":
        max_high = max(b['H'] for b in bars[fill_idx:exit_idx+1])
        mfe_pts = max_high - entry
        captured_pts = exit_p - entry
    else:
        min_low = min(b['L'] for b in bars[fill_idx:exit_idx+1])
        mfe_pts = entry - min_low
        captured_pts = entry - exit_p

    peak_R = mfe_pts / R
    capt_R = captured_pts / R
    left_R = peak_R - capt_R
    pnl = captured_pts * contracts * 2  # MNQ point value
    total_left += left_R * contracts * 2 * R  # dollar equivalent

    if peak_R >= 1.0:
        hit_1r += 1
    if peak_R >= 2.0:
        hit_2r += 1
    trades_count += 1

    print(f"{label:<14} {direction:<6} {entry:>9.2f} {stop:>9.2f} {exit_p:>9.2f} "
          f"{R:>6.2f} {mfe_pts:>7.2f} {peak_R:>7.2f} {capt_R:>+7.2f} {left_R:>+7.2f} "
          f"${pnl:>+7.2f}")

print('-' * 100)
print()
print(f"Trades that reached ≥ +1R MFE: {hit_1r}/{trades_count} ({hit_1r/trades_count*100:.0f}%)")
print(f"Trades that reached ≥ +2R MFE: {hit_2r}/{trades_count} ({hit_2r/trades_count*100:.0f}%)")
print(f"Total dollars left on table (peak - capt): ${total_left:+.2f}")
