"""
gamma/options_data.py
======================
Load NQ options open-interest data from CSV (CBOE / Databento / internal).

Expected CSV schema (long form, one row per strike × contract type):
    date,strike,type,open_interest,implied_vol,expiry
    2024-01-02,17000,call,1250,0.18,2024-01-19
    2024-01-02,17000,put,980,0.19,2024-01-19
    ...

After loading we pivot into a wide frame keyed by strike with:
    strike, call_oi, put_oi, call_iv, put_iv, expiry, days_to_expiry

Also provides a synthetic data generator for tests / backtesting that builds
a realistic-looking option chain around a given spot price.
"""

import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class OptionChain:
    """
    A normalized NQ option chain for a single underlying date + expiry.

    Arrays are aligned: index i corresponds to strikes[i] / call_oi[i] / ...
    """
    as_of: datetime.date
    expiry: datetime.date
    spot: float
    strikes: np.ndarray         # shape (N,) float
    call_oi: np.ndarray         # shape (N,) int/float
    put_oi: np.ndarray          # shape (N,) int/float
    implied_vol: np.ndarray     # shape (N,) float — blended call/put IV
    days_to_expiry: int

    def __repr__(self) -> str:
        return (
            f"OptionChain(as_of={self.as_of} expiry={self.expiry} "
            f"spot={self.spot:.2f} n_strikes={len(self.strikes)} "
            f"dte={self.days_to_expiry})"
        )

    def total_call_oi(self) -> float:
        return float(np.sum(self.call_oi))

    def total_put_oi(self) -> float:
        return float(np.sum(self.put_oi))

    def put_call_ratio(self) -> float:
        c = self.total_call_oi()
        if c == 0:
            return float("inf")
        return self.total_put_oi() / c


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

_REQUIRED_COLS = {"date", "strike", "type", "open_interest", "implied_vol", "expiry"}


def load_options_csv(
    filepath,
    as_of_date: Optional[datetime.date] = None,
    spot: Optional[float] = None,
    expiry: Optional[datetime.date] = None,
) -> OptionChain:
    """
    Load an NQ options chain from a long-form CSV.

    Parameters
    ----------
    filepath     : str | Path — path to CSV
    as_of_date   : filter to this trading day (defaults to first date in file)
    spot         : underlying NQ price (required — not in CSV schema)
    expiry       : filter to this expiry (defaults to first expiry after as_of)

    Returns
    -------
    OptionChain — strikes and OI arrays sorted ascending by strike.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Options file not found: {filepath}")

    df = pd.read_csv(path)

    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    df["type"] = df["type"].str.lower().str.strip()

    # Filter to a single trading day
    if as_of_date is None:
        as_of_date = df["date"].min()
    df = df[df["date"] == as_of_date]
    if df.empty:
        raise ValueError(f"No rows for as_of_date={as_of_date}")

    # Filter to a single expiry
    if expiry is None:
        future_expiries = sorted(df[df["expiry"] > as_of_date]["expiry"].unique())
        if not future_expiries:
            raise ValueError(f"No expiries after {as_of_date}")
        expiry = future_expiries[0]
    df = df[df["expiry"] == expiry]
    if df.empty:
        raise ValueError(f"No rows for expiry={expiry}")

    if spot is None:
        raise ValueError("spot price is required (not derivable from options CSV)")

    # Pivot long -> wide
    chain = _pivot_long_to_wide(df)

    dte = (expiry - as_of_date).days
    return OptionChain(
        as_of=as_of_date,
        expiry=expiry,
        spot=float(spot),
        strikes=chain["strike"].to_numpy(dtype=float),
        call_oi=chain["call_oi"].to_numpy(dtype=float),
        put_oi=chain["put_oi"].to_numpy(dtype=float),
        implied_vol=chain["implied_vol"].to_numpy(dtype=float),
        days_to_expiry=int(max(dte, 1)),
    )


def _pivot_long_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot long-form (strike, type, oi, iv) into wide (strike, call_oi, put_oi, iv).
    """
    calls = df[df["type"] == "call"].set_index("strike")
    puts = df[df["type"] == "put"].set_index("strike")

    strikes = sorted(set(calls.index) | set(puts.index))

    rows = []
    for k in strikes:
        c_oi = float(calls.loc[k, "open_interest"]) if k in calls.index else 0.0
        p_oi = float(puts.loc[k, "open_interest"]) if k in puts.index else 0.0
        c_iv = float(calls.loc[k, "implied_vol"]) if k in calls.index else np.nan
        p_iv = float(puts.loc[k, "implied_vol"]) if k in puts.index else np.nan
        # Blended IV: prefer whichever side has more OI
        if np.isnan(c_iv) and np.isnan(p_iv):
            iv = 0.20  # fallback
        elif np.isnan(c_iv):
            iv = p_iv
        elif np.isnan(p_iv):
            iv = c_iv
        else:
            # OI-weighted blend
            if c_oi + p_oi == 0:
                iv = (c_iv + p_iv) / 2
            else:
                iv = (c_iv * c_oi + p_iv * p_oi) / (c_oi + p_oi)
        rows.append({
            "strike": k,
            "call_oi": c_oi,
            "put_oi": p_oi,
            "implied_vol": iv,
        })

    return pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------

def generate_synthetic_chain(
    spot: float = 17000.0,
    as_of: Optional[datetime.date] = None,
    days_to_expiry: int = 21,
    strike_spacing: float = 25.0,
    strikes_per_side: int = 20,
    implied_vol: float = 0.20,
    call_wall_strike: Optional[float] = None,
    put_wall_strike: Optional[float] = None,
    seed: int = 42,
) -> OptionChain:
    """
    Build a realistic synthetic NQ option chain around `spot`.

    The generated OI profile has:
      - peak call OI near `call_wall_strike` (default: spot + 2 × spacing)
      - peak put  OI near `put_wall_strike`  (default: spot - 2 × spacing)
      - Gaussian taper around each peak
      - realistic magnitudes (hundreds to low thousands)

    Used for tests and for backtests when real options data is unavailable.
    """
    if as_of is None:
        as_of = datetime.date.today()
    expiry = as_of + datetime.timedelta(days=days_to_expiry)

    rng = np.random.default_rng(seed)

    # Build a symmetric strike ladder around spot
    center_strike = round(spot / strike_spacing) * strike_spacing
    strikes = np.array([
        center_strike + i * strike_spacing
        for i in range(-strikes_per_side, strikes_per_side + 1)
    ], dtype=float)

    if call_wall_strike is None:
        call_wall_strike = center_strike + 2 * strike_spacing
    if put_wall_strike is None:
        put_wall_strike = center_strike - 2 * strike_spacing

    # Gaussian bell around each wall
    sigma = 3 * strike_spacing   # width of concentration
    call_oi_peak = 2500
    put_oi_peak = 2500

    call_oi = call_oi_peak * np.exp(-0.5 * ((strikes - call_wall_strike) / sigma) ** 2)
    put_oi = put_oi_peak * np.exp(-0.5 * ((strikes - put_wall_strike) / sigma) ** 2)

    # Add some noise (10% jitter) so strike selection isn't perfectly symmetric
    call_oi *= 1.0 + rng.uniform(-0.1, 0.1, size=call_oi.shape)
    put_oi *= 1.0 + rng.uniform(-0.1, 0.1, size=put_oi.shape)

    call_oi = np.maximum(call_oi, 10)     # floor
    put_oi = np.maximum(put_oi, 10)

    iv = np.full_like(strikes, implied_vol)

    return OptionChain(
        as_of=as_of,
        expiry=expiry,
        spot=float(spot),
        strikes=strikes,
        call_oi=call_oi,
        put_oi=put_oi,
        implied_vol=iv,
        days_to_expiry=days_to_expiry,
    )
