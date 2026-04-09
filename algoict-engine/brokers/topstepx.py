"""
brokers/topstepx.py
====================
TopstepX (ProjectX) broker client for MNQ intraday trading.

Capabilities:
    1. Auth   : JWT login via /Auth/loginKey, auto-refresh before expiry
    2. WebSocket: real-time 1-min MNQ bars -> DataFrame rows via callback
    3. REST   : submit_market_order, submit_limit_order, submit_stop_order,
                cancel_order
    4. Positions: get_positions, flatten_all
    5. WS reconnect: exponential backoff, max 8 retries

Usage (async):
    client = TopstepXClient()
    await client.connect()                       # auth + WS start
    await client.subscribe_bars("MNQ", on_bar)  # callback(bar: dict)
    await client.submit_market_order("MNQ", side="buy", contracts=1)
    await client.flatten_all()
    await client.close()

All REST calls use aiohttp.ClientSession.
All WebSocket traffic uses the websockets library.
URLs are read from config.py (populated from .env).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

import aiohttp
import websockets
import websockets.exceptions

from config import (
    TOPSTEPX_API_URL,
    TOPSTEPX_WS_URL,
    TOPSTEPX_USERNAME,
    TOPSTEPX_API_KEY,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How many seconds before token expiry to trigger refresh
TOKEN_REFRESH_BUFFER_S = 120

# WebSocket reconnection
WS_RECONNECT_BASE_S = 1.0
WS_RECONNECT_MAX_S = 60.0
WS_MAX_RETRIES = 8

# Order sides
SIDE_BUY = "buy"
SIDE_SELL = "sell"

# Order types
ORDER_MARKET = "Market"
ORDER_LIMIT = "Limit"
ORDER_STOP = "Stop"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AuthToken:
    token: str
    expires_at: float          # Unix timestamp (UTC)

    def is_valid(self) -> bool:
        return time.time() < (self.expires_at - TOKEN_REFRESH_BUFFER_S)


@dataclass
class Position:
    symbol: str
    contracts: int             # positive = long, negative = short
    avg_price: float
    unrealized_pnl: float
    account_id: str = ""

    @property
    def is_long(self) -> bool:
        return self.contracts > 0

    @property
    def is_short(self) -> bool:
        return self.contracts < 0

    @property
    def is_flat(self) -> bool:
        return self.contracts == 0


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: str
    order_type: str
    contracts: int
    status: str
    filled_price: Optional[float] = None
    message: str = ""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TopstepXAuthError(Exception):
    """Raised when authentication fails."""


class TopstepXOrderError(Exception):
    """Raised when an order submission fails."""


class TopstepXConnectionError(Exception):
    """Raised when WS connection cannot be established after max retries."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TopstepXClient:
    """
    Async client for the TopstepX (ProjectX) API.

    Lifecycle:
        1. await client.connect()         -> authenticate + start WS listener
        2. await client.subscribe_bars()  -> register 1-min bar callback
        3. ... trade ...
        4. await client.close()           -> stop WS + close HTTP session
    """

    def __init__(
        self,
        username: str = TOPSTEPX_USERNAME,
        api_key: str = TOPSTEPX_API_KEY,
        api_url: str = TOPSTEPX_API_URL,
        ws_url: str = TOPSTEPX_WS_URL,
    ):
        if not username or not api_key:
            raise ValueError(
                "TopstepX credentials missing. "
                "Set TOPSTEPX_USERNAME and TOPSTEPX_API_KEY in .env"
            )

        self._username = username
        self._api_key = api_key
        self._api_url = api_url.rstrip("/")
        self._ws_url = ws_url.rstrip("/")

        self._token: Optional[AuthToken] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # WebSocket
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_running = False
        self._bar_callbacks: list[Callable] = []
        self._subscribed_symbols: set[str] = set()

        # Account ID (populated after auth)
        self._account_id: str = ""

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """Authenticate and start the WebSocket listener task."""
        self._session = aiohttp.ClientSession()
        await self._authenticate()
        self._ws_running = True
        self._ws_task = asyncio.create_task(self._ws_listener_loop())
        logger.info("TopstepXClient connected (account: %s)", self._account_id)

    async def close(self) -> None:
        """Gracefully stop WS and close HTTP session."""
        self._ws_running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("TopstepXClient closed")

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #

    async def _authenticate(self) -> None:
        """
        POST /Auth/loginKey with username + apiKey.
        Parses the JWT, extracts expiry from the payload.
        """
        url = f"{self._api_url}/Auth/loginKey"
        payload = {"userName": self._username, "apiKey": self._api_key}

        async with self._session.post(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise TopstepXAuthError(
                    f"Auth failed ({resp.status}): {text}"
                )
            data = await resp.json()

        token_str = data.get("token") or data.get("accessToken") or data.get("jwt", "")
        if not token_str:
            raise TopstepXAuthError(f"No token in auth response: {data}")

        # Extract expiry from JWT payload (middle segment)
        expires_at = _parse_jwt_expiry(token_str)
        self._token = AuthToken(token=token_str, expires_at=expires_at)

        # Store account ID if present
        self._account_id = str(
            data.get("accountId") or data.get("account_id") or ""
        )

        logger.info(
            "Authenticated as %s, token expires at %s",
            self._username,
            datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        )

    async def _ensure_token(self) -> str:
        """Return a valid JWT token, refreshing if close to expiry."""
        if self._token is None or not self._token.is_valid():
            logger.info("Token expired or missing — re-authenticating")
            await self._authenticate()
        return self._token.token

    # ------------------------------------------------------------------ #
    # REST helpers                                                         #
    # ------------------------------------------------------------------ #

    def _auth_headers(self) -> dict[str, str]:
        if self._token is None:
            raise TopstepXAuthError("Not authenticated")
        return {
            "Authorization": f"Bearer {self._token.token}",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        await self._ensure_token()
        url = f"{self._api_url}/{path.lstrip('/')}"
        async with self._session.get(
            url, headers=self._auth_headers(), params=params
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, payload: dict) -> Any:
        await self._ensure_token()
        url = f"{self._api_url}/{path.lstrip('/')}"
        async with self._session.post(
            url, headers=self._auth_headers(), json=payload
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _delete(self, path: str) -> Any:
        await self._ensure_token()
        url = f"{self._api_url}/{path.lstrip('/')}"
        async with self._session.delete(
            url, headers=self._auth_headers()
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------ #
    # Orders                                                               #
    # ------------------------------------------------------------------ #

    async def submit_market_order(
        self,
        symbol: str,
        side: str,
        contracts: int,
    ) -> OrderResult:
        """
        Submit a market order.

        Parameters
        ----------
        symbol    : e.g. "MNQ" or "MNQM5"
        side      : "buy" or "sell"
        contracts : number of contracts (positive integer)
        """
        _validate_order_params(symbol, side, contracts)
        payload = _build_order_payload(
            symbol=symbol,
            side=side,
            contracts=contracts,
            order_type=ORDER_MARKET,
            account_id=self._account_id,
        )
        return await self._submit_order(payload, symbol, side, contracts, ORDER_MARKET)

    async def submit_limit_order(
        self,
        symbol: str,
        side: str,
        contracts: int,
        limit_price: float,
    ) -> OrderResult:
        """Submit a limit order at limit_price."""
        _validate_order_params(symbol, side, contracts)
        if limit_price <= 0:
            raise TopstepXOrderError("limit_price must be positive")
        payload = _build_order_payload(
            symbol=symbol,
            side=side,
            contracts=contracts,
            order_type=ORDER_LIMIT,
            account_id=self._account_id,
            limit_price=limit_price,
        )
        return await self._submit_order(payload, symbol, side, contracts, ORDER_LIMIT)

    async def submit_stop_order(
        self,
        symbol: str,
        side: str,
        contracts: int,
        stop_price: float,
    ) -> OrderResult:
        """Submit a stop order at stop_price."""
        _validate_order_params(symbol, side, contracts)
        if stop_price <= 0:
            raise TopstepXOrderError("stop_price must be positive")
        payload = _build_order_payload(
            symbol=symbol,
            side=side,
            contracts=contracts,
            order_type=ORDER_STOP,
            account_id=self._account_id,
            stop_price=stop_price,
        )
        return await self._submit_order(payload, symbol, side, contracts, ORDER_STOP)

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order by order_id.
        Returns True on success, False if the order was not found.
        """
        if not order_id:
            raise TopstepXOrderError("order_id cannot be empty")
        try:
            await self._delete(f"/Order/{order_id}")
            logger.info("Cancelled order %s", order_id)
            return True
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                logger.warning("Order %s not found for cancellation", order_id)
                return False
            raise TopstepXOrderError(
                f"Failed to cancel order {order_id}: {exc}"
            ) from exc

    async def _submit_order(
        self,
        payload: dict,
        symbol: str,
        side: str,
        contracts: int,
        order_type: str,
    ) -> OrderResult:
        try:
            data = await self._post("/Order/place", payload)
        except aiohttp.ClientResponseError as exc:
            raise TopstepXOrderError(
                f"Order submission failed ({exc.status}): {exc.message}"
            ) from exc

        order_id = str(data.get("orderId") or data.get("order_id") or "")
        status = str(data.get("status") or data.get("orderStatus") or "submitted")
        filled_price = data.get("filledPrice") or data.get("avgPrice")

        result = OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            contracts=contracts,
            status=status,
            filled_price=float(filled_price) if filled_price else None,
            message=str(data.get("message") or ""),
        )
        logger.info(
            "Order %s | %s %s %d x %s @ %s",
            order_id, order_type, side.upper(), contracts, symbol,
            filled_price or "market",
        )
        return result

    # ------------------------------------------------------------------ #
    # Positions                                                            #
    # ------------------------------------------------------------------ #

    async def get_positions(self) -> list[Position]:
        """
        Return all open positions for the current account.
        Positions with zero contracts are excluded.
        """
        data = await self._get(f"/Position/account/{self._account_id}")

        # API may return a list directly or wrap it in a key
        if isinstance(data, dict):
            rows = data.get("positions") or data.get("data") or []
        else:
            rows = data or []

        positions = []
        for row in rows:
            contracts = int(row.get("size") or row.get("contracts") or 0)
            if contracts == 0:
                continue
            pos = Position(
                symbol=str(row.get("symbol") or row.get("contractId") or ""),
                contracts=contracts,
                avg_price=float(row.get("avgPrice") or row.get("averagePrice") or 0.0),
                unrealized_pnl=float(row.get("unrealizedPnl") or row.get("pnl") or 0.0),
                account_id=self._account_id,
            )
            positions.append(pos)

        logger.debug("get_positions: %d open", len(positions))
        return positions

    async def flatten_all(self) -> list[OrderResult]:
        """
        Close all open positions with market orders.
        Long positions are sold; short positions are bought back.

        Returns the list of OrderResults (one per position closed).
        """
        positions = await self.get_positions()
        if not positions:
            logger.info("flatten_all: no open positions")
            return []

        results = []
        for pos in positions:
            if pos.is_long:
                side = SIDE_SELL
            elif pos.is_short:
                side = SIDE_BUY
            else:
                continue

            try:
                result = await self.submit_market_order(
                    symbol=pos.symbol,
                    side=side,
                    contracts=abs(pos.contracts),
                )
                results.append(result)
                logger.warning(
                    "FLATTEN: %s %d x %s",
                    side.upper(), abs(pos.contracts), pos.symbol,
                )
            except TopstepXOrderError as exc:
                logger.error("Failed to flatten %s: %s", pos.symbol, exc)

        return results

    # ------------------------------------------------------------------ #
    # WebSocket — 1-min bars                                               #
    # ------------------------------------------------------------------ #

    def subscribe_bars(self, symbol: str, callback: Callable[[dict], Any]) -> None:
        """
        Register a callback for real-time 1-min bar updates for symbol.

        The callback receives a dict:
            {
              "symbol": str,
              "timestamp": pd.Timestamp (UTC),
              "open": float, "high": float, "low": float,
              "close": float, "volume": int
            }

        Can be called before or after connect().
        """
        self._subscribed_symbols.add(symbol.upper())
        self._bar_callbacks.append(callback)
        logger.info("Subscribed to 1-min bars: %s", symbol)

    async def _ws_listener_loop(self) -> None:
        """
        Main WS loop. Connects to the TopstepX SignalR-style WS endpoint,
        sends subscription messages, and dispatches incoming bar data.

        Reconnects with exponential backoff on any disconnect.
        """
        retries = 0
        backoff = WS_RECONNECT_BASE_S

        while self._ws_running:
            try:
                await self._ws_connect_and_listen()
                retries = 0
                backoff = WS_RECONNECT_BASE_S
            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError,
                asyncio.TimeoutError,
            ) as exc:
                if not self._ws_running:
                    break
                retries += 1
                if retries > WS_MAX_RETRIES:
                    logger.error(
                        "WS: exceeded max retries (%d). Giving up.", WS_MAX_RETRIES
                    )
                    raise TopstepXConnectionError(
                        f"WS failed after {WS_MAX_RETRIES} retries: {exc}"
                    ) from exc

                logger.warning(
                    "WS disconnected (%s). Retry %d/%d in %.1fs",
                    exc, retries, WS_MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_MAX_S)

                # Refresh token before reconnecting
                try:
                    await self._ensure_token()
                except TopstepXAuthError as auth_exc:
                    logger.error("Re-auth failed during WS reconnect: %s", auth_exc)
                    await asyncio.sleep(backoff)

    async def _ws_connect_and_listen(self) -> None:
        """Open one WS connection, subscribe, and listen until disconnection."""
        token = await self._ensure_token()
        uri = f"{self._ws_url}?access_token={token}"

        logger.info("WS: connecting to %s", self._ws_url)
        async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
            logger.info("WS: connected")

            # Subscribe to 1-min bars for all registered symbols
            for symbol in self._subscribed_symbols:
                sub_msg = json.dumps({
                    "action": "subscribe",
                    "channel": "bars",
                    "symbol": symbol,
                    "timeframe": "1min",
                })
                await ws.send(sub_msg)
                logger.debug("WS: subscribed to bars/%s", symbol)

            async for raw in ws:
                if not self._ws_running:
                    break
                self._dispatch_ws_message(raw)

    def _dispatch_ws_message(self, raw: str | bytes) -> None:
        """Parse a raw WS message and invoke registered bar callbacks."""
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            msg = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug("WS: failed to parse message: %s", exc)
            return

        msg_type = msg.get("type") or msg.get("event") or ""

        # Different TopstepX WS message shapes — normalise to a bar dict
        bar = None
        if msg_type in ("bar", "ohlcv", "1min_bar"):
            bar = _parse_bar_message(msg)
        elif "data" in msg and isinstance(msg["data"], dict):
            inner = msg["data"]
            if "open" in inner or "o" in inner:
                bar = _parse_bar_message(inner)

        if bar:
            for cb in self._bar_callbacks:
                try:
                    result = cb(bar)
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception as exc:
                    logger.exception("Bar callback raised: %s", exc)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_jwt_expiry(token: str) -> float:
    """
    Decode the JWT payload (base64 middle segment) and extract 'exp'.
    Returns Unix timestamp (float). Falls back to now + 24h if parse fails.
    """
    import base64

    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Not a 3-part JWT")
        # Add padding if needed
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = payload.get("exp")
        if exp is not None:
            return float(exp)
    except Exception as exc:
        logger.debug("JWT expiry parse failed: %s", exc)

    # Default: 24 hours from now
    return time.time() + 86400.0


def _validate_order_params(symbol: str, side: str, contracts: int) -> None:
    if not symbol:
        raise TopstepXOrderError("symbol cannot be empty")
    if side not in (SIDE_BUY, SIDE_SELL):
        raise TopstepXOrderError(f"side must be 'buy' or 'sell', got '{side}'")
    if contracts <= 0:
        raise TopstepXOrderError(f"contracts must be positive, got {contracts}")


def _build_order_payload(
    symbol: str,
    side: str,
    contracts: int,
    order_type: str,
    account_id: str,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> dict:
    payload: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "size": contracts,
        "type": order_type,
        "accountId": account_id,
    }
    if limit_price is not None:
        payload["limitPrice"] = limit_price
    if stop_price is not None:
        payload["stopPrice"] = stop_price
    return payload


def _parse_bar_message(msg: dict) -> Optional[dict]:
    """
    Normalise a WS message dict into our standard bar format.

    Returns None if required fields are missing.
    """
    import pandas as pd

    try:
        # Support both full names and single-char keys (o/h/l/c/v)
        open_  = float(msg.get("open")  or msg.get("o")  or 0)
        high   = float(msg.get("high")  or msg.get("h")  or 0)
        low    = float(msg.get("low")   or msg.get("l")  or 0)
        close  = float(msg.get("close") or msg.get("c")  or 0)
        volume = int(  msg.get("volume") or msg.get("v") or 0)

        ts_raw = (
            msg.get("timestamp") or msg.get("ts") or
            msg.get("time") or msg.get("datetime") or ""
        )
        if ts_raw:
            ts = pd.Timestamp(ts_raw, tz="UTC")
        else:
            ts = pd.Timestamp.now("UTC")

        symbol = str(msg.get("symbol") or msg.get("contractId") or "MNQ")

        if open_ == 0 and high == 0 and low == 0 and close == 0:
            return None

        return {
            "symbol": symbol,
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    except (TypeError, ValueError):
        return None
