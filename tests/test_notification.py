"""Tests for the notification module.

Only HTTP is faked (`responses`, via the shared `http_mock` fixture). The real
DiscordNotifier, DiscordWebhook, DiscordEmbed, and get_company_name run, so the
tests assert the payload a Discord user would see.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
import responses

from hvcwatch.config import Settings
from hvcwatch.notification import (
    DiscordDeliveryError,
    DiscordNotifier,
    notify_all_platforms,
)
from hvcwatch.utils import MASSIVE_TICKER_URL

WEBHOOK_URL = (
    "https://discord.com/api/webhooks/test"  # 🔗 Matches the shared `settings`
)
SECOND_URL = "https://discord.com/api/webhooks/second"
EMBED_COLOR = 0x03B2F8  # discord_webhook converts the "03b2f8" hex string to an int
FOOTER = "HVC Watch · Major's Bots"


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


def posts_to(http_mock: responses.RequestsMock, url: str) -> list[dict[str, Any]]:
    """📬 JSON bodies of every POST sent to `url`, in order."""
    bodies: list[dict[str, Any]] = []
    for call in http_mock.calls:
        request = call.request
        if request.method != "POST" or (request.url or "").split("?")[0] != url:
            continue
        assert isinstance(request.body, bytes)  # 📦 requests encodes json= as bytes
        bodies.append(json.loads(request.body))
    return bodies


def only_embed(payload: dict[str, Any]) -> dict[str, Any]:
    """🪟 The single embed in a webhook payload."""
    assert len(payload["embeds"]) == 1
    return payload["embeds"][0]


class TestDiscordNotifierSend:
    """DiscordNotifier.send: the embed Discord receives."""

    @pytest.mark.parametrize(
        ("ticker", "timeframe", "overview", "description"),
        [
            pytest.param(
                "AAPL",
                "daily",
                ("Apple Inc.", "CS"),
                "**Apple Inc.**\n**Type:** CS\n**Timeframe:** Daily",
                id="daily-with-name-and-type",
            ),
            pytest.param(
                "TSLA",
                "weekly",
                ("Tesla, Inc.", "CS"),
                "**Tesla, Inc.**\n**Type:** CS\n**Timeframe:** Weekly",
                id="weekly",
            ),
            pytest.param(
                "NVDA",
                "monthly",
                ("NVIDIA CORP", "CS"),
                "**NVIDIA CORP**\n**Type:** CS\n**Timeframe:** Monthly 🔥",
                id="monthly-has-fire-emoji",
            ),
            pytest.param(
                "SPY",
                "daily",
                ("SPDR S&P 500 ETF Trust", None),
                "**SPDR S&P 500 ETF Trust**\n**Timeframe:** Daily",
                id="type-missing-drops-type-line",
            ),
            pytest.param(
                "ZZZZ",
                "daily",
                (None, None),
                "**Timeframe:** Daily",
                id="company-name-none-drops-name-line",
            ),
        ],
    )
    def test_send_posts_expected_embed(
        self,
        http_mock,
        fake_discord,
        massive,
        settings,
        ticker,
        timeframe,
        overview,
        description,
    ):
        """✅ One POST whose embed carries every field a user sees."""
        # Arrange
        fake_discord()
        massive(ticker, *overview)

        # Act
        DiscordNotifier(webhook_url=WEBHOOK_URL).send(ticker, timeframe)

        # Assert
        (payload,) = posts_to(http_mock, WEBHOOK_URL)
        embed = only_embed(payload)
        # 🔎 The library adds null keys (proxy_url, height, ...), so compare what users see
        assert {
            "title": embed["title"],
            "description": embed["description"],
            "color": embed["color"],
            "footer": embed["footer"]["text"],
            "image": embed["image"]["url"],
            "thumbnail": embed["thumbnail"]["url"],
        } == {
            "title": ticker,
            "description": description,
            "color": EMBED_COLOR,
            "footer": FOOTER,
            "image": settings.transparent_png,
            "thumbnail": f"https://static.stocktitan.net/company-logo/{ticker.lower()}.webp",
        }
        assert datetime.fromisoformat(embed["timestamp"])

    def test_send_uses_custom_transparent_png(
        self, http_mock, fake_discord, override_settings
    ):
        """🖼️ The embed image comes from settings, not a hardcoded URL."""
        # Arrange
        fake_discord()
        override_settings(transparent_png="https://example.com/clear.png")

        # Act
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        (payload,) = posts_to(http_mock, WEBHOOK_URL)
        assert only_embed(payload)["image"]["url"] == "https://example.com/clear.png"

    def test_204_empty_body_is_success(self, http_mock, fake_discord):
        """✅ Discord's 204 (no body) is a successful delivery, not an error."""
        # Arrange
        fake_discord(status=204, body="")

        # Act (no exception is the observable behavior)
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 1


class TestDiscordDeliveryRetries:
    """DiscordNotifier.send: retries transient failures, raises when Discord rejects."""

    def test_server_error_then_success_posts_twice(
        self, http_mock, fake_discord, sleeps
    ):
        """🔁 A 500 is retried, and the second attempt succeeds."""
        # Arrange
        fake_discord(status=500, json={"message": "oops"})
        fake_discord()

        # Act
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 2
        sleeps.assert_called_once_with(1)

    @pytest.mark.parametrize(
        "rate_limit_reply",
        [
            pytest.param({"json": {"retry_after": 7}}, id="retry-after-in-body"),
            pytest.param(
                {"json": {}, "headers": {"Retry-After": "7"}},
                id="retry-after-header",
            ),
        ],
    )
    def test_429_waits_retry_after_when_larger_than_backoff(
        self, http_mock, fake_discord, sleeps, rate_limit_reply
    ):
        """⏳ A 429 waits the Discord-requested 7 seconds (more than the 1s backoff)."""
        # Arrange
        fake_discord(status=429, **rate_limit_reply)
        fake_discord()

        # Act
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 2
        sleeps.assert_called_once_with(7)

    def test_client_error_fails_without_retry(self, http_mock, fake_discord, sleeps):
        """🚫 A 400 is a bad request: one POST, no wait, and send raises."""
        # Arrange
        fake_discord(status=400, json={"message": "bad"})

        # Act / Assert
        with pytest.raises(DiscordDeliveryError):
            DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 1
        sleeps.assert_not_called()

    def test_gives_up_after_four_attempts(self, http_mock, fake_discord):
        """🛑 Four failed attempts in a row make send raise DiscordDeliveryError."""
        # Arrange
        fake_discord(status=503, json={"message": "down"})

        # Act / Assert
        with pytest.raises(DiscordDeliveryError):
            DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 4

    def test_backoff_waits_one_two_four_seconds(self, http_mock, fake_discord, sleeps):
        """📈 Exponential backoff: 3 waits of 1, 2, and 4 seconds across 4 attempts."""
        # Arrange
        fake_discord(status=500, json={"message": "oops"})

        # Act
        with pytest.raises(DiscordDeliveryError):
            DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        assert [call.args[0] for call in sleeps.call_args_list] == [1, 2, 4]

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(requests.ConnectionError("boom"), id="connection-error"),
            pytest.param(requests.Timeout("slow"), id="timeout"),
        ],
    )
    def test_network_error_then_success_posts_twice(
        self, http_mock, fake_discord, error
    ):
        """🔌 A dropped connection or timeout is retried, and the next attempt succeeds."""
        # Arrange
        fake_discord(body=error)
        fake_discord()

        # Act
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 2


class TestNotifyAllPlatforms:
    """notify_all_platforms: the real notifier, one POST per configured URL."""

    @pytest.mark.parametrize(
        ("timeframe", "expected_line"),
        [
            ("daily", "**Timeframe:** Daily"),
            ("weekly", "**Timeframe:** Weekly"),
            ("monthly", "**Timeframe:** Monthly 🔥"),
            (None, "**Timeframe:** Daily"),  # 🗓️ No argument means daily
        ],
        ids=["daily", "weekly", "monthly", "default-is-daily"],
    )
    def test_posts_once_with_timeframe(
        self, http_mock, fake_discord, massive, timeframe, expected_line
    ):
        """✅ One POST to the configured URL, with the right timeframe and name."""
        # Arrange
        fake_discord()
        massive("AAPL", "Apple Inc.", "CS")
        args = () if timeframe is None else (timeframe,)

        # Act
        notify_all_platforms("AAPL", *args)

        # Assert
        (payload,) = posts_to(http_mock, WEBHOOK_URL)
        embed = only_embed(payload)
        assert embed["title"] == "AAPL"
        assert embed["description"] == f"**Apple Inc.**\n**Type:** CS\n{expected_line}"

    def test_posts_once_to_each_configured_url(
        self, http_mock, fake_discord, override_settings
    ):
        """📬 Every configured URL gets exactly one POST with the same embed."""
        # Arrange
        override_settings(discord_webhook_urls=f"{SECOND_URL}, {WEBHOOK_URL}")
        fake_discord(WEBHOOK_URL)
        fake_discord(SECOND_URL)

        # Act
        notify_all_platforms("AAPL", "weekly")

        # Assert
        first = posts_to(http_mock, WEBHOOK_URL)
        second = posts_to(http_mock, SECOND_URL)
        assert (
            len(first) == len(second) == 1
        )  # 🧹 The duplicate URL is not posted twice
        assert only_embed(first[0])["description"].endswith("**Timeframe:** Weekly")
        assert only_embed(first[0])["title"] == only_embed(second[0])["title"] == "AAPL"

    def test_connection_error_is_logged_and_next_url_still_posts(
        self, http_mock, fake_discord, override_settings, caplog
    ):
        """🛡️ One unreachable URL is logged at ERROR and does not stop the others."""
        # Arrange
        override_settings(discord_webhook_urls=SECOND_URL)
        fake_discord(WEBHOOK_URL, body=requests.ConnectionError("boom"))
        fake_discord(SECOND_URL)

        # Act
        with caplog.at_level(logging.ERROR, logger="hvcwatch.notification"):
            notify_all_platforms("AAPL", "daily")  # must not raise

        # Assert
        assert len(posts_to(http_mock, SECOND_URL)) == 1
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "Failed to send notification" in errors[0].getMessage()
        assert "boom" in errors[0].getMessage()

    @pytest.mark.parametrize(
        ("failing_urls", "expected_sent"),
        [
            pytest.param({WEBHOOK_URL}, 1, id="one-of-two-fails"),
            pytest.param({WEBHOOK_URL, SECOND_URL}, 0, id="all-fail"),
        ],
    )
    def test_returns_number_of_successful_sends(
        self, fake_discord, override_settings, caplog, failing_urls, expected_sent
    ):
        """🔢 The return value counts the URLs that accepted the alert, and warns if 0."""
        # Arrange
        override_settings(discord_webhook_urls=f"{SECOND_URL}, {WEBHOOK_URL}")
        for url in (WEBHOOK_URL, SECOND_URL):
            fake_discord(url, status=500 if url in failing_urls else 200)

        # Act
        with caplog.at_level(logging.WARNING, logger="hvcwatch.notification"):
            sent = notify_all_platforms("AAPL", "daily")

        # Assert
        assert sent == expected_sent
        assert ("No Discord notification delivered" in caplog.text) is (
            expected_sent == 0
        )

    def test_no_urls_makes_no_http_calls_warns_and_returns_zero(
        self, http_mock, monkeypatch, caplog
    ):
        """
        📭 With no webhook URLs, nothing is sent, a warning says so, and 0 returns.

        Settings validation rejects a config with no URL, so the empty list is
        injected directly instead of building a Settings that has none.
        """
        # Arrange
        monkeypatch.setattr(Settings, "get_discord_webhook_urls", lambda self: [])

        # Act
        with caplog.at_level(logging.WARNING, logger="hvcwatch.notification"):
            sent = notify_all_platforms("AAPL", "daily")

        # Assert
        assert sent == 0
        assert len(http_mock.calls) == 0
        assert "No Discord webhooks configured, nothing sent" in caplog.text
        assert "No Discord notification delivered" not in caplog.text
