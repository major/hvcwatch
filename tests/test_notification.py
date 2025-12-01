"""Tests for notification module."""

import pytest
from unittest.mock import Mock, patch

from hvcwatch.notification import (
    DiscordNotifier,
    notify_all_platforms,
)


# Mock sentry_sdk for all tests in this module
@pytest.fixture(autouse=True)
def mock_sentry():
    with patch("hvcwatch.notification.sentry_sdk"):
        yield


@pytest.fixture
def mock_settings():
    """Mock settings with Discord webhook URL and transparent PNG."""
    with patch("hvcwatch.notification.settings") as mock_settings:
        mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/test"
        mock_settings.transparent_png = "https://example.com/transparent.png"
        yield mock_settings


@pytest.fixture
def mock_discord_webhook():
    """Mock DiscordWebhook and DiscordEmbed."""
    with (
        patch("hvcwatch.notification.DiscordWebhook") as mock_webhook_class,
        patch("hvcwatch.notification.DiscordEmbed") as mock_embed_class,
    ):
        mock_webhook = Mock()
        mock_embed = Mock()
        mock_webhook_class.return_value = mock_webhook
        mock_embed_class.return_value = mock_embed

        # Mock the webhook response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_webhook.execute.return_value = mock_response

        yield mock_webhook_class, mock_embed_class, mock_webhook, mock_embed


class TestDiscordNotifierSend:
    """Test DiscordNotifier send method."""

    @patch("hvcwatch.notification.logger")
    def test_send_daily_alert(
        self,
        mock_logger,
        mock_settings,
        mock_discord_webhook,
    ):
        """✅ Test sending a daily alert."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        webhook_url = "https://discord.com/api/webhooks/test"
        notifier = DiscordNotifier(webhook_url=webhook_url)
        notifier.send("AAPL", "daily")

        # Verify webhook creation
        mock_webhook_class.assert_called_once_with(
            url=webhook_url, rate_limit_retry=True
        )

        # Verify embed creation - title is just the ticker
        mock_embed_class.assert_called_once_with(
            title="AAPL",
            description="**Timeframe:** Daily",
            color="03b2f8",
        )

        # Verify embed methods were called
        mock_embed.set_footer.assert_called_once_with(text="HVC Watch · Major's Bots")
        mock_embed.set_image.assert_called_once_with(url=mock_settings.transparent_png)
        mock_embed.set_timestamp.assert_called_once()

        # Verify webhook operations
        mock_webhook.add_embed.assert_called_once_with(mock_embed)
        mock_webhook.execute.assert_called_once()

        # Verify logging
        mock_logger.info.assert_any_call(
            "Sending to Discord", ticker="AAPL", timeframe="daily"
        )
        mock_logger.info.assert_any_call("Discord response", status_code=200)

    @patch("hvcwatch.notification.logger")
    def test_send_weekly_alert(
        self,
        mock_logger,
        mock_settings,
        mock_discord_webhook,
    ):
        """✅ Test sending a weekly alert."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notifier.send("TSLA", "weekly")

        # Verify embed has weekly timeframe (no emoji)
        mock_embed_class.assert_called_once_with(
            title="TSLA",
            description="**Timeframe:** Weekly",
            color="03b2f8",
        )

    @patch("hvcwatch.notification.logger")
    def test_send_monthly_alert_with_fire_emoji(
        self,
        mock_logger,
        mock_settings,
        mock_discord_webhook,
    ):
        """✅ Test sending a monthly alert with 🔥 emoji."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notifier.send("NVDA", "monthly")

        # Verify embed has monthly timeframe WITH fire emoji
        mock_embed_class.assert_called_once_with(
            title="NVDA",
            description="**Timeframe:** Monthly 🔥",
            color="03b2f8",
        )

    @patch("hvcwatch.notification.logger")
    @pytest.mark.parametrize("status_code", [200, 201, 204, 400, 500])
    def test_send_various_response_codes(self, mock_logger, mock_settings, status_code):
        """✅ Test Discord notification with various HTTP response codes."""
        with (
            patch("hvcwatch.notification.DiscordWebhook") as mock_webhook_class,
            patch("hvcwatch.notification.DiscordEmbed"),
        ):
            mock_webhook = Mock()
            mock_webhook_class.return_value = mock_webhook

            # Mock response with different status codes
            mock_response = Mock()
            mock_response.status_code = status_code
            mock_webhook.execute.return_value = mock_response

            notifier = DiscordNotifier(
                webhook_url="https://discord.com/api/webhooks/test"
            )
            notifier.send("AAPL", "daily")

            mock_logger.info.assert_any_call(
                "Discord response", status_code=status_code
            )

    @patch("hvcwatch.notification.logger")
    @pytest.mark.parametrize(
        "ticker,timeframe",
        [
            ("AAPL", "daily"),
            ("TSLA", "weekly"),
            ("NVDA", "monthly"),
            ("MSFT", "daily"),
            ("GOOGL", "weekly"),
        ],
    )
    def test_send_various_tickers_and_timeframes(
        self, mock_logger, mock_settings, mock_discord_webhook, ticker, timeframe
    ):
        """✅ Test Discord notification with various tickers and timeframes."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notifier.send(ticker, timeframe)

        # Verify logging mentions correct ticker and timeframe
        mock_logger.info.assert_any_call(
            "Sending to Discord", ticker=ticker, timeframe=timeframe
        )


class TestNotifyAllPlatforms:
    """Test notify_all_platforms orchestrator function."""

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_success(
        self, mock_notifier_class, mock_logger, mock_settings
    ):
        """✅ Test successful notification to all platforms."""
        # Mock settings to return a single webhook URL
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("AAPL", "daily")

        # Verify Discord notifier was created and called
        mock_notifier_class.assert_called_once_with(
            webhook_url="https://discord.com/api/webhooks/test"
        )
        mock_notifier.send.assert_called_once_with("AAPL", "daily")

        # Verify logging
        mock_logger.info.assert_any_call(
            "Sending notifications", ticker="AAPL", timeframe="daily"
        )

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_with_timeframe(
        self, mock_notifier_class, mock_logger, mock_settings
    ):
        """✅ Test notification with different timeframes."""
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("TSLA", "weekly")

        mock_notifier.send.assert_called_once_with("TSLA", "weekly")

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_monthly_with_fire(
        self, mock_notifier_class, mock_logger, mock_settings
    ):
        """✅ Test monthly notification passes correct timeframe."""
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("NVDA", "monthly")

        mock_notifier.send.assert_called_once_with("NVDA", "monthly")

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_default_timeframe(
        self, mock_notifier_class, mock_logger, mock_settings
    ):
        """✅ Test that default timeframe is 'daily'."""
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        # Call without timeframe argument
        notify_all_platforms("AAPL")

        mock_notifier.send.assert_called_once_with("AAPL", "daily")

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_send_error(
        self, mock_notifier_class, mock_logger, mock_settings
    ):
        """❌ Test error handling when sending notification fails."""
        # Mock settings to return a single webhook URL
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier.send.side_effect = Exception("Webhook error")
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("AAPL", "daily")

        # Verify error was logged
        error_calls = [call for call in mock_logger.error.call_args_list]
        assert len(error_calls) == 1
        error_call = error_calls[0]
        assert error_call[1]["ticker"] == "AAPL"
        assert error_call[1]["platform"] == "Discord"
        assert "Webhook error" in error_call[1]["error"]

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    @pytest.mark.parametrize("ticker", ["TSLA", "MSFT", "GOOGL", "AMZN"])
    def test_notify_all_platforms_various_tickers(
        self, mock_notifier_class, mock_logger, mock_settings, ticker
    ):
        """✅ Test notify_all_platforms with various ticker symbols."""
        # Mock settings to return a single webhook URL
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms(ticker, "daily")

        # Verify notification was sent with correct ticker
        mock_notifier.send.assert_called_once_with(ticker, "daily")

        # Verify logging mentions correct ticker
        mock_logger.info.assert_any_call(
            "Sending notifications", ticker=ticker, timeframe="daily"
        )

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_no_discord_config(
        self, mock_notifier_class, mock_logger, mock_settings
    ):
        """⚠️ Test graceful handling when Discord is not configured."""
        mock_settings.get_discord_webhook_urls.return_value = []  # No Discord configured

        notify_all_platforms("AAPL", "daily")

        # Verify Discord notifier was NOT created
        mock_notifier_class.assert_not_called()

        # Verify debug log for skipping Discord
        mock_logger.debug.assert_any_call(
            "Discord webhook not configured, skipping", ticker="AAPL"
        )

        # Verify warning about no webhooks configured
        mock_logger.warning.assert_called_once_with(
            "No notifications sent - no Discord webhooks configured",
            ticker="AAPL",
        )

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_multiple_webhooks(
        self, mock_notifier_class, mock_logger, mock_settings
    ):
        """✅ Test sending to multiple webhook URLs."""
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test1",
            "https://discord.com/api/webhooks/test2",
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("AAPL", "weekly")

        # Verify notifier was created twice (once per webhook)
        assert mock_notifier_class.call_count == 2
        assert mock_notifier.send.call_count == 2

        # Both calls should have same ticker and timeframe
        for call in mock_notifier.send.call_args_list:
            assert call[0] == ("AAPL", "weekly")
