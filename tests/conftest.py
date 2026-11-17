"""Shared test setup: isolation guards that apply to every test.

Autouse fixtures (nothing to request, they always run):
    _isolated_home   HOME points into tmp_path, so the real ~/.hvcwatch is unreachable.
    settings         Real, frozen Settings bound into every module that imports it.
    http_mock        `responses` is active, so an unregistered HTTP call raises.
    _clear_ticker_overview_cache   Empties utils._lookup_ticker_overview before and after.
    sleeps                         Records retry waits instead of sleeping, jitter off.

Opt-in fixtures (request them by name):
    override_settings   Factory that swaps in a changed copy of `settings`.
    db_path             The SQLite file used by the default `settings`.
    fake_discord        Factory that registers a Discord webhook that accepts POSTs.
    massive             Factory that fakes the Massive ticker overview endpoint.
"""

from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import responses

from hvcwatch import utils
from hvcwatch.config import Settings
from hvcwatch.utils import MASSIVE_TICKER_URL
from tests.helpers import WEBHOOK_URL

# 📦 `settings` is bound by name in each of these modules (`from ... import settings`),
# so patching hvcwatch.config.settings alone would change none of them.
SETTINGS_MODULES = ("main", "email_monitor", "db", "notification", "utils")


def _bind_settings(monkeypatch: pytest.MonkeyPatch, value: Settings) -> None:
    """🔗 Point `settings` in every module that imports it at `value`."""
    for module in SETTINGS_MODULES:
        monkeypatch.setattr(f"hvcwatch.{module}.settings", value)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """🏠 Set HOME to a directory inside tmp_path so Path.home() stays in the sandbox."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """🗄️ Path of the throwaway SQLite database used by the default `settings`."""
    return tmp_path / "alerts.db"


@pytest.fixture(autouse=True)
def settings(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """
    ⚙️ Real Settings built from an explicit mapping, bound into all five modules.

    Never reads os.environ, so the result is the same on every machine. The
    database lives in tmp_path and no Massive API key is set. Use
    `override_settings` to change fields, never a MagicMock.
    """
    value = Settings.from_env({
        "FASTMAIL_USER": "test_user",
        "FASTMAIL_PASS": "test_password",
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test",
        "HVCWATCH_DB_PATH": str(db_path),
    })
    _bind_settings(monkeypatch, value)
    return value


@pytest.fixture
def override_settings(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Settings]:
    """
    🔁 Factory: `override_settings(imap_port=1143)` swaps in a changed copy.

    Uses dataclasses.replace on the baseline `settings`, rebinds the copy in all
    five modules, and returns it. Calls build on the baseline, not on each other.
    Undone automatically at the end of the test.
    """

    def _override(**changes: Any) -> Settings:
        value = replace(settings, **changes)
        _bind_settings(monkeypatch, value)
        return value

    return _override


@pytest.fixture(autouse=True)
def http_mock() -> Iterator[responses.RequestsMock]:
    """
    🔌 Activate `responses` for every test.

    An HTTP call with no registered response raises requests.ConnectionError
    instead of reaching the network. Register replies with `http_mock.get(...)`.
    Registered but unused responses are allowed.
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture(autouse=True)
def _clear_ticker_overview_cache() -> Iterator[None]:
    """
    🧹 Empty the ticker overview cache around each test.

    _get_nyse_calendar is deliberately left alone because it is slow to build.
    """
    utils._lookup_ticker_overview.cache_clear()
    yield
    utils._lookup_ticker_overview.cache_clear()


@pytest.fixture
def fake_discord(http_mock: responses.RequestsMock) -> Callable[..., None]:
    """
    🎭 Factory: `fake_discord(url)` registers a Discord webhook that accepts POSTs.

    Replies 200 with a JSON body by default. Any status works, 429 included,
    because the `sleeps` fixture stops the retry waits from really sleeping.
    """

    def _register(url: str = WEBHOOK_URL, status: int = 200, **reply: Any) -> None:
        if "body" not in reply:  # 🧩 responses rejects json and body together
            reply.setdefault("json", {"id": "1"})
        http_mock.post(url, status=status, **reply)

    return _register


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """
    💤 Record every retry wait instead of sleeping.

    Also turns jitter off, so the waits are exact (1, 2, 4 seconds) and no
    test really sleeps. Returns the sleep mock for assertions.
    """
    sleep = MagicMock()
    monkeypatch.setattr("hvcwatch.notification.time.sleep", sleep)
    monkeypatch.setattr("hvcwatch.notification._with_jitter", lambda delay: delay)
    return sleep


@pytest.fixture
def massive(
    http_mock: responses.RequestsMock, override_settings: Callable[..., Settings]
) -> Callable[..., None]:
    """
    🏢 Factory: `massive("AAPL", "Apple Inc.", "CS")` fakes the Massive overview call.

    Sets a Massive API key (without one, lookups are skipped), then registers the
    ticker endpoint. Pass name=None to fake a 404 (unknown ticker).
    """
    override_settings(massive_api_key="test-key")

    def _register(ticker: str, name: str | None, type_: str | None = None) -> None:
        url = MASSIVE_TICKER_URL.format(ticker=ticker.upper())
        if name is None:
            http_mock.get(url, status=404, json={"status": "NOT_FOUND"})
            return
        results = {"name": name, **({"type": type_} if type_ else {})}
        http_mock.get(url, json={"results": results})

    return _register
