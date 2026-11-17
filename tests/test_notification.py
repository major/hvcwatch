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

import pytest
import requests
import responses

from hvcwatch.config import Settings
from hvcwatch.notification import DiscordNotifier, notify_all_platforms
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

    Replies 200 with a JSON body, because DiscordWebhook.execute always runs
    json.loads on the body (an empty body raises JSONDecodeError). Never 429,
    since the library would then call a real sleep.
    """

    def _register(url: str = WEBHOOK_URL, status: int = 200, **reply: Any) -> None:
        assert status != 429, "a 429 reply makes discord_webhook sleep for real"
        if "body" not in reply:  # 🧩 responses rejects json and body together
            reply.setdefault("json", {"id": "1"})
        http_mock.post(url, status=status, **reply)

    return _register


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

    @pytest.mark.parametrize("status", [400, 500])
    def test_send_non_2xx_with_json_body_does_not_raise(
        self, http_mock, fake_discord, status
    ):
        """
        📌 Pins today's behavior for a non-2xx reply, nothing more.

        TODO(#117): the failure policy is undecided. Today send() returns
        normally, so the caller counts the alert as sent. When #117 is decided,
        replace this test with one that asserts the chosen policy.
        """
        # Arrange
        fake_discord(status=status, json={"message": "nope"})

        # Act (no exception is the observable behavior)
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 1

    def test_send_connection_error_propagates(self, http_mock, fake_discord):
        """🔌 A network failure reaches the caller (notify_all_platforms handles it)."""
        # Arrange
        fake_discord(body=requests.ConnectionError("boom"))

        # Act / Assert
        with pytest.raises(requests.ConnectionError):
            DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")


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

    def test_empty_json_body_is_logged_as_failure(self, fake_discord, caplog):
        """
        🕳️ An empty 200 body makes execute raise JSONDecodeError, which is logged.

        Guards the fake itself: a 200 with no JSON body would look like success
        in a "one POST" check while the real send had failed.
        """
        # Arrange
        fake_discord(body="")

        # Act
        with caplog.at_level(logging.ERROR, logger="hvcwatch.notification"):
            notify_all_platforms("AAPL", "daily")

        # Assert
        assert "Failed to send notification" in caplog.text

    def test_no_urls_makes_no_http_calls_and_warns(
        self, http_mock, monkeypatch, caplog
    ):
        """
        📭 With no webhook URLs, nothing is sent and a warning says so.

        Settings validation rejects a config with no URL, so the empty list is
        injected directly instead of building a Settings that has none.
        """
        # Arrange
        monkeypatch.setattr(Settings, "get_discord_webhook_urls", lambda self: [])

        # Act
        with caplog.at_level(logging.WARNING, logger="hvcwatch.notification"):
            notify_all_platforms("AAPL", "daily")

        # Assert
        assert len(http_mock.calls) == 0
        assert "No notifications sent" in caplog.text
