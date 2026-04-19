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

import threading

import aiohttp
from signalrcore.hub_connection_builder import HubConnectionBuilder

from config import (
    TOPSTEPX_API_URL,
    TOPSTEPX_WS_URL,
    TOPSTEPX_USERNAME,
    TOPSTEPX_API_KEY,
    TOPSTEPX_ACCOUNT_ID,
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

# Order sides (string aliases accepted by the public API)
SIDE_BUY = "buy"
SIDE_SELL = "sell"

# Order types (string aliases)
ORDER_MARKET = "Market"
ORDER_LIMIT = "Limit"
ORDER_STOP = "Stop"

# ProjectX REST wire codes
_SIDE_CODES = {"buy": 0, "long": 0, "bid": 0, "sell": 1, "short": 1, "ask": 1}
_TYPE_CODES = {
    ORDER_LIMIT: 1,
    ORDER_MARKET: 2,
    ORDER_STOP: 4,
    "TrailingStop": 5,
}


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
        account_id: str = TOPSTEPX_ACCOUNT_ID,
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

        # WebSocket — market hub (bars)
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_running = False
        self._bar_callbacks: list[Callable] = []
        self._subscribed_symbols: set[str] = set()
        self._on_ws_exhausted: Optional[Callable[[], Any]] = None

        # WebSocket — user hub (order fills)
        self._user_hub_task: Optional[asyncio.Task] = None
        self._fill_callback: Optional[Callable] = None

        # Account selection — resolved via /Account/search after auth
        self._requested_account_id: str = str(account_id or "")
        self._account_id: str = ""
        self._account_info: dict = {}

        # Symbol -> contractId cache (e.g. "MNQ" -> "CON.F.US.MNQ.M26")
        self._contract_cache: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """Authenticate and start the WebSocket listener tasks."""
        self._session = aiohttp.ClientSession()
        await self._authenticate()
        self._ws_running = True
        self._ws_task = asyncio.create_task(self._ws_listener_loop())
        self._user_hub_task = asyncio.create_task(self._user_hub_listener_loop())
        logger.info("TopstepXClient connected (account: %s)", self._account_id)

    async def close(self) -> None:
        """Gracefully stop WS and close HTTP session."""
        self._ws_running = False
        for task in (self._ws_task, self._user_hub_task):
            if task:
                task.cancel()
                try:
                    await task
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

        logger.info(
            "Authenticated as %s, token expires at %s",
            self._username,
            datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        )

        # Resolve account — /Auth/loginKey does not return accountId,
        # so we have to POST /Account/search and pick by requested id.
        await self._resolve_account()

    async def _resolve_account(self) -> None:
        """
        Fetch the list of accounts via /Account/search and select the one
        matching TOPSTEPX_ACCOUNT_ID. Raises if not found.
        """
        url = f"{self._api_url}/Account/search"
        async with self._session.post(
            url, headers=self._auth_headers(), json={}
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise TopstepXAuthError(
                    f"/Account/search failed ({resp.status}): {text}"
                )
            data = await resp.json()

        accounts = data.get("accounts") or []
        if not accounts:
            raise TopstepXAuthError(
                f"No accounts returned by /Account/search: {data}"
            )

        # If no explicit ID requested, default to first tradable account
        if not self._requested_account_id:
            tradable = [a for a in accounts if a.get("canTrade")]
            chosen = tradable[0] if tradable else accounts[0]
            logger.warning(
                "TOPSTEPX_ACCOUNT_ID not set — defaulting to %s (%s)",
                chosen.get("id"), chosen.get("name"),
            )
        else:
            chosen = next(
                (a for a in accounts if str(a.get("id")) == self._requested_account_id),
                None,
            )
            if chosen is None:
                available = ", ".join(
                    f"{a.get('id')} ({a.get('name')})" for a in accounts
                )
                raise TopstepXAuthError(
                    f"Requested account {self._requested_account_id} not found. "
                    f"Available: {available}"
                )

        self._account_id = str(chosen["id"])
        self._account_info = chosen
        logger.info(
            "Selected account %s (%s) — balance=$%.2f canTrade=%s simulated=%s",
            chosen.get("id"),
            chosen.get("name"),
            float(chosen.get("balance", 0)),
            chosen.get("canTrade"),
            chosen.get("simulated"),
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

    async def _resolve_contract_id(self, symbol: str) -> str:
        """
        Return a ProjectX contractId (e.g. 'CON.F.US.MNQ.M26') for a
        short symbol like 'MNQ'. Results are cached until the client dies.

        If the caller already passes a fully-qualified contractId
        (starts with 'CON.'), return it as-is.
        """
        symbol = symbol.strip()
        if symbol.startswith("CON."):
            return symbol

        cached = self._contract_cache.get(symbol.upper())
        if cached:
            return cached

        contract = await self.lookup_contract(symbol, live=False)
        if contract is None or "id" not in contract:
            raise TopstepXOrderError(
                f"Could not resolve contractId for symbol '{symbol}'"
            )
        contract_id = str(contract["id"])
        self._contract_cache[symbol.upper()] = contract_id
        return contract_id

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
        symbol    : short ("MNQ") or full contractId ("CON.F.US.MNQ.M26")
        side      : "buy" or "sell"
        contracts : number of contracts (positive integer)
        """
        _validate_order_params(symbol, side, contracts)
        contract_id = await self._resolve_contract_id(symbol)
        payload = _build_order_payload(
            contract_id=contract_id,
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
        reference_price: Optional[float] = None,
        max_deviation_pct: float = 0.02,
    ) -> OrderResult:
        """Submit a limit order at ``limit_price``.

        Parameters
        ----------
        reference_price : float | None
            Current market reference (last trade or mid). When provided, the
            limit price is rejected pre-submission if it deviates from this
            anchor by more than ``max_deviation_pct``. This guards against
            the TopstepX "Invalid price outside allowed range" errorCode=2
            which silently rejected 6 bracket targets on 2026-04-17.
        max_deviation_pct : float
            Maximum allowed fractional deviation from ``reference_price``.
            Default 0.02 (±2%). TopstepX's actual range is narrower and
            undocumented, but ±2% catches the mis-computed targets we've
            seen without producing false positives for legitimate setups.
        """
        _validate_order_params(symbol, side, contracts)
        if limit_price <= 0:
            raise TopstepXOrderError("limit_price must be positive")
        if reference_price is not None and reference_price > 0:
            deviation = abs(limit_price - reference_price) / reference_price
            if deviation > max_deviation_pct:
                raise TopstepXOrderError(
                    f"limit_price ${limit_price:.2f} deviates {deviation * 100:.2f}% "
                    f"from reference ${reference_price:.2f} "
                    f"(max {max_deviation_pct * 100:.2f}%). Refusing to submit — "
                    f"broker would reject with 'Invalid price outside allowed range'."
                )
        contract_id = await self._resolve_contract_id(symbol)
        payload = _build_order_payload(
            contract_id=contract_id,
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
        contract_id = await self._resolve_contract_id(symbol)
        payload = _build_order_payload(
            contract_id=contract_id,
            side=side,
            contracts=contracts,
            order_type=ORDER_STOP,
            account_id=self._account_id,
            stop_price=stop_price,
        )
        return await self._submit_order(payload, symbol, side, contracts, ORDER_STOP)

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order by order_id via POST /Order/cancel.

        Returns True if the API confirms success, False if the order was
        not found / already closed / otherwise rejected.
        """
        if not order_id:
            raise TopstepXOrderError("order_id cannot be empty")
        try:
            data = await self._post(
                "/Order/cancel",
                {
                    "accountId": int(self._account_id),
                    "orderId": int(order_id),
                },
            )
        except aiohttp.ClientResponseError as exc:
            raise TopstepXOrderError(
                f"Failed to cancel order {order_id}: {exc}"
            ) from exc

        success = bool(data.get("success"))
        if success:
            logger.info("Cancelled order %s", order_id)
            return True

        err_code = data.get("errorCode")
        err_msg = data.get("errorMessage") or ""
        logger.warning(
            "Cancel %s rejected (errorCode=%s): %s", order_id, err_code, err_msg,
        )
        return False

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
        success = bool(data.get("success"))
        err_code = data.get("errorCode")
        err_msg = str(data.get("errorMessage") or "")

        if success:
            status = "submitted"
            message = ""
        else:
            status = "rejected"
            message = f"errorCode={err_code} {err_msg}".strip()

        filled_price = data.get("filledPrice") or data.get("avgPrice")

        result = OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            contracts=contracts,
            status=status,
            filled_price=float(filled_price) if filled_price else None,
            message=message,
        )
        logger.info(
            "Order %s | %s %s %d x %s status=%s %s",
            order_id, order_type, side.upper(), contracts, symbol,
            status, message,
        )
        return result

    # ------------------------------------------------------------------ #
    # Positions                                                            #
    # ------------------------------------------------------------------ #

    async def get_positions(self) -> list[Position]:
        """
        Return all open positions for the current account.
        Positions with zero contracts are excluded.
        A 404 response means the account has no position record yet — treated
        as an empty list (INFO), not an error.
        """
        try:
            data = await self._get(f"/Position/account/{self._account_id}")
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                logger.info(
                    "get_positions: no open positions (404 — account has no position record)"
                )
                return []
            raise

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
    # Contract lookup + Historical bars (REST)                             #
    # ------------------------------------------------------------------ #

    async def lookup_contract(
        self,
        search_text: str,
        live: bool = False,
    ) -> Optional[dict]:
        """
        Find the first matching contract via POST /Contract/search.

        Returns the contract dict ({id, name, description, ...}) or None.
        Use `live=True` to search live feeds, False for sim/historical.
        """
        payload = {"searchText": search_text, "live": live}
        data = await self._post("/Contract/search", payload)
        contracts = data.get("contracts") or []
        if not contracts:
            return None
        return contracts[0]

    async def get_historical_bars(
        self,
        contract_id: str,
        start: datetime,
        end: datetime,
        unit: int = 2,
        unit_number: int = 1,
        limit: int = 2000,
        include_partial: bool = False,
    ) -> list[dict]:
        """
        Fetch historical bars via POST /History/retrieveBars.

        Parameters
        ----------
        contract_id : e.g. "CON.F.US.MNQ.M26"
        start, end  : timezone-aware datetimes (UTC recommended)
        unit        : 1=Second 2=Minute 3=Hour 4=Day 5=Week 6=Month
        unit_number : bar size (e.g. 1 → 1-minute when unit=2)
        limit       : max bars returned
        include_partial: include the bar currently forming

        Returns
        -------
        list[dict] — each dict uses the same shape as live WS bars:
            {symbol, timestamp (pd.Timestamp UTC), open, high, low, close, volume}
        """
        payload = {
            "contractId": contract_id,
            "live": False,
            "startTime": start.isoformat(),
            "endTime": end.isoformat(),
            "unit": unit,
            "unitNumber": unit_number,
            "limit": limit,
            "includePartialBar": include_partial,
        }
        data = await self._post("/History/retrieveBars", payload)
        raw_bars = data.get("bars") or []

        parsed: list[dict] = []
        for row in raw_bars:
            # Inject the contract id so _parse_bar_message keeps the symbol
            if "symbol" not in row and "contractId" not in row:
                row = {**row, "contractId": contract_id}
            bar = _parse_bar_message(row)
            if bar is not None:
                parsed.append(bar)

        # API returns newest-first; our pipeline expects oldest-first
        parsed.sort(key=lambda b: b["timestamp"])
        logger.info(
            "Historical bars: %d parsed for %s (unit=%d x%d)",
            len(parsed), contract_id, unit, unit_number,
        )
        return parsed

    # ------------------------------------------------------------------ #
    # Real-time streaming — SignalR user hub → order fill events         #
    # ------------------------------------------------------------------ #

    # User hub URL — receives GatewayUserOrder fill notifications
    _USER_HUB = "wss://rtc.topstepx.com/hubs/user"

    async def _user_hub_listener_loop(self) -> None:
        """Outer retry loop for the user/account hub (order fills).

        Mirrors the market hub retry pattern: exponential backoff,
        re-auth on reconnect. Does NOT have a hard max-retries limit
        (fills are too critical to give up on).
        """
        backoff = WS_RECONNECT_BASE_S
        while self._ws_running:
            try:
                await self._connect_user_hub_and_listen()
                backoff = WS_RECONNECT_BASE_S  # reset on clean exit
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "User hub disconnected (%s). Reconnecting in %.1fs", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_MAX_S)
                try:
                    await self._ensure_token()
                except Exception:
                    pass

    async def _connect_user_hub_and_listen(self) -> None:
        """Connect to the TopstepX user hub and listen for GatewayUserOrder events.

        ProjectX user hub emits GatewayUserOrder(accountId, orderData) whenever
        an order status changes. Status code 2 = Filled (complete fill).
        We route complete fills to ``_fill_callback`` so the engine can call
        ``_on_trade_closed()`` and update daily risk accounting.
        """
        token = await self._ensure_token()
        loop = asyncio.get_running_loop()
        url = f"{self._USER_HUB}?access_token={token}"
        conn = HubConnectionBuilder()\
            .with_url(url, options={"skip_negotiation": True})\
            .build()

        disconnected = asyncio.Event()

        def _on_order_update(args: list) -> None:
            """Runs in signalrcore's thread — bridge fills to asyncio loop."""
            try:
                # GatewayUserOrder args shape: [accountId, orderData] or [orderData]
                order_data: dict
                if len(args) >= 2 and isinstance(args[1], dict):
                    order_data = args[1]
                elif len(args) >= 1 and isinstance(args[0], dict):
                    order_data = args[0]
                else:
                    return

                # ProjectX status codes: 2 = Filled
                if order_data.get("status") != 2:
                    return

                # Ignore partial fills — wait for the complete fill event
                filled_qty = order_data.get("filledQuantity") or 0
                total_qty = order_data.get("qty") or order_data.get("contracts") or 0
                if filled_qty and total_qty and int(filled_qty) < int(total_qty):
                    return

                oid = order_data.get("orderId") or order_data.get("id")
                fp = order_data.get("filledPrice") or 0
                logger.info("User hub: order %s FILLED @ %.2f", oid, fp)

                if self._fill_callback is not None:
                    asyncio.run_coroutine_threadsafe(
                        self._fill_callback(order_data), loop
                    )
            except Exception as exc:
                logger.exception("User hub order handler error: %s", exc)

        def _on_open() -> None:
            logger.info(
                "User hub: connected, subscribing account %s", self._account_id
            )
            conn.send("SubscribeAccounts", [self._account_id])

        # Capture whether the disconnect came from an error or a clean
        # close — the outer retry loop needs this to decide whether to
        # reset the exponential backoff (clean exit) or escalate
        # (error-disconnect). Without this, the listener returned
        # normally on error and the outer loop reset backoff to the base
        # every iteration → retry storm every ~1s on weekends when the
        # user hub is closed. 2026-04-19 boot verification caught it.
        had_error = False

        def _on_close() -> None:
            logger.warning("User hub: disconnected")
            loop.call_soon_threadsafe(disconnected.set)

        def _on_error(err: Exception) -> None:
            nonlocal had_error
            had_error = True
            logger.error("User hub: error — %s", err)
            loop.call_soon_threadsafe(disconnected.set)

        conn.on("GatewayUserOrder", _on_order_update)
        conn.on_open(_on_open)
        conn.on_close(_on_close)
        conn.on_error(_on_error)

        logger.info("User hub: connecting to %s", self._USER_HUB)
        conn.start()
        try:
            while self._ws_running and not disconnected.is_set():
                await asyncio.sleep(1)
        finally:
            try:
                conn.stop()
            except Exception:
                pass
            logger.info("User hub: connection stopped")

        # Re-raise the error-disconnect to the outer retry loop so its
        # exponential backoff actually grows on repeated failures. Clean
        # disconnects (user initiated / _ws_running=False) fall through.
        if had_error and self._ws_running:
            raise TopstepXConnectionError(
                "User hub: disconnected with error (see previous log lines)"
            )

    # ------------------------------------------------------------------ #
    # Real-time streaming — SignalR market hub → 1-min bar aggregation   #
    # ------------------------------------------------------------------ #
    #
    # TopstepX (ProjectX) streams via ASP.NET SignalR Core hubs:
    #   Market hub : wss://rtc.topstepx.com/hubs/market
    #   Events     : GatewayQuote(contractId, payload)
    #                GatewayTrade(contractId, [trade, ...])
    #   Subscribe  : connection.send("SubscribeContractQuotes", [contractId])
    #                connection.send("SubscribeContractTrades", [contractId])
    #
    # signalrcore is thread-based; we bridge completed bars back to the
    # asyncio loop via loop.call_soon_threadsafe → bar_callbacks.
    # ------------------------------------------------------------------ #

    # Market hub URL (the .env WS_URL was wrong — real host is rtc.topstepx.com)
    _MARKET_HUB = "wss://rtc.topstepx.com/hubs/market"

    def subscribe_bars(self, symbol: str, callback: Callable[[dict], Any]) -> None:
        """
        Register a callback for real-time 1-min bar updates for symbol.

        The callback receives a dict:
            {symbol, timestamp (pd.Timestamp UTC), open, high, low, close, volume}

        Can be called before or after connect().
        """
        self._subscribed_symbols.add(symbol.upper())
        self._bar_callbacks.append(callback)
        logger.info("Subscribed to 1-min bars: %s", symbol)

    def set_fill_callback(self, callback: Callable) -> None:
        """Register callback invoked when any order is fully filled.

        The callback signature is: ``async def cb(order_data: dict) -> None``
        where ``order_data`` is the raw GatewayUserOrder payload from the
        TopstepX user hub (contains orderId, filledPrice, status, etc.).
        """
        self._fill_callback = callback

    def set_on_ws_exhausted(self, callback: Callable[[], Any]) -> None:
        """Register an emergency-flatten callback invoked when the SignalR
        reconnect loop exhausts WS_MAX_RETRIES. Without this hook, the
        listener task raised TopstepXConnectionError and the engine
        crashed with open positions unmanaged (audit finding 2026-04-17).
        The callback is called FIRST (best-effort flatten), then the
        exception is re-raised so the engine's outer supervisor sees it.
        Callback can be sync or return a coroutine."""
        self._on_ws_exhausted = callback

    async def _ws_listener_loop(self) -> None:
        """
        Outer retry loop around the SignalR connection. Runs as an asyncio
        task created by connect(). Reconnects with exponential backoff.
        """
        retries = 0
        backoff = WS_RECONNECT_BASE_S

        while self._ws_running:
            try:
                await self._signalr_connect_and_listen()
                retries = 0
                backoff = WS_RECONNECT_BASE_S
            except Exception as exc:
                if not self._ws_running:
                    break
                retries += 1
                if retries > WS_MAX_RETRIES:
                    logger.error(
                        "SignalR: exceeded max retries (%d). Giving up.", WS_MAX_RETRIES,
                    )
                    # Emergency flatten BEFORE propagating. We've lost the
                    # market feed — without a price stream we can't monitor
                    # stops, can't detect VPIN spikes, can't exit on
                    # hard-close. Any open position here is uncovered risk.
                    cb = getattr(self, "_on_ws_exhausted", None)
                    if cb is not None:
                        try:
                            result = cb()
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as cb_exc:
                            logger.critical(
                                "on_ws_exhausted callback failed: %s", cb_exc, exc_info=True,
                            )
                    raise TopstepXConnectionError(
                        f"SignalR failed after {WS_MAX_RETRIES} retries: {exc}"
                    ) from exc

                logger.warning(
                    "SignalR disconnected (%s). Retry %d/%d in %.1fs",
                    exc, retries, WS_MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_MAX_S)

                try:
                    await self._ensure_token()
                except TopstepXAuthError as auth_exc:
                    logger.error("Re-auth failed during reconnect: %s", auth_exc)
                    await asyncio.sleep(backoff)

    async def _signalr_connect_and_listen(self) -> None:
        """
        Connect to the SignalR market hub, subscribe to GatewayTrade for
        all registered symbols, and aggregate ticks into 1-min bars.

        signalrcore runs in its own thread; we use an asyncio.Event to
        detect disconnection from the calling coroutine.
        """
        import pandas as pd

        token = await self._ensure_token()
        loop = asyncio.get_running_loop()

        url = f"{self._MARKET_HUB}?access_token={token}"
        conn = HubConnectionBuilder()\
            .with_url(url, options={"skip_negotiation": True})\
            .build()

        # ── Bar aggregation state (per-contract) ─────────────────────
        # Keys: contractId → dict with OHLCV accumulators.
        bar_state: dict[str, dict] = {}
        bar_lock = threading.Lock()

        def _flush_bar(cid: str) -> Optional[dict]:
            """Return a completed bar dict and reset the accumulator.
            MUST be called with bar_lock already held."""
            s = bar_state.get(cid)
            if s is None or s["count"] == 0:
                return None
            bar = {
                "symbol": cid,
                "timestamp": pd.Timestamp(s["minute_ts"], unit="s", tz="UTC"),
                "open": s["open"],
                "high": s["high"],
                "low": s["low"],
                "close": s["close"],
                "volume": s["volume"],
            }
            bar_state[cid] = _empty_bar(s["minute_ts"])
            return bar

        def _empty_bar(minute_ts: int) -> dict:
            return {
                "minute_ts": minute_ts,
                "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0,
                "volume": 0, "count": 0,
            }

        def _emit_bar(bar: dict) -> None:
            """Push a completed bar to all registered callbacks (thread-safe)."""
            logger.info(
                "WS: %s bar [%s] O:%.2f H:%.2f L:%.2f C:%.2f V:%d",
                bar["symbol"], bar["timestamp"],
                bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"],
            )
            for cb in self._bar_callbacks:
                try:
                    loop.call_soon_threadsafe(cb, bar)
                except Exception as exc:
                    logger.exception("Bar callback schedule failed: %s", exc)

        # ── GatewayTrade handler (runs in signalrcore's thread) ──────
        def _on_trade(args: list) -> None:
            cid = args[0]
            trades = args[1] if isinstance(args[1], list) else [args[1]]

            with bar_lock:
                for t in trades:
                    price = float(t.get("price", 0))
                    vol = int(t.get("volume", 0))
                    ts_str = t.get("timestamp", "")
                    if price == 0 or not ts_str:
                        continue
                    try:
                        ts = pd.Timestamp(ts_str).timestamp()
                    except Exception:
                        continue
                    minute_ts = int(ts) - int(ts) % 60  # floor to minute

                    s = bar_state.get(cid)
                    if s is None or s["minute_ts"] != minute_ts:
                        # New minute — flush the old bar if it exists
                        if s is not None and s["count"] > 0:
                            old = _flush_bar(cid)
                            if old:
                                _emit_bar(old)
                        bar_state[cid] = _empty_bar(minute_ts)
                        s = bar_state[cid]

                    if s["count"] == 0:
                        s["open"] = price
                    s["high"] = max(s["high"], price) if s["count"] > 0 else price
                    s["low"] = min(s["low"], price) if s["count"] > 0 else price
                    s["close"] = price
                    s["volume"] += vol
                    s["count"] += 1

        # ── GatewayQuote handler (runs in signalrcore's thread) ──────
        # We only log the first quote per contract for the session snapshot.
        _first_quote_seen: set[str] = set()

        def _on_quote(args: list) -> None:
            cid = args[0]
            q = args[1]
            if cid not in _first_quote_seen and "lastPrice" in q:
                _first_quote_seen.add(cid)
                logger.info(
                    "WS: %s session snapshot last=%.2f bid=%.2f ask=%.2f "
                    "open=%.2f high=%.2f low=%.2f vol=%s",
                    cid,
                    q.get("lastPrice", 0), q.get("bestBid", 0), q.get("bestAsk", 0),
                    q.get("open", 0), q.get("high", 0), q.get("low", 0),
                    q.get("volume", "?"),
                )

        # ── Lifecycle events ─────────────────────────────────────────
        disconnected = asyncio.Event()

        def _on_open() -> None:
            logger.info("SignalR: connected to market hub")
            # Resolve contract IDs for subscribed symbols
            for sym in self._subscribed_symbols:
                cid = self._contract_cache.get(sym)
                if not cid:
                    logger.warning("SignalR: no cached contract for %s, skipping", sym)
                    continue
                conn.send("SubscribeContractQuotes", [cid])
                conn.send("SubscribeContractTrades", [cid])
                logger.info("SignalR: subscribed to quotes+trades for %s (%s)", sym, cid)

        def _on_close() -> None:
            logger.warning("SignalR: market hub disconnected")
            loop.call_soon_threadsafe(disconnected.set)

        def _on_error(err: Exception) -> None:
            logger.error("SignalR: error — %s", err)
            loop.call_soon_threadsafe(disconnected.set)

        conn.on("GatewayTrade", _on_trade)
        conn.on("GatewayQuote", _on_quote)
        conn.on_open(_on_open)
        conn.on_close(_on_close)
        conn.on_error(_on_error)

        # Resolve contract IDs before connecting so _on_open has them
        for sym in self._subscribed_symbols:
            if sym not in self._contract_cache:
                try:
                    cid = await self._resolve_contract_id(sym)
                    logger.info("Resolved %s -> %s", sym, cid)
                except Exception as exc:
                    logger.warning("Could not resolve %s: %s", sym, exc)

        # Start signalrcore in its own thread
        logger.info("SignalR: starting connection to %s", self._MARKET_HUB)
        conn.start()

        try:
            # Wait until disconnect or shutdown
            while self._ws_running and not disconnected.is_set():
                await asyncio.sleep(1)

                # Periodically flush bars that haven't completed due to
                # low-activity periods (e.g., 30s without a new-minute tick).
                # This ensures the pipeline gets bars even during slow periods.
                now_ts = int(time.time())
                current_minute = now_ts - now_ts % 60
                with bar_lock:
                    for cid, s in list(bar_state.items()):
                        if s["count"] > 0 and s["minute_ts"] < current_minute:
                            old = _flush_bar(cid)
                            if old:
                                _emit_bar(old)
        finally:
            try:
                conn.stop()
            except Exception:
                pass
            logger.info("SignalR: connection stopped")


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
    contract_id: str,
    side: str,
    contracts: int,
    order_type: str,
    account_id: str,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> dict:
    """
    Build the ProjectX `/Order/place` payload.

    Wire format requires integer type/side codes and a fully qualified
    contractId. Nulls for unused price fields must still be present.
    """
    side_code = _SIDE_CODES.get(side.lower())
    if side_code is None:
        raise TopstepXOrderError(f"Invalid side: {side!r}")

    type_code = _TYPE_CODES.get(order_type)
    if type_code is None:
        raise TopstepXOrderError(f"Invalid order_type: {order_type!r}")

    payload: dict[str, Any] = {
        "accountId": int(account_id),
        "contractId": contract_id,
        "type": type_code,
        "side": side_code,
        "size": contracts,
        "limitPrice": limit_price,
        "stopPrice": stop_price,
        "trailPrice": None,
        "customTag": None,
        "linkedOrderId": None,
    }
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
            msg.get("time") or msg.get("datetime") or
            msg.get("t") or ""
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
