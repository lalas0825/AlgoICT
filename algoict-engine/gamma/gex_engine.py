"""
gamma/gex_engine.py
====================
GEX Engine — Pre-market orchestrator for Gamma Exposure analysis.

Runs at 5:30 AM CT to produce a GEXOverlay that the trading engine uses
to identify call/put walls, gamma regime, and confluence bonuses.

Pipeline:
    1. Fetch NQ options chain (OptionsData)
    2. Calculate GEX levels (GEXCalculator)
    3. Detect regime (RegimeDetector)
    4. Build actionable overlay (build_overlay)

Fallback: If options data is unavailable (no API key, network error),
returns an unavailable GEXOverlay that contributes 0 confluence points.

Usage:
    from gamma.gex_engine import GEXEngine
    engine = GEXEngine(spot_price=19500.0)
    overlay = engine.run_premarket_scan()
    print(overlay.call_wall)
    print(overlay.regime)

    # For main.py integration:
    from gamma.gex_engine import run_premarket_scan
    overlay = run_premarket_scan(spot_price=current_price)
"""

import logging
from typing import Optional

from gamma.gex_calculator import GEXCalculator
from gamma.regime_detector import RegimeDetector
from gamma.gex_overlay import GEXOverlay, build_overlay, unavailable_overlay

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GEXEngine
# ---------------------------------------------------------------------------

class GEXEngine:
    """
    Pre-market GEX orchestrator.

    Parameters
    ----------
    spot_price : float
        Current NQ/MNQ spot price. Used for regime detection.
    options_loader : callable | None
        Function that returns an OptionChain. If None, uses synthetic data
        for testing or falls back to unavailable overlay in production.
    near_flip_points : float
        Proximity to gamma flip for "near flip" classification.
    """

    def __init__(
        self,
        spot_price: float = 0.0,
        options_loader=None,
        near_flip_points: float = 15.0,
    ):
        self._spot = spot_price
        self._options_loader = options_loader
        self._near_flip_points = near_flip_points
        self._calculator = GEXCalculator()
        self._detector = RegimeDetector(near_flip_points=near_flip_points)
        logger.info(
            "GEXEngine initialized (spot=%.0f, loader=%s)",
            spot_price,
            options_loader is not None,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def run_premarket_scan(self, spot_price: Optional[float] = None) -> GEXOverlay:
        """
        Run full GEX scan: fetch options -> calculate -> detect -> overlay.

        Parameters
        ----------
        spot_price : float | None
            Override spot price. Uses the value from __init__ if not provided.

        Returns
        -------
        GEXOverlay — actionable GEX summary.
        """
        spot = spot_price if spot_price is not None else self._spot

        if self._options_loader is None:
            logger.warning("GEXEngine: no options_loader configured — returning unavailable overlay")
            return unavailable_overlay("No options data source configured")

        try:
            logger.info("GEXEngine: fetching options chain (spot=%.0f)", spot)
            chain = self._options_loader()

            if chain is None:
                return unavailable_overlay("Options loader returned None")

            logger.info("GEXEngine: calculating GEX levels")
            gamma_regime = self._calculator.calculate_gex(chain)

            # Inject spot price for regime detection
            gamma_regime_with_spot = self._inject_spot(gamma_regime, spot)

            logger.info("GEXEngine: detecting regime")
            regime_result = self._detector.detect(gamma_regime_with_spot)

            overlay = build_overlay(
                gamma_regime=gamma_regime_with_spot,
                spot=spot,
                regime_result=regime_result,
                near_flip_points=self._near_flip_points,
            )

            logger.info(
                "GEX scan complete: regime=%s call_wall=%.0f put_wall=%.0f flip=%.0f",
                overlay.regime, overlay.call_wall, overlay.put_wall, overlay.gamma_flip,
            )
            return overlay

        except Exception as exc:
            logger.error("GEXEngine.run_premarket_scan failed: %s", exc)
            return unavailable_overlay(str(exc))

    def update_spot(self, spot_price: float) -> None:
        """Update the spot price for subsequent scans."""
        self._spot = spot_price

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _inject_spot(self, gamma_regime, spot: float):
        """
        Inject spot price into a GammaRegime object if it doesn't have one.
        Returns the regime (possibly modified in-place).
        """
        if not hasattr(gamma_regime, "spot") or not gamma_regime.spot:
            try:
                gamma_regime.spot = spot
            except (AttributeError, TypeError):
                pass
        return gamma_regime


# ---------------------------------------------------------------------------
# Module-level function (used by main.py via _try_import)
# ---------------------------------------------------------------------------

def run_premarket_scan(
    spot_price: float = 0.0,
    options_loader=None,
    near_flip_points: float = 15.0,
) -> GEXOverlay:
    """
    Module-level convenience function for main.py integration.

    main.py calls: _GEX_RUN = _try_import("gamma.gex_engine", "run_premarket_scan")
    Then: gex_snapshot = await asyncio.get_event_loop().run_in_executor(
              None, lambda: _GEX_RUN(spot_price=current_price))
    """
    engine = GEXEngine(
        spot_price=spot_price,
        options_loader=options_loader,
        near_flip_points=near_flip_points,
    )
    return engine.run_premarket_scan()
