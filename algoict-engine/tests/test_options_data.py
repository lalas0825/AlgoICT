"""
tests/test_options_data.py
===========================
Tests for gamma/options_data.py
"""

import datetime
import tempfile
import os

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gamma.options_data import (
    OptionChain,
    load_options_csv,
    generate_synthetic_chain,
)


# ---------------------------------------------------------------------------
# Synthetic chain generator
# ---------------------------------------------------------------------------

class TestSyntheticChain:
    def test_returns_option_chain(self):
        chain = generate_synthetic_chain(spot=17000.0)
        assert isinstance(chain, OptionChain)

    def test_spot_preserved(self):
        chain = generate_synthetic_chain(spot=17500.0)
        assert chain.spot == 17500.0

    def test_strikes_length_matches_oi(self):
        chain = generate_synthetic_chain(spot=17000.0, strikes_per_side=10)
        assert len(chain.strikes) == len(chain.call_oi)
        assert len(chain.strikes) == len(chain.put_oi)
        assert len(chain.strikes) == len(chain.implied_vol)

    def test_strikes_count(self):
        chain = generate_synthetic_chain(spot=17000.0, strikes_per_side=20)
        # 2*20 + 1 (center) = 41
        assert len(chain.strikes) == 41

    def test_strikes_sorted_ascending(self):
        chain = generate_synthetic_chain(spot=17000.0)
        assert np.all(np.diff(chain.strikes) > 0)

    def test_strikes_centered_on_spot(self):
        chain = generate_synthetic_chain(spot=17000.0, strike_spacing=25.0)
        center = (chain.strikes[0] + chain.strikes[-1]) / 2
        assert abs(center - 17000.0) <= 25.0

    def test_call_wall_near_specified(self):
        chain = generate_synthetic_chain(
            spot=17000.0,
            call_wall_strike=17050.0,
            strike_spacing=25.0,
        )
        # Peak call OI should be at or near 17050
        peak_idx = int(np.argmax(chain.call_oi))
        assert abs(chain.strikes[peak_idx] - 17050.0) <= 25.0

    def test_put_wall_near_specified(self):
        chain = generate_synthetic_chain(
            spot=17000.0,
            put_wall_strike=16950.0,
            strike_spacing=25.0,
        )
        peak_idx = int(np.argmax(chain.put_oi))
        assert abs(chain.strikes[peak_idx] - 16950.0) <= 25.0

    def test_implied_vol_constant(self):
        chain = generate_synthetic_chain(spot=17000.0, implied_vol=0.22)
        assert np.all(np.isclose(chain.implied_vol, 0.22))

    def test_days_to_expiry(self):
        chain = generate_synthetic_chain(spot=17000.0, days_to_expiry=30)
        assert chain.days_to_expiry == 30

    def test_expiry_date_correct(self):
        as_of = datetime.date(2024, 1, 2)
        chain = generate_synthetic_chain(spot=17000.0, as_of=as_of, days_to_expiry=21)
        assert chain.expiry == datetime.date(2024, 1, 23)

    def test_oi_positive(self):
        chain = generate_synthetic_chain(spot=17000.0)
        assert np.all(chain.call_oi > 0)
        assert np.all(chain.put_oi > 0)

    def test_put_call_ratio_computed(self):
        chain = generate_synthetic_chain(spot=17000.0)
        pcr = chain.put_call_ratio()
        assert pcr > 0
        assert np.isfinite(pcr)

    def test_seed_reproducibility(self):
        c1 = generate_synthetic_chain(spot=17000.0, seed=42)
        c2 = generate_synthetic_chain(spot=17000.0, seed=42)
        assert np.allclose(c1.call_oi, c2.call_oi)
        assert np.allclose(c1.put_oi, c2.put_oi)


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def _write_sample_csv() -> str:
    """Write a minimal valid options CSV to a temp file and return path."""
    rows = [
        # Jan 2, expiry Jan 19
        {"date": "2024-01-02", "strike": 16900, "type": "call",
         "open_interest": 500, "implied_vol": 0.20, "expiry": "2024-01-19"},
        {"date": "2024-01-02", "strike": 16900, "type": "put",
         "open_interest": 1200, "implied_vol": 0.21, "expiry": "2024-01-19"},
        {"date": "2024-01-02", "strike": 17000, "type": "call",
         "open_interest": 1500, "implied_vol": 0.19, "expiry": "2024-01-19"},
        {"date": "2024-01-02", "strike": 17000, "type": "put",
         "open_interest": 2000, "implied_vol": 0.20, "expiry": "2024-01-19"},
        {"date": "2024-01-02", "strike": 17100, "type": "call",
         "open_interest": 2500, "implied_vol": 0.18, "expiry": "2024-01-19"},
        {"date": "2024-01-02", "strike": 17100, "type": "put",
         "open_interest": 800, "implied_vol": 0.19, "expiry": "2024-01-19"},
    ]
    df = pd.DataFrame(rows)
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(f.name, index=False)
    f.close()
    return f.name


class TestCSVLoading:
    def test_loads_valid_csv(self):
        path = _write_sample_csv()
        try:
            chain = load_options_csv(path, spot=17000.0)
            assert isinstance(chain, OptionChain)
        finally:
            os.unlink(path)

    def test_strikes_sorted(self):
        path = _write_sample_csv()
        try:
            chain = load_options_csv(path, spot=17000.0)
            assert np.all(np.diff(chain.strikes) > 0)
        finally:
            os.unlink(path)

    def test_spot_required(self):
        path = _write_sample_csv()
        try:
            with pytest.raises(ValueError, match="spot"):
                load_options_csv(path)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_options_csv("/nonexistent/path.csv", spot=17000.0)

    def test_call_oi_correct(self):
        path = _write_sample_csv()
        try:
            chain = load_options_csv(path, spot=17000.0)
            # Strike 17100 should have call_oi = 2500
            idx = int(np.where(chain.strikes == 17100)[0][0])
            assert chain.call_oi[idx] == 2500
        finally:
            os.unlink(path)

    def test_put_oi_correct(self):
        path = _write_sample_csv()
        try:
            chain = load_options_csv(path, spot=17000.0)
            # Strike 17000 should have put_oi = 2000
            idx = int(np.where(chain.strikes == 17000)[0][0])
            assert chain.put_oi[idx] == 2000
        finally:
            os.unlink(path)

    def test_dte_computed(self):
        path = _write_sample_csv()
        try:
            chain = load_options_csv(path, spot=17000.0)
            # Jan 2 -> Jan 19 = 17 days
            assert chain.days_to_expiry == 17
        finally:
            os.unlink(path)

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"date": ["2024-01-02"], "strike": [17000]})
        f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
        df.to_csv(f.name, index=False)
        f.close()
        try:
            with pytest.raises(ValueError, match="missing required columns"):
                load_options_csv(f.name, spot=17000.0)
        finally:
            os.unlink(f.name)

    def test_iv_blended(self):
        path = _write_sample_csv()
        try:
            chain = load_options_csv(path, spot=17000.0)
            # Strike 17000: call_iv=0.19, put_iv=0.20, weighted by OI
            idx = int(np.where(chain.strikes == 17000)[0][0])
            expected = (0.19 * 1500 + 0.20 * 2000) / (1500 + 2000)
            assert abs(chain.implied_vol[idx] - expected) < 1e-6
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# OptionChain helper methods
# ---------------------------------------------------------------------------

class TestOptionChainMethods:
    def test_total_call_oi(self):
        chain = generate_synthetic_chain(spot=17000.0, seed=42)
        total = chain.total_call_oi()
        assert total > 0

    def test_total_put_oi(self):
        chain = generate_synthetic_chain(spot=17000.0, seed=42)
        total = chain.total_put_oi()
        assert total > 0

    def test_pcr_reasonable(self):
        chain = generate_synthetic_chain(spot=17000.0, seed=42)
        pcr = chain.put_call_ratio()
        # Symmetric synthetic walls should give PCR ~ 1.0
        assert 0.5 < pcr < 2.0
