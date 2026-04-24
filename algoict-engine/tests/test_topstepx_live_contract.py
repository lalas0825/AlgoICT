"""
tests/test_topstepx_live_contract.py
=====================================
Integration tests against the LIVE TopstepX ProjectX API.

These tests are **opt-in** and require valid `.env` credentials. They hit
the broker's real endpoints with READ-ONLY operations (auth, account
search, position search, open order search, contract resolve) to verify
our broker client's API contract matches what TopstepX actually returns.

Past bugs that these tests would have caught:

* **Bug J (2026-04-24)** — `get_positions` called ``GET /Position/account/{id}``
  which always returned 404; the bot was blind to real positions for an
  entire session. A ``test_searchopen_returns_empty_200`` test run against
  the real API would have surfaced the 404 immediately.

* **Bug K (2026-04-24)** — User Hub ``SubscribeAccounts`` was called with
  an argument but the server signature takes none; every WS connect errored
  and fell back to (broken) polling. The User Hub contract is hard to
  integration-test without opening an actual SignalR connection, but the
  REST endpoints can be covered here.

Run manually:
    cd algoict-engine
    python -m pytest tests/test_topstepx_live_contract.py -v --runintegration

CI is currently expected to skip these (no credentials in CI runner).
"""
from __future__ import annotations

import os
import pytest
import pytest_asyncio
import aiohttp

from config import (
    TOPSTEPX_API_KEY,
    TOPSTEPX_API_URL,
    TOPSTEPX_USERNAME,
)


# The --runintegration flag is registered in conftest.py (not required by
# default pytest — falls back to env var TOPSTEPX_INTEGRATION=1).
def _integration_enabled() -> bool:
    return bool(
        os.environ.get("TOPSTEPX_INTEGRATION")
        or any(a == "--runintegration" for a in os.sys.argv)
    )


pytestmark = pytest.mark.skipif(
    not _integration_enabled() or not TOPSTEPX_USERNAME or not TOPSTEPX_API_KEY,
    reason="Integration tests require TOPSTEPX_INTEGRATION=1 + .env credentials",
)


@pytest_asyncio.fixture
async def authed_session():
    """Authenticate once per module and yield (session, headers, account_id)."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{TOPSTEPX_API_URL}/Auth/loginKey",
            json={"userName": TOPSTEPX_USERNAME, "apiKey": TOPSTEPX_API_KEY},
        ) as resp:
            assert resp.status == 200, f"Auth failed: {resp.status}"
            data = await resp.json()
            assert data.get("token"), "No token returned by /Auth/loginKey"
        headers = {
            "Authorization": f"Bearer {data['token']}",
            "Content-Type": "application/json",
        }
        # Find a tradable account
        async with session.post(
            f"{TOPSTEPX_API_URL}/Account/search",
            json={"onlyActiveAccounts": True},
            headers=headers,
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
        accounts = data.get("accounts") or []
        assert accounts, "No active accounts — cannot test position endpoints"
        account_id = int(accounts[0]["id"])
        yield session, headers, account_id


class TestAuthContract:
    """Verify our auth flow actually returns a usable JWT."""

    @pytest.mark.asyncio
    async def test_login_returns_token(self, authed_session):
        session, headers, _ = authed_session
        token_str = headers["Authorization"].split(" ", 1)[1]
        assert len(token_str) > 20, "Token suspiciously short"


class TestPositionEndpointContract:
    """
    Bug J regression: GET /Position/account/{id} does NOT exist.
    POST /Position/searchOpen DOES.

    If TopstepX ever changes these, CI will catch it.
    """

    @pytest.mark.asyncio
    async def test_searchopen_post_is_200(self, authed_session):
        """POST /Position/searchOpen must return 200 with {"positions":[...]}."""
        session, headers, account_id = authed_session
        async with session.post(
            f"{TOPSTEPX_API_URL}/Position/searchOpen",
            json={"accountId": account_id},
            headers=headers,
        ) as resp:
            assert resp.status == 200, (
                f"POST /Position/searchOpen returned {resp.status} — "
                f"broker API contract broken, get_positions() will fail."
            )
            data = await resp.json()
        assert "positions" in data, (
            f"Response missing 'positions' key: {data}"
        )
        assert isinstance(data["positions"], list)
        assert data.get("success") is True, f"success=False: {data}"

    @pytest.mark.asyncio
    async def test_legacy_get_path_is_not_a_valid_endpoint(self, authed_session):
        """
        GET /Position/account/{id} should NOT work (Bug J regression).

        If TopstepX later adds this endpoint, that's fine — we'd want to
        know. But as of 2026-04-24 the route returns 404.
        """
        session, headers, account_id = authed_session
        async with session.get(
            f"{TOPSTEPX_API_URL}/Position/account/{account_id}",
            headers=headers,
        ) as resp:
            # Accept either 404 (not found) or 405 (method not allowed)
            assert resp.status in (404, 405), (
                f"Unexpected status {resp.status} on legacy GET path — "
                f"if TopstepX now supports this, update broker client too."
            )


class TestOrderEndpointContract:
    """
    Verify /Order/searchOpen contract (used by poll + reconcile paths).
    """

    @pytest.mark.asyncio
    async def test_searchopen_post_is_200(self, authed_session):
        session, headers, account_id = authed_session
        async with session.post(
            f"{TOPSTEPX_API_URL}/Order/searchOpen",
            json={"accountId": account_id},
            headers=headers,
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
        assert "orders" in data, f"Response missing 'orders' key: {data}"
        assert isinstance(data["orders"], list)


class TestContractResolveContract:
    """
    Verify /Contract/search for symbol → contractId resolution.
    Broker client's _resolve_contract_id depends on this.
    """

    @pytest.mark.asyncio
    async def test_mnq_resolves(self, authed_session):
        session, headers, _ = authed_session
        async with session.post(
            f"{TOPSTEPX_API_URL}/Contract/search",
            json={"searchText": "MNQ", "live": False},
            headers=headers,
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
        contracts = data.get("contracts") or []
        # TopstepX stores the short name in `name` (e.g. 'MNQM6') and the
        # fully-qualified contractId in `id` (e.g. 'CON.F.US.MNQ.M26').
        mnq = [
            c for c in contracts
            if "MNQ" in str(c.get("id", "")) or "MNQ" in str(c.get("name", ""))
        ]
        assert mnq, f"No MNQ contract found: {data}"
        # Must have an id field — broker client reads contract["id"]
        assert all("id" in c for c in mnq), (
            f"Contract missing 'id' field: {mnq[0]}"
        )
