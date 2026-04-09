"""
tests/test_topstepx.py
=======================
Unit tests for brokers/topstepx.py

These tests are OFFLINE — no real network calls.
All HTTP/WS interactions are mocked.
"""

import asyncio
import base64
import json
import time
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brokers.topstepx import (
    TopstepXClient,
    AuthToken,
    Position,
    OrderResult,
    TopstepXAuthError,
    TopstepXOrderError,
    TopstepXConnectionError,
    _parse_jwt_expiry,
    _validate_order_params,
    _build_order_payload,
    _parse_bar_message,
    SIDE_BUY,
    SIDE_SELL,
    ORDER_MARKET,
    ORDER_LIMIT,
    ORDER_STOP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jwt(exp: float) -> str:
    """Build a minimal JWT string with a given 'exp' claim."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"exp": exp, "sub": "test"}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


def _make_client(username="testuser", api_key="testkey") -> TopstepXClient:
    return TopstepXClient(
        username=username,
        api_key=api_key,
        api_url="https://fake.api.com/api",
        ws_url="wss://fake.ws.com/api",
    )


# ---------------------------------------------------------------------------
# AuthToken
# ---------------------------------------------------------------------------

class TestAuthToken:
    def test_valid_token(self):
        token = AuthToken(token="abc", expires_at=time.time() + 3600)
        assert token.is_valid() is True

    def test_expired_token(self):
        token = AuthToken(token="abc", expires_at=time.time() - 1)
        assert token.is_valid() is False

    def test_near_expiry_invalid(self):
        # Within refresh buffer (120s) -> should trigger refresh
        token = AuthToken(token="abc", expires_at=time.time() + 60)
        assert token.is_valid() is False


# ---------------------------------------------------------------------------
# JWT parsing
# ---------------------------------------------------------------------------

class TestParseJwtExpiry:
    def test_valid_jwt(self):
        future = time.time() + 3600
        jwt = _make_jwt(future)
        result = _parse_jwt_expiry(jwt)
        assert abs(result - future) < 1.0

    def test_invalid_jwt_returns_default(self):
        result = _parse_jwt_expiry("not.a.jwt")
        # Should fall back to now + 24h
        assert result > time.time() + 80000

    def test_two_part_jwt_returns_default(self):
        result = _parse_jwt_expiry("header.payload")
        assert result > time.time() + 80000


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestClientConstructor:
    def test_raises_without_credentials(self):
        with pytest.raises(ValueError, match="credentials missing"):
            TopstepXClient(username="", api_key="", api_url="x", ws_url="y")

    def test_raises_without_api_key(self):
        with pytest.raises(ValueError):
            TopstepXClient(username="user", api_key="", api_url="x", ws_url="y")

    def test_created_successfully(self):
        client = _make_client()
        assert client._username == "testuser"
        assert client._api_key == "testkey"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    @pytest.mark.asyncio
    async def test_auth_stores_token(self):
        client = _make_client()
        future = time.time() + 3600
        jwt = _make_jwt(future)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"token": jwt, "accountId": "ACC123"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        client._session = mock_session

        await client._authenticate()

        assert client._token is not None
        assert client._token.token == jwt
        assert client._account_id == "ACC123"

    @pytest.mark.asyncio
    async def test_auth_raises_on_401(self):
        client = _make_client()

        mock_resp = AsyncMock()
        mock_resp.status = 401
        mock_resp.text = AsyncMock(return_value="Unauthorized")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        client._session = mock_session

        with pytest.raises(TopstepXAuthError):
            await client._authenticate()

    @pytest.mark.asyncio
    async def test_auth_raises_if_no_token_in_response(self):
        client = _make_client()

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"message": "ok"})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        client._session = mock_session

        with pytest.raises(TopstepXAuthError, match="No token"):
            await client._authenticate()


# ---------------------------------------------------------------------------
# Order validation helpers
# ---------------------------------------------------------------------------

class TestValidateOrderParams:
    def test_valid(self):
        _validate_order_params("MNQ", "buy", 1)   # should not raise

    def test_empty_symbol(self):
        with pytest.raises(TopstepXOrderError, match="symbol"):
            _validate_order_params("", "buy", 1)

    def test_bad_side(self):
        with pytest.raises(TopstepXOrderError, match="side"):
            _validate_order_params("MNQ", "long", 1)

    def test_zero_contracts(self):
        with pytest.raises(TopstepXOrderError, match="contracts"):
            _validate_order_params("MNQ", "buy", 0)

    def test_negative_contracts(self):
        with pytest.raises(TopstepXOrderError, match="contracts"):
            _validate_order_params("MNQ", "sell", -2)


class TestBuildOrderPayload:
    def test_market_payload(self):
        p = _build_order_payload("MNQ", "buy", 2, ORDER_MARKET, "ACC1")
        assert p["symbol"] == "MNQ"
        assert p["side"] == "buy"
        assert p["size"] == 2
        assert p["type"] == ORDER_MARKET
        assert "limitPrice" not in p
        assert "stopPrice" not in p

    def test_limit_payload_has_price(self):
        p = _build_order_payload("MNQ", "sell", 1, ORDER_LIMIT, "ACC1", limit_price=19500.0)
        assert p["limitPrice"] == 19500.0
        assert "stopPrice" not in p

    def test_stop_payload_has_price(self):
        p = _build_order_payload("MNQ", "buy", 1, ORDER_STOP, "ACC1", stop_price=19000.0)
        assert p["stopPrice"] == 19000.0
        assert "limitPrice" not in p


# ---------------------------------------------------------------------------
# Orders (REST mocked)
# ---------------------------------------------------------------------------

def _mock_client_with_token() -> TopstepXClient:
    client = _make_client()
    client._token = AuthToken(token=_make_jwt(time.time() + 3600), expires_at=time.time() + 3600)
    client._account_id = "ACC999"
    return client


def _mock_session_for_post(response_data: dict, status: int = 200):
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=response_data)
    mock_resp.raise_for_status = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    return mock_session


class TestSubmitMarketOrder:
    @pytest.mark.asyncio
    async def test_returns_order_result(self):
        client = _mock_client_with_token()
        client._session = _mock_session_for_post({
            "orderId": "ORD001", "status": "submitted"
        })

        result = await client.submit_market_order("MNQ", "buy", 1)
        assert isinstance(result, OrderResult)
        assert result.order_id == "ORD001"
        assert result.side == "buy"
        assert result.order_type == ORDER_MARKET
        assert result.contracts == 1

    @pytest.mark.asyncio
    async def test_bad_side_raises(self):
        client = _mock_client_with_token()
        with pytest.raises(TopstepXOrderError):
            await client.submit_market_order("MNQ", "long", 1)

    @pytest.mark.asyncio
    async def test_zero_contracts_raises(self):
        client = _mock_client_with_token()
        with pytest.raises(TopstepXOrderError):
            await client.submit_market_order("MNQ", "buy", 0)


class TestSubmitLimitOrder:
    @pytest.mark.asyncio
    async def test_limit_order_accepted(self):
        client = _mock_client_with_token()
        client._session = _mock_session_for_post({
            "orderId": "ORD002", "status": "pending"
        })
        result = await client.submit_limit_order("MNQ", "sell", 2, limit_price=19500.0)
        assert result.order_type == ORDER_LIMIT
        assert result.contracts == 2

    @pytest.mark.asyncio
    async def test_zero_limit_price_raises(self):
        client = _mock_client_with_token()
        with pytest.raises(TopstepXOrderError, match="limit_price"):
            await client.submit_limit_order("MNQ", "buy", 1, limit_price=0.0)


class TestSubmitStopOrder:
    @pytest.mark.asyncio
    async def test_stop_order_accepted(self):
        client = _mock_client_with_token()
        client._session = _mock_session_for_post({
            "orderId": "ORD003", "status": "pending"
        })
        result = await client.submit_stop_order("MNQ", "sell", 1, stop_price=19000.0)
        assert result.order_type == ORDER_STOP


class TestCancelOrder:
    @pytest.mark.asyncio
    async def test_cancel_success(self):
        client = _mock_client_with_token()

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={"status": "cancelled"})
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.delete = MagicMock(return_value=mock_resp)
        client._session = mock_session

        result = await client.cancel_order("ORD001")
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_not_found_returns_false(self):
        import aiohttp
        client = _mock_client_with_token()

        mock_resp = AsyncMock()
        exc = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=404
        )
        mock_resp.raise_for_status = MagicMock(side_effect=exc)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.delete = MagicMock(return_value=mock_resp)
        client._session = mock_session

        result = await client.cancel_order("NONEXISTENT")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_empty_id_raises(self):
        client = _mock_client_with_token()
        with pytest.raises(TopstepXOrderError, match="order_id"):
            await client.cancel_order("")


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

class TestGetPositions:
    @pytest.mark.asyncio
    async def test_returns_open_positions(self):
        client = _mock_client_with_token()

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=[
            {"symbol": "MNQ", "size": 2, "avgPrice": 19500.0, "unrealizedPnl": 100.0},
            {"symbol": "NQ",  "size": -1, "avgPrice": 19600.0, "unrealizedPnl": -50.0},
        ])
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        client._session = mock_session

        positions = await client.get_positions()
        assert len(positions) == 2
        assert positions[0].symbol == "MNQ"
        assert positions[0].contracts == 2
        assert positions[0].is_long is True
        assert positions[1].is_short is True

    @pytest.mark.asyncio
    async def test_excludes_zero_size(self):
        client = _mock_client_with_token()

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=[
            {"symbol": "MNQ", "size": 0, "avgPrice": 0.0, "unrealizedPnl": 0.0},
        ])
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        client._session = mock_session

        positions = await client.get_positions()
        assert positions == []


class TestFlattenAll:
    @pytest.mark.asyncio
    async def test_flatten_long_position(self):
        client = _mock_client_with_token()

        # get_positions returns 1 long
        long_pos = Position("MNQ", contracts=2, avg_price=19500.0, unrealized_pnl=0.0)

        order_resp = OrderResult(
            order_id="FLAT001", symbol="MNQ", side="sell",
            order_type=ORDER_MARKET, contracts=2, status="submitted",
        )

        mock_submit = AsyncMock(return_value=order_resp)
        with patch.object(client, "get_positions", AsyncMock(return_value=[long_pos])):
            with patch.object(client, "submit_market_order", mock_submit):
                results = await client.flatten_all()

        assert len(results) == 1
        mock_submit.assert_called_once_with(
            symbol="MNQ", side=SIDE_SELL, contracts=2
        )

    @pytest.mark.asyncio
    async def test_flatten_short_position(self):
        client = _mock_client_with_token()

        short_pos = Position("MNQ", contracts=-3, avg_price=19500.0, unrealized_pnl=0.0)
        order_resp = OrderResult(
            order_id="FLAT002", symbol="MNQ", side="buy",
            order_type=ORDER_MARKET, contracts=3, status="submitted",
        )

        mock_submit = AsyncMock(return_value=order_resp)
        with patch.object(client, "get_positions", AsyncMock(return_value=[short_pos])):
            with patch.object(client, "submit_market_order", mock_submit):
                results = await client.flatten_all()

        mock_submit.assert_called_once_with(
            symbol="MNQ", side=SIDE_BUY, contracts=3
        )

    @pytest.mark.asyncio
    async def test_flatten_no_positions(self):
        client = _mock_client_with_token()
        with patch.object(client, "get_positions", AsyncMock(return_value=[])):
            results = await client.flatten_all()
        assert results == []


# ---------------------------------------------------------------------------
# Position dataclass
# ---------------------------------------------------------------------------

class TestPositionDataclass:
    def test_long_flags(self):
        p = Position("MNQ", contracts=2, avg_price=100.0, unrealized_pnl=10.0)
        assert p.is_long is True
        assert p.is_short is False
        assert p.is_flat is False

    def test_short_flags(self):
        p = Position("MNQ", contracts=-1, avg_price=100.0, unrealized_pnl=-5.0)
        assert p.is_long is False
        assert p.is_short is True
        assert p.is_flat is False

    def test_flat_flags(self):
        p = Position("MNQ", contracts=0, avg_price=100.0, unrealized_pnl=0.0)
        assert p.is_flat is True


# ---------------------------------------------------------------------------
# Bar message parsing
# ---------------------------------------------------------------------------

class TestParseBarMessage:
    def test_full_names(self):
        msg = {
            "symbol": "MNQ",
            "timestamp": "2024-01-02T09:30:00Z",
            "open": 19500.0, "high": 19520.0,
            "low": 19490.0, "close": 19510.0,
            "volume": 1500,
        }
        bar = _parse_bar_message(msg)
        assert bar is not None
        assert bar["open"] == 19500.0
        assert bar["volume"] == 1500
        assert bar["symbol"] == "MNQ"
        assert isinstance(bar["timestamp"], pd.Timestamp)

    def test_single_char_keys(self):
        msg = {"o": 100.0, "h": 105.0, "l": 99.0, "c": 103.0, "v": 500}
        bar = _parse_bar_message(msg)
        assert bar is not None
        assert bar["open"] == 100.0
        assert bar["close"] == 103.0

    def test_all_zero_returns_none(self):
        msg = {"open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0}
        bar = _parse_bar_message(msg)
        assert bar is None

    def test_missing_timestamp_uses_now(self):
        msg = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 200}
        bar = _parse_bar_message(msg)
        assert bar is not None
        assert isinstance(bar["timestamp"], pd.Timestamp)


# ---------------------------------------------------------------------------
# WS dispatch (offline)
# ---------------------------------------------------------------------------

class TestDispatchWSMessage:
    def test_bar_type_triggers_callback(self):
        client = _make_client()
        received = []
        client._bar_callbacks.append(lambda b: received.append(b))

        msg = {
            "type": "bar",
            "symbol": "MNQ",
            "open": 19500.0, "high": 19520.0,
            "low": 19490.0, "close": 19510.0,
            "volume": 1000,
        }
        client._dispatch_ws_message(json.dumps(msg))
        assert len(received) == 1
        assert received[0]["symbol"] == "MNQ"

    def test_unknown_type_no_callback(self):
        client = _make_client()
        received = []
        client._bar_callbacks.append(lambda b: received.append(b))

        client._dispatch_ws_message(json.dumps({"type": "heartbeat", "status": "ok"}))
        assert len(received) == 0

    def test_nested_data_triggers_callback(self):
        client = _make_client()
        received = []
        client._bar_callbacks.append(lambda b: received.append(b))

        msg = {
            "type": "update",
            "data": {
                "symbol": "MNQ",
                "open": 19500.0, "high": 19520.0,
                "low": 19490.0, "close": 19510.0,
                "volume": 800,
            }
        }
        client._dispatch_ws_message(json.dumps(msg))
        assert len(received) == 1

    def test_malformed_json_ignored(self):
        client = _make_client()
        received = []
        client._bar_callbacks.append(lambda b: received.append(b))
        client._dispatch_ws_message("{not valid json")
        assert len(received) == 0

    def test_subscribe_bars_registers(self):
        client = _make_client()
        cb = lambda b: None
        client.subscribe_bars("MNQ", cb)
        assert "MNQ" in client._subscribed_symbols
        assert cb in client._bar_callbacks
