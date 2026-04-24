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
        mock_resp.json = AsyncMock(return_value={"token": jwt, "success": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.closed = False
        client._session = mock_session

        # _authenticate now calls _resolve_account after the login POST;
        # stub it out so this unit test stays focused on token handling.
        with patch.object(client, "_resolve_account", AsyncMock()):
            await client._authenticate()

        assert client._token is not None
        assert client._token.token == jwt

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
    """
    ProjectX wire format: integer type/side codes, numeric accountId,
    fully qualified contractId, nullable price fields always present.
    """

    def test_market_payload(self):
        p = _build_order_payload(
            contract_id="CON.F.US.MNQ.M26",
            side="buy",
            contracts=2,
            order_type=ORDER_MARKET,
            account_id="999",
        )
        assert p["contractId"] == "CON.F.US.MNQ.M26"
        assert p["accountId"] == 999
        assert p["side"] == 0      # buy
        assert p["size"] == 2
        assert p["type"] == 2      # market
        assert p["limitPrice"] is None
        assert p["stopPrice"] is None
        assert "trailPrice" in p
        assert "customTag" in p
        assert "linkedOrderId" in p

    def test_limit_payload_has_price(self):
        p = _build_order_payload(
            contract_id="CON.F.US.MNQ.M26",
            side="sell",
            contracts=1,
            order_type=ORDER_LIMIT,
            account_id="999",
            limit_price=19500.0,
        )
        assert p["type"] == 1      # limit
        assert p["side"] == 1      # sell
        assert p["limitPrice"] == 19500.0
        assert p["stopPrice"] is None

    def test_stop_payload_has_price(self):
        p = _build_order_payload(
            contract_id="CON.F.US.MNQ.M26",
            side="buy",
            contracts=1,
            order_type=ORDER_STOP,
            account_id="999",
            stop_price=19000.0,
        )
        assert p["type"] == 4      # stop
        assert p["stopPrice"] == 19000.0
        assert p["limitPrice"] is None

    def test_invalid_side_raises(self):
        with pytest.raises(TopstepXOrderError, match="side"):
            _build_order_payload(
                contract_id="CON.F.US.MNQ.M26",
                side="bananas",
                contracts=1,
                order_type=ORDER_MARKET,
                account_id="999",
            )


# ---------------------------------------------------------------------------
# Orders (REST mocked)
# ---------------------------------------------------------------------------

def _mock_client_with_token() -> TopstepXClient:
    client = _make_client()
    client._token = AuthToken(token=_make_jwt(time.time() + 3600), expires_at=time.time() + 3600)
    # ProjectX requires a numeric accountId on the wire
    client._account_id = "999"
    # Pre-populate the contract cache so order tests don't have to mock
    # the /Contract/search lookup.
    client._contract_cache["MNQ"] = "CON.F.US.MNQ.M26"
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
            "orderId": 123456, "success": True,
            "errorCode": 0, "errorMessage": None,
        })

        result = await client.submit_market_order("MNQ", "buy", 1)
        assert isinstance(result, OrderResult)
        assert result.order_id == "123456"
        assert result.side == "buy"
        assert result.order_type == ORDER_MARKET
        assert result.contracts == 1
        assert result.status == "submitted"

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
            "orderId": 222, "success": True,
            "errorCode": 0, "errorMessage": None,
        })
        result = await client.submit_limit_order("MNQ", "sell", 2, limit_price=19500.0)
        assert result.order_type == ORDER_LIMIT
        assert result.contracts == 2
        assert result.order_id == "222"

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
            "orderId": 333, "success": True,
            "errorCode": 0, "errorMessage": None,
        })
        result = await client.submit_stop_order("MNQ", "sell", 1, stop_price=19000.0)
        assert result.order_type == ORDER_STOP
        assert result.order_id == "333"


class TestCancelOrder:
    """
    Cancel moved to POST /Order/cancel with {accountId, orderId} payload
    and a {success, errorCode, errorMessage} response shape.
    """

    @pytest.mark.asyncio
    async def test_cancel_success(self):
        client = _mock_client_with_token()
        client._session = _mock_session_for_post({
            "success": True, "errorCode": 0, "errorMessage": None,
        })
        result = await client.cancel_order("123456")
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_not_found_returns_false(self):
        client = _mock_client_with_token()
        # errorCode=5 is what TopstepX returns when the order is already
        # gone / never persisted — we report False, not raise.
        client._session = _mock_session_for_post({
            "success": False, "errorCode": 5, "errorMessage": None,
        })
        result = await client.cancel_order("999999")
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
    """
    2026-04-24: Bug J fix — endpoint moved from GET /Position/account/{id}
    (always 404) to POST /Position/searchOpen (ProjectX canonical).
    Response shape is now {"positions": [...], "success": bool, ...}.
    Position type is 1=long, 2=short per ProjectX convention.
    """

    @pytest.mark.asyncio
    async def test_returns_open_positions(self):
        client = _mock_client_with_token()
        client._account_id = "21551987"

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "positions": [
                {"contractId": "CON.F.US.MNQ.M26", "type": 1, "size": 2,
                 "averagePrice": 19500.0, "unrealizedPnl": 100.0},
                {"contractId": "CON.F.US.NQ.M26", "type": 2, "size": 1,
                 "averagePrice": 19600.0, "unrealizedPnl": -50.0},
            ],
            "success": True,
            "errorCode": 0,
            "errorMessage": None,
        })
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        client._session = mock_session

        positions = await client.get_positions()
        assert len(positions) == 2
        # type=1 → positive contracts (long)
        assert positions[0].symbol == "CON.F.US.MNQ.M26"
        assert positions[0].contracts == 2
        assert positions[0].is_long is True
        # type=2 → negative contracts (short)
        assert positions[1].contracts == -1
        assert positions[1].is_short is True

        # POST payload should include accountId
        call_args = mock_session.post.call_args
        assert "/Position/searchOpen" in call_args.args[0]
        assert call_args.kwargs["json"] == {"accountId": 21551987}

    @pytest.mark.asyncio
    async def test_excludes_zero_size(self):
        client = _mock_client_with_token()

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "positions": [
                {"contractId": "CON.F.US.MNQ.M26", "type": 1, "size": 0,
                 "averagePrice": 0.0, "unrealizedPnl": 0.0},
            ],
            "success": True,
        })
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        client._session = mock_session

        positions = await client.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_empty_positions_list(self):
        """Flat account — ProjectX returns {"positions": [], "success": true}."""
        client = _mock_client_with_token()

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "positions": [],
            "success": True,
        })
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        client._session = mock_session

        positions = await client.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_api_error_logged_returns_empty(self):
        """success=False from ProjectX — log error, return []."""
        client = _mock_client_with_token()

        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={
            "positions": None,
            "success": False,
            "errorCode": 42,
            "errorMessage": "Account not found",
        })
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
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
# SignalR streaming (subscribe_bars still works the same way)
# ---------------------------------------------------------------------------

class TestSubscribeBars:
    def test_subscribe_bars_registers(self):
        client = _make_client()
        cb = lambda b: None
        client.subscribe_bars("MNQ", cb)
        assert "MNQ" in client._subscribed_symbols
        assert cb in client._bar_callbacks
