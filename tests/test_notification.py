"""Tests for the notification module.

Only HTTP is faked. Discord uses `responses` (the shared `http_mock` fixture), and
Massive uses `httpx2_mock`. The real DiscordNotifier, DiscordWebhook,
DiscordEmbed, and get_company_name run, so the tests assert the payload a Discord
user would see.
"""

import logging
from datetime import timedelta

import httpx2
import pytest
import requests

from hvcwatch.config import Settings
from hvcwatch.notification import (
    DiscordDeliveryError,
    DiscordNotifier,
    format_dollar_volume,
    format_price,
    format_volume,
    notify_all_platforms,
)
from tests.helpers import SECOND_URL, WEBHOOK_URL, daily_bar, only_embed, posts_to


class TestDiscordNotifierSend:
    """DiscordNotifier.send: the embed Discord receives."""

    @pytest.mark.parametrize(
        ("ticker", "timeframe", "overview", "title", "description", "color"),
        [
            pytest.param(
                "AAPL",
                "daily",
                ("Apple Inc.", "CS"),
                "Apple Inc.",
                "**AAPL** · CS · Daily",
                0x03B2F8,  # 🔵 discord_webhook converts "03b2f8" to an int
                id="daily-with-name-and-type",
            ),
            pytest.param(
                "TSLA",
                "weekly",
                ("Tesla, Inc.", "CS"),
                "Tesla, Inc.",
                "**TSLA** · CS · Weekly",
                0x9B59B6,  # 🟣
                id="weekly",
            ),
            pytest.param(
                "NVDA",
                "monthly",
                ("NVIDIA CORP", "CS"),
                "NVIDIA CORP",
                "**NVDA** · CS · Monthly 🔥",
                0xF39C12,  # 🟠
                id="monthly-has-fire-emoji",
            ),
            pytest.param(
                "SPY",
                "daily",
                ("SPDR S&P 500 ETF Trust", None),
                "SPDR S&P 500 ETF Trust",
                "**SPY** · Daily",
                0x03B2F8,
                id="type-missing-drops-type-part",
            ),
            pytest.param(
                "ZZZZ",
                "daily",
                (None, None),
                "ZZZZ",  # 🏷️ No name, so the title falls back to the ticker
                "Daily",  # 🧹 No bold ticker either, the title already shows it
                0x03B2F8,
                id="no-name-title-is-ticker",
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
        title,
        description,
        color,
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
            "image": embed["image"]["url"],
            "thumbnail": embed["thumbnail"]["url"],
        } == {
            "title": title,
            "description": description,
            "color": color,
            "image": settings.transparent_png,
            "thumbnail": f"https://static.stocktitan.net/company-logo/{ticker.lower()}.webp",
        }
        # 🧹 No footer row. Discord shows the send time, so no timestamp either.
        # The library stores an unset footer as None and drops an unset timestamp key.
        assert embed.get("footer") is None
        assert embed.get("timestamp") is None

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
        ("timeframe", "expected_description"),
        [
            ("daily", "**AAPL** · CS · Daily"),
            ("weekly", "**AAPL** · CS · Weekly"),
            ("monthly", "**AAPL** · CS · Monthly 🔥"),
            (None, "**AAPL** · CS · Daily"),  # 🗓️ No argument means daily
        ],
        ids=["daily", "weekly", "monthly", "default-is-daily"],
    )
    def test_posts_once_with_timeframe(
        self, http_mock, fake_discord, massive, timeframe, expected_description
    ):
        """✅ One POST to the configured URL, titled with the company name."""
        # Arrange
        fake_discord()
        massive("AAPL", "Apple Inc.", "CS")
        args = () if timeframe is None else (timeframe,)

        # Act
        notify_all_platforms("AAPL", *args)

        # Assert
        (payload,) = posts_to(http_mock, WEBHOOK_URL)
        embed = only_embed(payload)
        assert embed["title"] == "Apple Inc."
        assert embed["description"] == expected_description

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
        assert only_embed(first[0])["description"] == "Weekly"  # 📭 No name lookup here
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


class TestMarketStatsFields:
    """DiscordNotifier.send: market stats as inline embed fields, when known."""

    def test_stats_add_three_inline_fields_in_order(
        self, http_mock, fake_discord, massive, massive_bars, frozen_today
    ):
        """📊 Price, Vol 20MA, and $Vol 20MA are added as inline fields, in that order."""
        # Arrange: price 48.12 today, and 20 prior days at 48.00 on 1.2M shares
        fake_discord()
        massive("AAPL", "Apple Inc.", "CS")
        today_bar = daily_bar(frozen_today, close=48.12, volume=500)
        prior = [
            daily_bar(frozen_today - timedelta(days=k), close=48.00, volume=1_200_000)
            for k in range(1, 21)
        ]
        massive_bars([today_bar, *prior])

        # Act
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        (payload,) = posts_to(http_mock, WEBHOOK_URL)
        assert only_embed(payload)["fields"] == [
            {"name": "Price", "value": "$48.12", "inline": True},
            {"name": "Vol 20MA", "value": "1.2M", "inline": True},
            {"name": "$Vol 20MA", "value": "$57.6M", "inline": True},
        ]

    def test_price_only_adds_only_the_price_field(
        self, http_mock, fake_discord, massive, massive_bars, frozen_today
    ):
        """📊 With a price but fewer than 20 prior bars, the embed gets the Price field only."""
        # Arrange
        fake_discord()
        massive("AAPL", "Apple Inc.", "CS")
        massive_bars([daily_bar(frozen_today, close=48.12, volume=500)])

        # Act
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        (payload,) = posts_to(http_mock, WEBHOOK_URL)
        assert only_embed(payload)["fields"] == [
            {"name": "Price", "value": "$48.12", "inline": True},
        ]

    @pytest.mark.parametrize(
        "reply",
        [
            pytest.param(
                {"error": httpx2.TimeoutException("timed out")}, id="lookup-failed"
            ),
            pytest.param({"body": b'{"status":"OK","results":[]}'}, id="no-bars"),
        ],
    )
    def test_missing_stats_add_no_fields_and_still_send(
        self, http_mock, fake_discord, massive, massive_bars, reply
    ):
        """🛟 A failed or empty stats lookup adds no fields, and the alert still goes out."""
        # Arrange
        fake_discord()
        massive("AAPL", "Apple Inc.", "CS")
        massive_bars(**reply)

        # Act
        DiscordNotifier(webhook_url=WEBHOOK_URL).send("AAPL", "daily")

        # Assert
        (payload,) = posts_to(http_mock, WEBHOOK_URL)
        assert not only_embed(payload).get("fields")


@pytest.mark.parametrize(
    ("price", "text"),
    [
        (1234.56, "$1,234.56"),
        (48.12, "$48.12"),
        (1.0, "$1.00"),
        (0.5, "$0.5000"),
        (0.1234, "$0.1234"),
    ],
)
def test_format_price_uses_two_decimals_at_one_dollar_and_up(price, text):
    """💲 Prices of $1 and up get 2 decimals and thousands separators. Under $1 gets 4."""
    assert format_price(price) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1_300_000_000, "1.3B"),
        (1_200_000, "1.2M"),
        (850_300, "850.3K"),
        (1_000, "1.0K"),
        (999, "999"),
        (42, "42"),
    ],
)
def test_format_volume_is_compact(value, text):
    """🔢 Volume uses K, M, or B with one decimal. Below 1,000 it is a whole number."""
    assert format_volume(value) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (57_600_000, "$57.6M"),
        (2_500_000_000, "$2.5B"),
        (42, "$42"),
    ],
)
def test_format_dollar_volume_adds_dollar_sign_to_compact_form(value, text):
    """💵 Dollar volume is the compact volume form with a $ prefix."""
    assert format_dollar_volume(value) == text
