"""
backtest/data_safety.py
========================
Guard rails to prevent accidental overwrite of real market data.

Background
----------
On 2026-04-08 a run of ``python -m backtest.synthetic_data`` silently
clobbered ``data/nq_1min.csv`` (real Databento NQ 1-min OHLCV) because
the script's ``if __name__ == "__main__"`` block writes to that exact
path by default. Both ``nq_1min.csv`` and ``mnq_1min.csv`` ended up as
bit-for-bit identical random-walk data seeded with ``np.random.seed(42)``
and ``start_price=10000.0``.

This module exists so nobody (human or script) can do that again without
an explicit, loud opt-in. Every entry point that might generate synthetic
data should call ``assert_safe_write(path)`` first.

Usage
-----
    from backtest.data_safety import assert_safe_write

    def my_synthetic_generator(output_path: str) -> None:
        assert_safe_write(output_path)  # raises if overwriting real data
        # ... generate + write ...
"""

from __future__ import annotations

import os
from pathlib import Path


# Files we never want to touch without explicit confirmation.
# Add new protected paths here as we accumulate real datasets.
PROTECTED_PATHS = {
    # Databento raw OHLCV-1m dumps (the real deal)
    "data/nq_1minute.csv",
    "data/mnq_1minute.csv",
    "data/es_1minute.csv",
    "data/ym_1minute.csv",
    # Legacy short-name slots (kept protected even if currently synthetic,
    # in case a real download lands there later)
    "data/nq_1min.csv",
    "data/mnq_1min.csv",
    "data/es_1min.csv",
    "data/ym_1min.csv",
    "data/mes_1min.csv",
    "data/mym_1min.csv",
}

# Env var that lets scripts override the guard if really needed
OVERRIDE_ENV = "ALGOICT_ALLOW_OVERWRITE_REAL_DATA"


class RealDataOverwriteError(RuntimeError):
    """Raised when a script tries to overwrite a real-data file without opt-in."""


def _normalize(path: str | Path) -> str:
    """Return a forward-slash relative path for comparison against PROTECTED_PATHS."""
    p = Path(path).resolve()
    try:
        # If the path is inside the repo root, compare against repo-relative form
        repo_root = _find_repo_root(p)
        rel = p.relative_to(repo_root)
        return str(rel).replace("\\", "/")
    except (ValueError, RuntimeError):
        return str(p).replace("\\", "/")


def _find_repo_root(start: Path) -> Path:
    """Walk up until we find a directory containing both `data/` and `algoict-engine/`."""
    current = start if start.is_dir() else start.parent
    for ancestor in [current, *current.parents]:
        if (ancestor / "algoict-engine").exists() and (ancestor / "data").exists():
            return ancestor
    raise RuntimeError(f"Could not locate repo root from {start}")


def is_protected(path: str | Path) -> bool:
    """True if the given path is in the PROTECTED_PATHS set (after normalization)."""
    try:
        normalized = _normalize(path)
    except Exception:
        return False
    return normalized in PROTECTED_PATHS


def assert_safe_write(path: str | Path) -> None:
    """
    Raise if ``path`` is a protected real-data file and the override env is unset.

    Parameters
    ----------
    path : str | Path
        The file the caller wants to write to.

    Raises
    ------
    RealDataOverwriteError
        If the path is protected and the user hasn't explicitly opted in by
        setting ``ALGOICT_ALLOW_OVERWRITE_REAL_DATA=1`` in the environment.
    """
    if not is_protected(path):
        return

    if os.environ.get(OVERRIDE_ENV) == "1":
        return  # Explicit opt-in — user knows what they're doing

    raise RealDataOverwriteError(
        f"\n{'=' * 70}\n"
        f"  BLOCKED: refusing to overwrite protected real-data file\n"
        f"  path: {path}\n"
        f"{'=' * 70}\n"
        f"\n"
        f"  This file is in PROTECTED_PATHS (backtest/data_safety.py)\n"
        f"  because it's expected to contain real market data that\n"
        f"  cannot be reproduced without re-downloading / re-buying.\n"
        f"\n"
        f"  If you REALLY mean to overwrite it, set the override:\n"
        f"\n"
        f"      set {OVERRIDE_ENV}=1        (Windows cmd)\n"
        f"      $env:{OVERRIDE_ENV}='1'     (PowerShell)\n"
        f"      export {OVERRIDE_ENV}=1     (bash)\n"
        f"\n"
        f"  Or write to a different path (e.g. data/*_synthetic.csv).\n"
    )


def safe_synthetic_output_path(preferred: str | Path) -> str:
    """
    If ``preferred`` is a protected path, suggest a _synthetic suffixed sibling.
    Returns the safe path as a string.

    Example:
      preferred = "data/nq_1min.csv"
      result    = "data/nq_1min_synthetic.csv"
    """
    p = Path(preferred)
    if not is_protected(p):
        return str(p)
    return str(p.with_name(f"{p.stem}_synthetic{p.suffix}"))
