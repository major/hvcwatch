"""Shared test setup: isolation guards that apply to every test.

Autouse fixtures (nothing to request, they always run):
    _isolated_home   HOME points into tmp_path, so the real ~/.hvcwatch is unreachable.
    settings         Real, frozen Settings returned by config.get_settings().
    http_mock        `responses` is active (requests, used by Discord), so an unregistered call raises.
    _httpx2_guard    `httpx2_mock` is active (httpx2, used by Massive), so an unregistered call raises.
    _clear_ticker_overview_cache   Empties utils._lookup_ticker_overview before and after.
    sleeps                         Records retry waits instead of sleeping, jitter off.

Opt-in fixtures (request them by name):
    override_settings   Factory that swaps in a changed copy of `settings`.
    db_path             The SQLite file used by the default `settings`.
    fake_discord        Factory that registers a Discord webhook that accepts POSTs.
    massive             Factory that fakes the Massive ticker overview endpoint.
    fake_mailbox        Factory that swaps imap_tools MailBox for a scripted FakeMailBox.
    hvcwatch_logger     The hvcwatch logger, cleaned before and restored after the test.
"""

from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from logging import Logger, getLogger
from pathlib import Path
from typing import Any, NamedTuple, Self
from unittest.mock import MagicMock

import pytest
import responses
from imap_tools.message import MailMessage
from pytest_httpx2 import HTTPXMock

from hvcwatch import utils
from hvcwatch.config import Settings
from hvcwatch.logging_config import LOGGER_NAME
from hvcwatch.utils import MASSIVE_TICKER_URL
from tests.helpers import WEBHOOK_URL, ScriptExhausted


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """
    🧩 Let `httpx2_mock` keep replies that a test never uses, like `responses` does.

    The plugin fails a test for unused replies by default. Turn that off here.
    Unregistered calls still raise, and the plugin also fails the test at teardown
    for them, even if the code caught the error. A test that expects the error can
    opt out with `@pytest.mark.httpx2_mock(assert_all_requests_were_expected=False)`.
    """
    marker = pytest.mark.httpx2_mock(assert_all_responses_were_requested=False)
    for item in items:
        item.add_marker(marker)


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
    ⚙️ Real Settings built from an explicit mapping, returned by get_settings().

    Patches `config.get_settings` so every caller gets this value. Never reads
    os.environ, so the result is the same on every machine. The database lives
    in tmp_path and no Massive API key is set. Use `override_settings` to change
    fields, never a MagicMock.
    """
    value = Settings.from_env({
        "FASTMAIL_USER": "test_user",
        "FASTMAIL_PASS": "test_password",
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test",
        "HVCWATCH_DB_PATH": str(db_path),
    })
    monkeypatch.setattr("hvcwatch.config.get_settings", lambda: value)
    return value


@pytest.fixture
def override_settings(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Settings]:
    """
    🔁 Factory: `override_settings(imap_port=1143)` swaps in a changed copy.

    Uses dataclasses.replace on the baseline `settings`, patches get_settings to
    return the copy, and returns it. Calls build on the baseline, not on each
    other. Undone automatically at the end of the test.
    """

    def _override(**changes: Any) -> Settings:
        value = replace(settings, **changes)
        monkeypatch.setattr("hvcwatch.config.get_settings", lambda: value)
        return value

    return _override


@pytest.fixture(autouse=True)
def http_mock() -> Iterator[responses.RequestsMock]:
    """
    🔌 Activate `responses` for every test (requests, used by Discord).

    An HTTP call with no registered response raises requests.ConnectionError
    instead of reaching the network. Register replies with `http_mock.get(...)`.
    Registered but unused responses are allowed.
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture(autouse=True)
def _httpx2_guard(httpx2_mock: HTTPXMock) -> None:
    """
    🛡️ Activate `httpx2_mock` for every test (httpx2, used by Massive).

    Requesting the plugin fixture patches httpx2's transports. An HTTP call with
    no registered reply raises httpx2.TimeoutException instead of reaching the
    network. Register replies with `httpx2_mock.add_response(url=..., ...)`.
    """


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
    httpx2_mock: HTTPXMock, override_settings: Callable[..., Settings]
) -> Callable[..., None]:
    """
    🏢 Factory: `massive("AAPL", "Apple Inc.", "CS")` fakes the Massive overview call.

    Sets a Massive API key (without one, lookups are skipped), then registers the
    ticker endpoint on `httpx2_mock`. Pass name=None to fake a 404 (unknown ticker).
    """
    override_settings(massive_api_key="test-key")

    def _register(ticker: str, name: str | None, type_: str | None = None) -> None:
        url = MASSIVE_TICKER_URL.format(ticker=ticker.upper())
        if name is None:
            httpx2_mock.add_response(
                url=url, status_code=404, json={"status": "NOT_FOUND"}
            )
            return
        results = {"name": name, **({"type": type_} if type_ else {})}
        httpx2_mock.add_response(url=url, json={"results": results})

    return _register


class FetchCall(NamedTuple):
    """📝 One `fetch` call as the code made it: criteria as text, plus mark_seen."""

    criteria: str
    mark_seen: bool


class FakeIdle:
    """💤 Stand-in for `MailBox.idle`: a context manager whose `poll` follows a script."""

    def __init__(self, polls: Sequence[list[bytes]]) -> None:
        """Store the scripted poll results, one per `poll` call, in order."""
        self._polls = list(polls)
        self.timeouts: list[float | None] = []  # 🕒 The timeout of every poll, in order

    def __enter__(self) -> Self:
        """Return self, as the real idle object does."""
        return self

    def __exit__(self, *_exc_info: object) -> None:
        """Return None so exceptions, including ScriptExhausted, still propagate."""

    def poll(self, timeout: float | None) -> list[bytes]:
        """
        Record the timeout and return the next scripted result.

        An empty result means the IDLE wait timed out with no new mail. Raises
        ScriptExhausted when the script has no more polls.
        """
        self.timeouts.append(timeout)
        if not self._polls:
            raise ScriptExhausted("no poll scripted")
        return self._polls.pop(0)


class FakeMailBox:
    """
    📭 Stand-in for imap_tools MailBox, scripted one call at a time.

    Models the calls production makes: `MailBox(host).login(...)` used as a
    context manager, `mailbox.idle` used as a context manager with `poll`, and
    `mailbox.fetch(criteria, mark_seen=...)`. Each `fetch` consumes one list of
    messages from `fetches`. Each `poll` consumes one result from `polls`. Both
    raise ScriptExhausted when their script is empty.
    """

    def __init__(
        self,
        fetches: Sequence[Sequence[MailMessage]] = (),
        polls: Sequence[list[bytes]] = (),
    ) -> None:
        """Store the scripts. `host` is filled in when the code calls MailBox(host)."""
        self.host: str | None = None
        self.login_args: tuple[str, str, str] | None = None
        self.fetch_calls: list[FetchCall] = []
        self.logged_out = False
        self.idle = FakeIdle(polls)
        self._fetches = [list(batch) for batch in fetches]

    def login(self, user: str, password: str, folder: str) -> FakeMailBox:
        """🔑 Record the login arguments and return self, as MailBox.login does."""
        self.login_args = (user, password, folder)
        return self

    def __enter__(self) -> Self:
        """Return self, as MailBox does inside `with`."""
        return self

    def __exit__(self, *_exc_info: object) -> None:
        """🚪 Mark the session closed. Returns None so exceptions still propagate."""
        self.logged_out = True

    def fetch(
        self, criteria: object, *, mark_seen: bool = True
    ) -> Iterator[MailMessage]:
        """
        Record the call and return the next scripted batch of messages.

        Raises ScriptExhausted when no batch is left.
        """
        self.fetch_calls.append(FetchCall(str(criteria), mark_seen))
        if not self._fetches:
            raise ScriptExhausted("no fetch scripted")
        return iter(self._fetches.pop(0))


@pytest.fixture
def fake_mailbox(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeMailBox]:
    """
    📭 Factory: `fake_mailbox(fetches=[[...]], polls=[[...]])` replaces MailBox.

    Returns the FakeMailBox so tests can read what the code did to it. Each
    `MailBox(host)` call in hvcwatch.email_monitor returns that same fake and
    records the host. Undone automatically at the end of the test.
    """

    def _make(
        fetches: Sequence[Sequence[MailMessage]] = (),
        polls: Sequence[list[bytes]] = (),
    ) -> FakeMailBox:
        mailbox = FakeMailBox(fetches, polls)

        def _connect(host: str) -> FakeMailBox:
            mailbox.host = host  # 🏷️ Record the server the code asked for
            return mailbox

        monkeypatch.setattr("hvcwatch.email_monitor.MailBox", _connect)
        return mailbox

    return _make


@pytest.fixture
def hvcwatch_logger() -> Iterator[Logger]:
    """
    📜 Give the test a clean hvcwatch logger and restore it afterwards.

    Handlers the test adds are closed at teardown. The level and the handlers
    that were there before the test come back.
    """
    logger = getLogger(LOGGER_NAME)
    saved_level = logger.level
    saved_handlers = logger.handlers[:]
    for handler in saved_handlers:
        logger.removeHandler(handler)
    yield logger
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    for handler in saved_handlers:
        logger.addHandler(handler)
    logger.setLevel(saved_level)
