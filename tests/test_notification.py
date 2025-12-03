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


# Mock get_company_name to return known values for test tickers
@pytest.fixture(autouse=True)
def mock_company_names():
    company_names = {
        "AAPL": "Apple Inc.",
        "TSLA": "Tesla, Inc.",
        "NVDA": "NVIDIA CORP",
        "MSFT": "MICROSOFT CORP",
        "GOOGL": "Alphabet Inc.",
        "AMZN": "AMAZON COM INC",
    }
    with patch(
        "hvcwatch.notification.get_company_name",
        side_effect=lambda t: company_names.get(t.upper()),
    ):
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

    def test_send_daily_alert(
        self,
        mock_settings,
        mock_discord_webhook,
    ):
        """Test sending a daily alert."""
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

        # Verify embed creation - title is ticker, description includes company name
        mock_embed_class.assert_called_once_with(
            title="AAPL",
            description="**Apple Inc.**\n**Timeframe:** Daily",
            color="03b2f8",
        )

        # Verify embed methods were called
        mock_embed.set_footer.assert_called_once_with(text="HVC Watch · Major's Bots")
        mock_embed.set_image.assert_called_once_with(url=mock_settings.transparent_png)
        mock_embed.set_timestamp.assert_called_once()

        # Verify webhook operations
        mock_webhook.add_embed.assert_called_once_with(mock_embed)
        mock_webhook.execute.assert_called_once()

    def test_send_weekly_alert(
        self,
        mock_settings,
        mock_discord_webhook,
    ):
        """Test sending a weekly alert."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notifier.send("TSLA", "weekly")

        # Verify embed has weekly timeframe with company name (no emoji)
        mock_embed_class.assert_called_once_with(
            title="TSLA",
            description="**Tesla, Inc.**\n**Timeframe:** Weekly",
            color="03b2f8",
        )

    def test_send_monthly_alert_with_fire_emoji(
        self,
        mock_settings,
        mock_discord_webhook,
    ):
        """Test sending a monthly alert with fire emoji."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notifier.send("NVDA", "monthly")

        # Verify embed has monthly timeframe with company name and fire emoji
        mock_embed_class.assert_called_once_with(
            title="NVDA",
            description="**NVIDIA CORP**\n**Timeframe:** Monthly 🔥",
            color="03b2f8",
        )

    @pytest.mark.parametrize("status_code", [200, 201, 204, 400, 500])
    def test_send_various_response_codes(self, mock_settings, status_code):
        """Test Discord notification with various HTTP response codes."""
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

            # Just verify execution completes without error
            mock_webhook.execute.assert_called_once()

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
        self, mock_settings, mock_discord_webhook, ticker, timeframe
    ):
        """Test Discord notification with various tickers and timeframes."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
        notifier.send(ticker, timeframe)

        # Verify webhook was executed
        mock_webhook.execute.assert_called_once()


class TestNotifyAllPlatforms:
    """Test notify_all_platforms orchestrator function."""

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_success(self, mock_notifier_class, mock_settings):
        """Test successful notification to all platforms."""
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

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_with_timeframe(
        self, mock_notifier_class, mock_settings
    ):
        """Test notification with different timeframes."""
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("TSLA", "weekly")

        mock_notifier.send.assert_called_once_with("TSLA", "weekly")

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_monthly_with_fire(
        self, mock_notifier_class, mock_settings
    ):
        """Test monthly notification passes correct timeframe."""
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("NVDA", "monthly")

        mock_notifier.send.assert_called_once_with("NVDA", "monthly")

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_default_timeframe(
        self, mock_notifier_class, mock_settings
    ):
        """Test that default timeframe is 'daily'."""
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        # Call without timeframe argument
        notify_all_platforms("AAPL")

        mock_notifier.send.assert_called_once_with("AAPL", "daily")

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_send_error(self, mock_notifier_class, mock_settings):
        """Test error handling when sending notification fails."""
        # Mock settings to return a single webhook URL
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier.send.side_effect = Exception("Webhook error")
        mock_notifier_class.return_value = mock_notifier

        # Should not raise - error is caught and logged
        notify_all_platforms("AAPL", "daily")

        # Verify the send was attempted
        mock_notifier.send.assert_called_once_with("AAPL", "daily")

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.DiscordNotifier")
    @pytest.mark.parametrize("ticker", ["TSLA", "MSFT", "GOOGL", "AMZN"])
    def test_notify_all_platforms_various_tickers(
        self, mock_notifier_class, mock_settings, ticker
    ):
        """Test notify_all_platforms with various ticker symbols."""
        # Mock settings to return a single webhook URL
        mock_settings.get_discord_webhook_urls.return_value = [
            "https://discord.com/api/webhooks/test"
        ]

        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms(ticker, "daily")

        # Verify notification was sent with correct ticker
        mock_notifier.send.assert_called_once_with(ticker, "daily")

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_no_discord_config(
        self, mock_notifier_class, mock_settings
    ):
        """Test graceful handling when Discord is not configured."""
        mock_settings.get_discord_webhook_urls.return_value = []  # No Discord configured

        notify_all_platforms("AAPL", "daily")

        # Verify Discord notifier was NOT created
        mock_notifier_class.assert_not_called()

    @patch("hvcwatch.notification.settings")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_multiple_webhooks(
        self, mock_notifier_class, mock_settings
    ):
        """Test sending to multiple webhook URLs."""
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
