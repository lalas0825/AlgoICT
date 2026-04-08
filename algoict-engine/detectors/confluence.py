"""
detectors/confluence.py
========================
ICT 20-point confluence scorer — the brain that aggregates every signal.

Scoring (max 20 pts, min 7 to trade):

  ICT Core (14)
    +2 liquidity_grab          — sweep on the correct side (LiquidityLevel.swept)
    +2 fair_value_gap          — active FVG aligned to direction (entry inside it)
    +2 order_block             — active OB aligned to direction (entry inside it)
    +2 market_structure_shift  — MSS or CHoCH event in trade direction
    +1 kill_zone               — current bar is inside a kill zone
    +1 ote_fibonacci           — entry inside the 0.618–0.786 retracement
    +1 htf_bias_aligned        — BiasResult.direction matches trade direction
    +1 htf_ob_fvg_alignment    — entry overlaps any HTF FVG or HTF OB
    +1 target_at_pdh_pdl       — target within tolerance of a PDH/PDL/PWH/PWL

  SWC (1)
    +1 sentiment_alignment     — flag from SWC engine

  GEX (3)
    +2 gex_wall_alignment      — flag from GEX engine
    +1 gamma_regime            — flag from GEX engine

  VPIN (2)
    +1 vpin_validated_sweep    — flag from VPIN engine
    +1 vpin_quality_session    — flag from VPIN engine

Tiers
-----
  >= 12 : 'A+'        — full-size position
   9-11 : 'high'      — high confidence
    7-8 : 'standard'  — standard size
   <  7 : 'no_trade'  — skip
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from detectors.fair_value_gap import FVG
from detectors.order_block import OrderBlock
from detectors.market_structure import StructureEvent
from detectors.liquidity import LiquidityLevel
from detectors.displacement import Displacement
from timeframes.htf_bias import BiasResult

logger = logging.getLogger(__name__)

# Tolerance (relative) for "target at PDH/PDL"
TARGET_LEVEL_TOLERANCE_PCT = 0.001   # 0.1%

# Direction-mapping helpers
_LONG_BSL_TYPES = {"BSL", "PDH", "PWH", "equal_highs"}
_SHORT_SSL_TYPES = {"SSL", "PDL", "PWL", "equal_lows"}


@dataclass
class ConfluenceResult:
    """Aggregate score for a potential trade."""

    total_score: int                           # 0..20
    breakdown: dict = field(default_factory=dict)
    tier: str = "no_trade"                     # 'A+'|'high'|'standard'|'no_trade'
    trade_allowed: bool = False
    reasons: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"ConfluenceResult(score={self.total_score}/20, tier={self.tier}, "
            f"allowed={self.trade_allowed}, factors={list(self.breakdown.keys())})"
        )


class ConfluenceScorer:
    """
    Aggregates all detector outputs into a single 0-20 confluence score.

    All inputs are optional — missing data simply means the corresponding
    factor scores zero. The scorer never throws on incomplete inputs.
    """

    def __init__(self, weights: Optional[dict] = None):
        self.weights: dict = weights if weights is not None else config.CONFLUENCE_WEIGHTS

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def score(
        self,
        direction: str,                                    # 'long' | 'short'
        entry_price: float,
        target_price: Optional[float] = None,
        # ICT factors
        sweep: Optional[LiquidityLevel] = None,
        fvgs: Optional[list[FVG]] = None,
        obs: Optional[list[OrderBlock]] = None,
        structure_event: Optional[StructureEvent] = None,
        displacement: Optional[Displacement] = None,      # not scored, but logged
        kill_zone: bool = False,
        swing_high: Optional[float] = None,                # for OTE fib
        swing_low: Optional[float] = None,                 # for OTE fib
        # HTF
        htf_bias: Optional[BiasResult] = None,
        htf_fvgs: Optional[list[FVG]] = None,
        htf_obs: Optional[list[OrderBlock]] = None,
        key_levels: Optional[list[LiquidityLevel]] = None, # PDH/PDL/PWH/PWL
        # Edge modules (default 0 if not active)
        swc_sentiment_aligned: bool = False,
        gex_wall_aligned: bool = False,
        gex_regime_aligned: bool = False,
        vpin_validated_sweep: bool = False,
        vpin_quality_session: bool = False,
    ) -> ConfluenceResult:
        """
        Compute confluence for a single potential trade.

        Parameters
        ----------
        direction : 'long' | 'short' — trade direction
        entry_price : float          — proposed entry price
        target_price : float, optional — proposed target (used for PDH/PDL test)

        Returns
        -------
        ConfluenceResult
        """
        if direction not in ("long", "short"):
            raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")

        bias_dir = "bullish" if direction == "long" else "bearish"
        score = 0
        breakdown: dict = {}
        reasons: list[str] = []

        # ── 1. Liquidity grab (sweep on correct side) ──────────────────
        if sweep is not None and sweep.swept:
            sweep_ok = (
                (direction == "long" and sweep.type in _SHORT_SSL_TYPES) or
                (direction == "short" and sweep.type in _LONG_BSL_TYPES)
            )
            if sweep_ok:
                pts = self.weights["liquidity_grab"]
                score += pts
                breakdown["liquidity_grab"] = pts
                reasons.append(f"sweep of {sweep.type}")

        # ── 2. Fair Value Gap aligned with direction ───────────────────
        if fvgs:
            aligned_fvg = self._find_containing_fvg(fvgs, entry_price, bias_dir)
            if aligned_fvg is not None:
                pts = self.weights["fair_value_gap"]
                score += pts
                breakdown["fair_value_gap"] = pts
                reasons.append("entry inside FVG")

        # ── 3. Order Block aligned with direction ──────────────────────
        if obs:
            aligned_ob = self._find_containing_ob(obs, entry_price, bias_dir)
            if aligned_ob is not None:
                pts = self.weights["order_block"]
                score += pts
                breakdown["order_block"] = pts
                reasons.append("entry inside OB")

        # ── 4. Market Structure Shift / CHoCH ─────────────────────────
        if (
            structure_event is not None
            and structure_event.type in ("MSS", "CHoCH")
            and structure_event.direction == bias_dir
        ):
            pts = self.weights["market_structure_shift"]
            score += pts
            breakdown["market_structure_shift"] = pts
            reasons.append(f"{structure_event.type} {bias_dir}")

        # ── 5. Kill Zone ────────────────────────────────────────────────
        if kill_zone:
            pts = self.weights["kill_zone"]
            score += pts
            breakdown["kill_zone"] = pts
            reasons.append("kill zone")

        # ── 6. OTE Fibonacci (0.618 – 0.786 retracement) ───────────────
        if self._in_ote_zone(direction, entry_price, swing_high, swing_low):
            pts = self.weights["ote_fibonacci"]
            score += pts
            breakdown["ote_fibonacci"] = pts
            reasons.append("OTE 61.8-78.6")

        # ── 7. HTF Bias Aligned ────────────────────────────────────────
        if htf_bias is not None and htf_bias.direction == bias_dir:
            pts = self.weights["htf_bias_aligned"]
            score += pts
            breakdown["htf_bias_aligned"] = pts
            reasons.append(f"HTF bias {bias_dir}")

        # ── 8. HTF OB / FVG alignment ──────────────────────────────────
        htf_aligned = (
            (htf_fvgs and self._find_containing_fvg(htf_fvgs, entry_price, bias_dir) is not None)
            or (htf_obs and self._find_containing_ob(htf_obs, entry_price, bias_dir) is not None)
        )
        if htf_aligned:
            pts = self.weights["htf_ob_fvg_alignment"]
            score += pts
            breakdown["htf_ob_fvg_alignment"] = pts
            reasons.append("HTF OB/FVG overlap")

        # ── 9. Target at PDH / PDL / PWH / PWL ─────────────────────────
        if target_price is not None and key_levels:
            if self._target_near_key_level(target_price, key_levels):
                pts = self.weights["target_at_pdh_pdl"]
                score += pts
                breakdown["target_at_pdh_pdl"] = pts
                reasons.append("target at key level")

        # ── 10. SWC sentiment ──────────────────────────────────────────
        if swc_sentiment_aligned:
            pts = self.weights["sentiment_alignment"]
            score += pts
            breakdown["sentiment_alignment"] = pts
            reasons.append("sentiment aligned")

        # ── 11. GEX wall ───────────────────────────────────────────────
        if gex_wall_aligned:
            pts = self.weights["gex_wall_alignment"]
            score += pts
            breakdown["gex_wall_alignment"] = pts
            reasons.append("GEX wall aligned")

        # ── 12. GEX regime ─────────────────────────────────────────────
        if gex_regime_aligned:
            pts = self.weights["gamma_regime"]
            score += pts
            breakdown["gamma_regime"] = pts
            reasons.append("gamma regime")

        # ── 13. VPIN validated sweep ───────────────────────────────────
        if vpin_validated_sweep:
            pts = self.weights["vpin_validated_sweep"]
            score += pts
            breakdown["vpin_validated_sweep"] = pts
            reasons.append("VPIN sweep")

        # ── 14. VPIN quality session ───────────────────────────────────
        if vpin_quality_session:
            pts = self.weights["vpin_quality_session"]
            score += pts
            breakdown["vpin_quality_session"] = pts
            reasons.append("VPIN session")

        # ── Tier ───────────────────────────────────────────────────────
        tier = self._compute_tier(score)
        allowed = score >= config.MIN_CONFLUENCE

        result = ConfluenceResult(
            total_score=score,
            breakdown=breakdown,
            tier=tier,
            trade_allowed=allowed,
            reasons=reasons,
        )
        logger.debug("Confluence: %s", result)
        return result

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_containing_fvg(
        fvgs: list[FVG],
        price: float,
        direction: str,
    ) -> Optional[FVG]:
        """Return first unmitigated FVG of *direction* whose range contains *price*."""
        for fvg in fvgs:
            if fvg.mitigated or fvg.direction != direction:
                continue
            if fvg.bottom <= price <= fvg.top:
                return fvg
        return None

    @staticmethod
    def _find_containing_ob(
        obs: list[OrderBlock],
        price: float,
        direction: str,
    ) -> Optional[OrderBlock]:
        """Return first unmitigated OB of *direction* whose range contains *price*."""
        for ob in obs:
            if ob.mitigated or ob.direction != direction:
                continue
            if ob.low <= price <= ob.high:
                return ob
        return None

    @staticmethod
    def _in_ote_zone(
        direction: str,
        entry_price: float,
        swing_high: Optional[float],
        swing_low: Optional[float],
    ) -> bool:
        """
        ICT Optimal Trade Entry — entry inside the 0.618–0.786 fib retracement.

        Long  : impulse up from swing_low → swing_high; OTE retrace zone =
                [swing_low + 0.214*R, swing_low + 0.382*R]
                (R = swing_high - swing_low)
        Short : impulse down from swing_high → swing_low; OTE retrace zone =
                [swing_low + 0.618*R, swing_low + 0.786*R]
        """
        if swing_high is None or swing_low is None:
            return False
        rng = swing_high - swing_low
        if rng <= 0:
            return False

        if direction == "long":
            lo = swing_low + 0.214 * rng   # 78.6% retrace from high
            hi = swing_low + 0.382 * rng   # 61.8% retrace from high
            return lo <= entry_price <= hi
        else:  # short
            lo = swing_low + 0.618 * rng
            hi = swing_low + 0.786 * rng
            return lo <= entry_price <= hi

    @staticmethod
    def _target_near_key_level(
        target_price: float,
        key_levels: list[LiquidityLevel],
        tolerance_pct: float = TARGET_LEVEL_TOLERANCE_PCT,
    ) -> bool:
        """True if target is within tolerance_pct of any PDH/PDL/PWH/PWL level."""
        valid_types = {"PDH", "PDL", "PWH", "PWL"}
        for lvl in key_levels:
            if lvl.type not in valid_types:
                continue
            if lvl.price <= 0:
                continue
            if abs(target_price - lvl.price) / lvl.price <= tolerance_pct:
                return True
        return False

    @staticmethod
    def _compute_tier(score: int) -> str:
        if score >= config.CONFLUENCE_A_PLUS:
            return "A+"
        if score >= config.CONFLUENCE_HIGH:
            return "high"
        if score >= config.CONFLUENCE_STANDARD:
            return "standard"
        return "no_trade"
