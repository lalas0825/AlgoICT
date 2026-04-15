"""
sentiment/swc_engine.py
========================
Sentiment-Weighted Confluence (SWC) Engine — Pre-market orchestrator.

Runs at 6:00 AM CT to produce a DailyMoodReport that the main trading
engine uses to adjust min_confluence and position sizing for the day.

Pipeline:
    1. Economic Calendar  -> events_today, event_risk
    2. FedWatch           -> rate probabilities, hawkish/dovish shift
    3. News Scanner       -> news_sentiment (-1 to +1)
    4. Mood Synthesizer   -> DailyMoodReport (Claude API)

If any component fails, the engine falls back gracefully and returns
a conservative report that does NOT override trading parameters.

Usage:
    from sentiment.swc_engine import SWCEngine
    engine = SWCEngine()
    report = engine.run_premarket_scan()
    # report.min_confluence_override -> int
    # report.position_size_multiplier -> float
    # report.market_mood -> MarketMood enum

    # For main.py integration (called as module-level function):
    from sentiment.swc_engine import run_premarket_scan
    report = run_premarket_scan()
"""

import datetime
import logging
from typing import Optional

from sentiment.economic_calendar import (
    FinnhubCalendar,
    get_events_on_date,
    _max_risk,
)
from sentiment.confluence_adjuster import get_adjustments
from sentiment.mood_synthesizer import DailyMoodReport, MarketMood, MoodSynthesizer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SWCEngine
# ---------------------------------------------------------------------------

class SWCEngine:
    """
    Pre-market sentiment orchestrator for AlgoICT.

    Parameters
    ----------
    news_scanner : optional NewsScanner instance
        If None, news sentiment defaults to 0.0 (neutral).
    fedwatch_client : optional FedWatchClient instance
        If None, FedWatch defaults to 50% cut prob, 0 shift.
    mood_synthesizer : optional MoodSynthesizer instance
        If None, mood falls back to heuristic (no Claude API).
    """

    def __init__(
        self,
        news_scanner=None,
        fedwatch_client=None,
        mood_synthesizer: Optional[MoodSynthesizer] = None,
        finnhub_calendar: Optional[FinnhubCalendar] = None,
    ):
        self._news_scanner = news_scanner
        self._fedwatch_client = fedwatch_client
        self._mood_synthesizer = mood_synthesizer
        self._finnhub = finnhub_calendar
        self._last_news_result = None   # populated during run_premarket_scan
        logger.info(
            "SWCEngine initialized (finnhub=%s, news=%s, fedwatch=%s, mood=%s)",
            finnhub_calendar is not None,
            news_scanner is not None,
            fedwatch_client is not None,
            mood_synthesizer is not None,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def run_premarket_scan(
        self,
        date: Optional[datetime.date] = None,
    ) -> DailyMoodReport:
        """
        Run the full pre-market SWC scan for the given date.

        Parameters
        ----------
        date : datetime.date
            Date to scan. Defaults to today.

        Returns
        -------
        DailyMoodReport with complete daily assessment.
        """
        if date is None:
            date = datetime.date.today()

        logger.info("SWCEngine: pre-market scan for %s", date)

        # Step 1: Economic Calendar — Finnhub live if configured, else hardcoded
        events_today = self._get_events(date)
        if events_today:
            event_risk = _max_risk([e.risk for e in events_today])
        else:
            event_risk = "none"
        logger.info(
            "SWC: %d events today, risk=%s (%s)",
            len(events_today),
            event_risk,
            [e.name for e in events_today],
        )

        # Step 2: FedWatch
        fedwatch_cut_prob, fedwatch_shift = self._get_fedwatch()

        # Step 3: News sentiment — also capture top headlines for the mood prompt
        news_sentiment, headlines = self._get_news_sentiment_and_headlines()

        # Step 4: Mood Synthesis
        report = self._synthesize_mood(
            events=events_today,
            event_risk=event_risk,
            news_sentiment=news_sentiment,
            fedwatch_cut_prob=fedwatch_cut_prob,
            fedwatch_shift=fedwatch_shift,
            headlines=headlines,
        )

        logger.info(
            "SWC: mood=%s confidence=%s min_conf=%d pos_mult=%.2f",
            report.market_mood.value,
            report.confidence,
            report.min_confluence_override,
            report.position_size_multiplier,
        )
        return report

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _get_events(self, date: datetime.date) -> list:
        """
        Fetch today's events. Prefers the injected Finnhub client; falls back
        to the hardcoded calendar when Finnhub isn't configured or fails.
        """
        if self._finnhub is not None:
            try:
                live = self._finnhub.fetch_events(from_date=date, to_date=date)
                if live:
                    logger.info("SWC: using %d live events from Finnhub", len(live))
                    return live
                logger.info("SWC: Finnhub returned 0 events — using hardcoded calendar")
            except Exception as exc:
                logger.warning("SWC: Finnhub fetch failed (%s) — using hardcoded calendar", exc)
        # No injected client → use hardcoded calendar directly. Auto-construction
        # of a Finnhub client is opt-in via run_premarket_scan() at module level.
        return get_events_on_date(date)

    def _get_news_sentiment_and_headlines(self) -> tuple:
        """
        Fetch news sentiment + top headlines for the mood synthesizer.

        Returns (score, headlines_list). Both default to (0.0, []) if the
        scanner is unavailable or fails.
        """
        if self._news_scanner is None:
            return 0.0, []

        try:
            result = self._news_scanner.fetch_and_score()
            if result.is_valid:
                self._last_news_result = result
                top = result.top_headlines(5) if hasattr(result, "top_headlines") else []
                logger.info(
                    "SWC: news score=%.3f (%s), %d headlines",
                    result.score,
                    getattr(result, "overall_sentiment", "neutral"),
                    len(top),
                )
                return result.score, top
            logger.warning("News sentiment invalid: %s", result.error)
        except Exception as exc:
            logger.warning("News fetch failed: %s", exc)

        return 0.0, []

    def _get_fedwatch(self) -> tuple:
        """
        Fetch FedWatch probabilities.
        Returns (cut_prob, daily_shift). Falls back to (50.0, 0.0).
        """
        if self._fedwatch_client is None:
            return 50.0, 0.0

        try:
            result = self._fedwatch_client.get_probabilities()
            if result.is_valid:
                return result.cut_prob, result.daily_change
            logger.warning("FedWatch result invalid: %s", result.error)
        except Exception as exc:
            logger.warning("FedWatch fetch failed: %s", exc)

        return 50.0, 0.0

    def _get_news_sentiment(self) -> float:
        """
        Fetch news sentiment score.
        Returns 0.0 (neutral) if scanner is unavailable or fails.
        """
        if self._news_scanner is None:
            return 0.0

        try:
            result = self._news_scanner.fetch_and_score()
            if result.is_valid:
                return result.score
            logger.warning("News sentiment invalid: %s", result.error)
        except Exception as exc:
            logger.warning("News fetch failed: %s", exc)

        return 0.0

    def _synthesize_mood(
        self,
        events: list,
        event_risk: str,
        news_sentiment: float,
        fedwatch_cut_prob: float,
        fedwatch_shift: float,
        headlines: Optional[list] = None,
    ) -> DailyMoodReport:
        """
        Synthesize mood using Claude API if available, otherwise fallback.
        """
        if self._mood_synthesizer is not None:
            try:
                return self._mood_synthesizer.generate(
                    events=events,
                    event_risk=event_risk,
                    news_sentiment=news_sentiment,
                    fedwatch_cut_prob=fedwatch_cut_prob,
                    fedwatch_shift=fedwatch_shift,
                    headlines=headlines or [],
                )
            except Exception as exc:
                logger.warning("MoodSynthesizer failed: %s — using heuristic", exc)

        # Heuristic fallback: no Claude API
        return self._heuristic_mood(
            events=events,
            event_risk=event_risk,
            news_sentiment=news_sentiment,
            fedwatch_shift=fedwatch_shift,
        )

    def _heuristic_mood(
        self,
        events: list,
        event_risk: str,
        news_sentiment: float,
        fedwatch_shift: float,
    ) -> DailyMoodReport:
        """
        Simple heuristic mood determination without Claude API.
        Used as fallback when mood_synthesizer is unavailable.
        """
        try:
            adj = get_adjustments(event_risk)
        except Exception:
            adj = {"min_confluence": 7, "position_multiplier": 1.0}

        # Determine mood from available signals
        if event_risk in ("high", "extreme"):
            mood = MarketMood.EVENT_DRIVEN
            summary = f"Major event day ({event_risk} risk) — elevated caution"
        elif news_sentiment >= 0.3 and fedwatch_shift >= 0:
            mood = MarketMood.RISK_ON
            summary = "Positive news sentiment with dovish/neutral Fed backdrop"
        elif news_sentiment <= -0.3 or fedwatch_shift <= -5:
            mood = MarketMood.RISK_OFF
            summary = "Negative sentiment or hawkish Fed shift — defensive posture"
        else:
            mood = MarketMood.CHOPPY
            summary = "Mixed signals — wait for clear price action"

        event_names = [getattr(e, "name", "?") for e in events] if events else []

        return DailyMoodReport(
            market_mood=mood,
            confidence="medium" if event_risk != "none" else "low",
            one_line_summary=summary,
            key_risk=", ".join(event_names) if event_names else "No major scheduled events",
            opportunity="ICT setups in Kill Zone with confluence >= min",
            event_risk=event_risk,
            min_confluence_override=adj["min_confluence"],
            position_size_multiplier=adj["position_multiplier"],
            news_blackout_windows=[],
            news_sentiment=news_sentiment,
            fedwatch_shift=fedwatch_shift,
            source="heuristic",
        )


# ---------------------------------------------------------------------------
# Module-level function (used by main.py via _try_import)
# ---------------------------------------------------------------------------

def run_premarket_scan(
    date: Optional[datetime.date] = None,
    news_scanner=None,
    fedwatch_client=None,
    mood_synthesizer=None,
    finnhub_calendar=None,
) -> DailyMoodReport:
    """
    Module-level convenience function for main.py integration.

    If no clients are passed, this will try to auto-construct them from
    environment variables (FINNHUB_API_KEY, ALPHA_VANTAGE_API_KEY,
    ANTHROPIC_API_KEY). Each component degrades independently.
    """
    # Auto-construct from env if not provided (best-effort, never raises)
    if finnhub_calendar is None:
        try:
            finnhub_calendar = FinnhubCalendar()
        except (ImportError, ValueError) as exc:
            logger.debug("Finnhub auto-init skipped: %s", exc)
            finnhub_calendar = None

    if news_scanner is None:
        try:
            from sentiment.news_scanner import NewsScanner
            news_scanner = NewsScanner()
        except (ImportError, ValueError) as exc:
            logger.debug("NewsScanner auto-init skipped: %s", exc)
            news_scanner = None

    if mood_synthesizer is None:
        try:
            mood_synthesizer = MoodSynthesizer()
        except (ImportError, ValueError) as exc:
            logger.debug("MoodSynthesizer auto-init skipped: %s", exc)
            mood_synthesizer = None

    engine = SWCEngine(
        news_scanner=news_scanner,
        fedwatch_client=fedwatch_client,
        mood_synthesizer=mood_synthesizer,
        finnhub_calendar=finnhub_calendar,
    )
    return engine.run_premarket_scan(date=date)
