"""
gamma/gex_calculator.py
========================
Gamma Exposure (GEX) calculator for NQ options.

Core math (per strike):
    d1    = (ln(S/K) + (r + 0.5*sigma^2)*T) / (sigma*sqrt(T))
    gamma = phi(d1) / (S * sigma * sqrt(T))       # Black-Scholes gamma

    Call GEX  = gamma * call_OI * 100 * S^2 * 0.01
    Put GEX   = gamma * put_OI  * 100 * S^2 * 0.01 * -1
    Net GEX   = Call GEX + Put GEX

Key levels:
    Call Wall  = strike with max call GEX           (resistance)
    Put  Wall  = strike with min (most neg) put GEX (support)
    Gamma Flip = strike where net GEX crosses zero
                 (from positive below to negative above, or vice-versa).
                 We pick the crossing closest to the current spot.

Regime:
    spot > gamma_flip -> 'positive' (stabilizing)
    spot < gamma_flip -> 'negative' (amplifying)
    spot == gamma_flip -> 'neutral'

Assumptions
-----------
- Dealers are long calls (investors sell calls for income) -> +call_gex
- Dealers are short puts (investors buy puts for protection) -> -put_gex
- Per-strike gamma applies to both calls and puts at the same strike + IV.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)


# MNQ contract multiplier is not used here — GEX is normalized by spot^2 * 0.01
# which expresses "dollar gamma per 1% move" in the underlying.
GEX_MULTIPLIER_SCALE = 100.0           # 100 shares per option contract (equiv)
GEX_MOVE_PCT = 0.01                    # 1% move normalization
DEFAULT_RISK_FREE_RATE = 0.05          # 5% — reasonable 2024-2025 default


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GEXLevel:
    """A single strike-level GEX breakdown."""
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float
    gamma: float            # Black-Scholes gamma at this strike


@dataclass
class GammaRegime:
    """
    Full GEX snapshot returned by GEXCalculator.calculate_gex().

    All GEX values are in "dollar-gamma per 1% move" units (standard notation).
    """
    spot: float
    total_gex: float
    call_wall: float              # strike with max call GEX
    put_wall: float               # strike with min (most negative) put GEX
    gamma_flip: float             # price where net GEX crosses zero
    regime: str                   # 'positive' | 'negative' | 'neutral'
    strength: str                 # 'weak' | 'moderate' | 'strong'
    high_gex_zones: list          # strikes with |net GEX| above threshold
    levels: list                  # list[GEXLevel] — per-strike breakdown
    strikes: np.ndarray = field(repr=False)
    net_gex_array: np.ndarray = field(repr=False)

    def __repr__(self) -> str:
        return (
            f"GammaRegime(spot={self.spot:.2f} regime={self.regime} "
            f"flip={self.gamma_flip:.2f} call_wall={self.call_wall:.2f} "
            f"put_wall={self.put_wall:.2f} total=${self.total_gex:,.0f} "
            f"strength={self.strength})"
        )


# ---------------------------------------------------------------------------
# Pure Black-Scholes gamma helper (exposed for testing)
# ---------------------------------------------------------------------------

def black_scholes_gamma(
    spot: float,
    strike: float,
    days_to_expiry: float,
    implied_vol: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """
    Black-Scholes gamma for a single option.

    gamma is the same for calls and puts at the same strike/IV (it's
    a second-order greek that only depends on the underlying's position
    in the distribution).

    Parameters
    ----------
    spot            : underlying price
    strike          : option strike
    days_to_expiry  : calendar days until expiry (>= 1 enforced)
    implied_vol     : annualized IV (e.g. 0.20 for 20%)
    risk_free_rate  : annualized risk-free rate

    Returns
    -------
    float — gamma (dimensionless)
    """
    if spot <= 0:
        raise ValueError(f"spot must be positive, got {spot}")
    if strike <= 0:
        raise ValueError(f"strike must be positive, got {strike}")
    if implied_vol <= 0:
        raise ValueError(f"implied_vol must be positive, got {implied_vol}")

    T = max(days_to_expiry, 1.0) / 365.0
    sqrt_T = np.sqrt(T)
    d1 = (np.log(spot / strike) + (risk_free_rate + 0.5 * implied_vol ** 2) * T) \
        / (implied_vol * sqrt_T)
    return float(norm.pdf(d1) / (spot * implied_vol * sqrt_T))


# ---------------------------------------------------------------------------
# GEX calculator
# ---------------------------------------------------------------------------

class GEXCalculator:
    """
    Computes gamma exposure across an option chain and derives key levels.

    Usage
    -----
        from gamma.options_data import generate_synthetic_chain
        from gamma.gex_calculator import GEXCalculator

        chain = generate_synthetic_chain(spot=17000)
        calc = GEXCalculator()
        regime = calc.calculate_gex(chain)
        print(regime)  # -> GammaRegime(spot=17000.00 regime=positive ...)
    """

    def __init__(self, risk_free_rate: float = DEFAULT_RISK_FREE_RATE):
        self.risk_free_rate = risk_free_rate

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def calculate_gex(self, chain) -> GammaRegime:
        """
        Compute full GEX snapshot for an OptionChain.

        Parameters
        ----------
        chain : OptionChain (from gamma.options_data)

        Returns
        -------
        GammaRegime
        """
        spot = float(chain.spot)
        strikes = np.asarray(chain.strikes, dtype=float)
        call_oi = np.asarray(chain.call_oi, dtype=float)
        put_oi = np.asarray(chain.put_oi, dtype=float)
        iv = np.asarray(chain.implied_vol, dtype=float)
        dte = float(chain.days_to_expiry)

        return self._compute(spot, strikes, call_oi, put_oi, iv, dte)

    def calculate_gex_arrays(
        self,
        spot: float,
        strikes: np.ndarray,
        call_oi: np.ndarray,
        put_oi: np.ndarray,
        implied_vol: np.ndarray,
        days_to_expiry: float,
    ) -> GammaRegime:
        """Array-based entry point — same as calculate_gex() without OptionChain."""
        return self._compute(
            float(spot),
            np.asarray(strikes, dtype=float),
            np.asarray(call_oi, dtype=float),
            np.asarray(put_oi, dtype=float),
            np.asarray(implied_vol, dtype=float),
            float(days_to_expiry),
        )

    # ------------------------------------------------------------------ #
    # Core computation                                                     #
    # ------------------------------------------------------------------ #

    def _compute(
        self,
        spot: float,
        strikes: np.ndarray,
        call_oi: np.ndarray,
        put_oi: np.ndarray,
        iv: np.ndarray,
        dte: float,
    ) -> GammaRegime:
        if len(strikes) == 0:
            raise ValueError("Empty strike array")
        if not (len(strikes) == len(call_oi) == len(put_oi) == len(iv)):
            raise ValueError("All input arrays must have the same length")

        # Sort by strike ascending (stable order for flip detection)
        order = np.argsort(strikes)
        strikes = strikes[order]
        call_oi = call_oi[order]
        put_oi = put_oi[order]
        iv = iv[order]

        # ── 1. Black-Scholes gamma per strike ─────────────────────────────
        T = max(dte, 1.0) / 365.0
        sqrt_T = np.sqrt(T)
        # Avoid divide-by-zero on any zero IV
        iv_safe = np.where(iv <= 0, 1e-6, iv)
        d1 = (np.log(spot / strikes) + (self.risk_free_rate + 0.5 * iv_safe ** 2) * T) \
            / (iv_safe * sqrt_T)
        gamma = norm.pdf(d1) / (spot * iv_safe * sqrt_T)

        # ── 2. GEX per strike ─────────────────────────────────────────────
        multiplier = GEX_MULTIPLIER_SCALE * spot * spot * GEX_MOVE_PCT
        call_gex = gamma * call_oi * multiplier
        put_gex = gamma * put_oi * multiplier * -1.0
        net_gex = call_gex + put_gex

        # ── 3. Key strike levels ──────────────────────────────────────────
        call_wall_idx = int(np.argmax(call_gex))
        put_wall_idx = int(np.argmin(put_gex))     # most negative
        call_wall = float(strikes[call_wall_idx])
        put_wall = float(strikes[put_wall_idx])

        # ── 4. Gamma flip — zero crossing of net_gex closest to spot ─────
        gamma_flip = self._find_gamma_flip(strikes, net_gex, spot)

        # ── 5. Regime classification ──────────────────────────────────────
        if spot > gamma_flip:
            regime = "positive"
        elif spot < gamma_flip:
            regime = "negative"
        else:
            regime = "neutral"

        # ── 6. Strength from total GEX vs cross-strike std dev ───────────
        total_gex = float(np.sum(net_gex))
        gex_std = float(np.std(net_gex))
        if gex_std == 0 or not np.isfinite(gex_std):
            strength = "weak"
        elif abs(total_gex) > 2 * gex_std:
            strength = "strong"
        elif abs(total_gex) > gex_std:
            strength = "moderate"
        else:
            strength = "weak"

        # ── 7. High GEX zones (strikes > mean + 1 std of |net_gex|) ──────
        abs_gex = np.abs(net_gex)
        if abs_gex.size == 0 or np.all(abs_gex == 0):
            high_gex_zones: list = []
        else:
            threshold = float(np.mean(abs_gex) + np.std(abs_gex))
            high_gex_zones = strikes[abs_gex > threshold].tolist()

        # ── 8. Per-strike breakdown ───────────────────────────────────────
        levels = [
            GEXLevel(
                strike=float(strikes[i]),
                call_gex=float(call_gex[i]),
                put_gex=float(put_gex[i]),
                net_gex=float(net_gex[i]),
                gamma=float(gamma[i]),
            )
            for i in range(len(strikes))
        ]

        regime_obj = GammaRegime(
            spot=spot,
            total_gex=total_gex,
            call_wall=call_wall,
            put_wall=put_wall,
            gamma_flip=gamma_flip,
            regime=regime,
            strength=strength,
            high_gex_zones=high_gex_zones,
            levels=levels,
            strikes=strikes,
            net_gex_array=net_gex,
        )

        logger.debug(
            "GEX computed: spot=%.2f flip=%.2f call_wall=%.2f put_wall=%.2f "
            "total=%.2f regime=%s",
            spot, gamma_flip, call_wall, put_wall, total_gex, regime,
        )
        return regime_obj

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_gamma_flip(
        strikes: np.ndarray,
        net_gex: np.ndarray,
        spot: float,
    ) -> float:
        """
        Find the strike(s) where net GEX crosses zero, and return the crossing
        closest to the current spot. Uses linear interpolation between strikes.

        If no crossing is found:
          - All net_gex >= 0 -> flip is below the lowest strike (return strikes[0])
          - All net_gex <= 0 -> flip is above the highest strike (return strikes[-1])
          - Else fallback to spot.
        """
        if len(strikes) < 2:
            return float(spot)

        signs = np.sign(net_gex)
        # Mask zeros so they're treated as "below" (arbitrary but consistent).
        # We want strict sign changes, so look at np.diff on signs.
        diffs = np.diff(signs)
        crossing_idx = np.where(diffs != 0)[0]

        if len(crossing_idx) == 0:
            # No sign change — pick a sensible default
            if np.all(net_gex >= 0):
                return float(strikes[0])
            if np.all(net_gex <= 0):
                return float(strikes[-1])
            return float(spot)

        # Linear interp at each crossing, then pick the one closest to spot
        flips: list[float] = []
        for i in crossing_idx:
            g0, g1 = net_gex[i], net_gex[i + 1]
            k0, k1 = strikes[i], strikes[i + 1]
            if g1 == g0:
                flips.append(float((k0 + k1) / 2))
                continue
            frac = -g0 / (g1 - g0)       # where g0 + frac*(g1-g0) == 0
            flips.append(float(k0 + frac * (k1 - k0)))

        flips_arr = np.array(flips)
        closest_idx = int(np.argmin(np.abs(flips_arr - spot)))
        return float(flips_arr[closest_idx])


# ---------------------------------------------------------------------------
# Convenience functions (for simple one-shot usage)
# ---------------------------------------------------------------------------

def calculate_gex_from_chain(chain) -> GammaRegime:
    """Shortcut: use a default-configured calculator on an OptionChain."""
    return GEXCalculator().calculate_gex(chain)


def find_call_wall(strikes: np.ndarray, call_gex: np.ndarray) -> float:
    """Strike with the maximum call GEX."""
    return float(strikes[int(np.argmax(call_gex))])


def find_put_wall(strikes: np.ndarray, put_gex: np.ndarray) -> float:
    """Strike with the most negative put GEX."""
    return float(strikes[int(np.argmin(put_gex))])
