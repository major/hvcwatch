"""Tests for notification module."""

import pytest
from unittest.mock import Mock, patch

from hvcwatch.models import TickerData
from hvcwatch.notification import DiscordNotifier, notify_all_platforms


@pytest.fixture
def sample_ticker_data() -> TickerData:
    """Create sample TickerData for testing."""
    return TickerData(
        ticker="AAPL",
        name="Apple Inc.",
        description="Technology company",
        type="CS",
        logo_url="https://static.stocktitan.net/company-logo/aapl.webp",
        close=150.25,
        volume=2_500_000,
        volume_sma=2_000_000.0,
        volume_ratio=1.25,
    )


@pytest.fixture
def sample_ticker_data_no_sma() -> TickerData:
    """Create sample TickerData with None volume_sma (insufficient data case)."""
    return TickerData(
        ticker="TSLA",
        name="Tesla Inc",
        description="Electric vehicle company",
        type="CS",
        logo_url="https://static.stocktitan.net/company-logo/tsla.webp",
        close=250.50,
        volume=500_000,
        volume_sma=None,
        volume_ratio=None,
    )


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


class TestDiscordNotifierBuildDescription:
    """Test DiscordNotifier build_description method."""

    @pytest.mark.parametrize(
        "ticker_data_kwargs,expected_parts",
        [
            (
                {
                    "ticker": "AAPL",
                    "name": "Apple Inc",
                    "description": "Tech",
                    "type": "CS",
                    "logo_url": "https://example.com/logo.png",
                    "close": 150.25,
                    "volume": 2_500_000,
                    "volume_sma": 2_000_000.0,
                    "volume_ratio": 1.25,
                },
                ["Current price: $150.25", "Volume vs avg: 2M / 2M **1.25x**"],
            ),
            (
                {
                    "ticker": "MSFT",
                    "name": "Microsoft",
                    "description": "Software",
                    "type": "CS",
                    "logo_url": "https://example.com/logo.png",
                    "close": 99.99,
                    "volume": 1_000_000,
                    "volume_sma": 800_000.0,
                    "volume_ratio": 1.25,
                },
                ["Current price: $99.99", "Volume vs avg: 1M / 800K **1.25x**"],
            ),
            (
                {
                    "ticker": "GOOGL",
                    "name": "Alphabet",
                    "description": "Search",
                    "type": "CS",
                    "logo_url": "https://example.com/logo.png",
                    "close": 1000.00,
                    "volume": 500_000,
                    "volume_sma": 1_000_000.0,
                    "volume_ratio": 0.50,
                },
                ["Current price: $1000.00", "Volume vs avg: 500K / 1M **0.50x**"],
            ),
        ],
    )
    def test_build_description_various_values(self, ticker_data_kwargs, expected_parts):
        """✅ Test build_description with various ticker data values."""
        ticker_data = TickerData(**ticker_data_kwargs)
        notifier = DiscordNotifier()

        result = notifier.build_description(ticker_data)

        # Check that both expected parts are in the result
        for part in expected_parts:
            assert part in result

        # Check that the result is properly formatted with newlines
        lines = result.split("\n")
        assert len(lines) == 2

    def test_build_description_insufficient_data(
        self, sample_ticker_data_no_sma: TickerData
    ):
        """✅ Test build_description when volume_sma is None (insufficient data)."""
        notifier = DiscordNotifier()

        result = notifier.build_description(sample_ticker_data_no_sma)

        assert "Current price: $250.50" in result
        assert "Volume: 500K (insufficient data for average)" in result
        assert "**" not in result  # No bold ratio when insufficient data


class TestDiscordNotifierSend:
    """Test DiscordNotifier send method."""

    @patch("hvcwatch.notification.logger")
    def test_send_success(
        self,
        mock_logger,
        sample_ticker_data: TickerData,
        mock_settings,
        mock_discord_webhook,
    ):
        """✅ Test successful Discord notification send."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        notifier = DiscordNotifier()
        notifier.send(sample_ticker_data)

        # Verify webhook creation
        mock_webhook_class.assert_called_once_with(
            url=mock_settings.discord_webhook_url, rate_limit_retry=True
        )

        # Verify embed creation and configuration
        mock_embed_class.assert_called_once_with(
            title="Apple Inc. (AAPL)",
            description=notifier.build_description(sample_ticker_data),
            color="03b2f8",
        )

        # Verify embed methods were called
        mock_embed.set_thumbnail.assert_called_once_with(
            url="https://static.stocktitan.net/company-logo/aapl.webp"
        )
        mock_embed.set_footer.assert_called_once_with(text="HVC Watch · Major's Bots")
        mock_embed.set_image.assert_called_once_with(url=mock_settings.transparent_png)
        mock_embed.set_timestamp.assert_called_once()

        # Verify webhook operations
        mock_webhook.add_embed.assert_called_once_with(mock_embed)
        mock_webhook.execute.assert_called_once()

        # Verify logging
        mock_logger.info.assert_any_call("Sending to Discord", ticker="AAPL")
        mock_logger.info.assert_any_call("Discord response", status_code=200)

    @patch("hvcwatch.notification.logger")
    @pytest.mark.parametrize("status_code", [200, 201, 204, 400, 500])
    def test_send_various_response_codes(
        self, mock_logger, sample_ticker_data, mock_settings, status_code
    ):
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

            notifier = DiscordNotifier()
            notifier.send(sample_ticker_data)

            mock_logger.info.assert_any_call(
                "Discord response", status_code=status_code
            )

    @patch("hvcwatch.notification.logger")
    def test_send_with_different_ticker_data(
        self, mock_logger, mock_settings, mock_discord_webhook
    ):
        """✅ Test Discord notification with different ticker data."""
        mock_webhook_class, mock_embed_class, mock_webhook, mock_embed = (
            mock_discord_webhook
        )

        # Different ticker data
        ticker_data = TickerData(
            ticker="NVDA",
            name="NVIDIA Corporation",
            description="Graphics processors",
            type="CS",
            logo_url="https://static.stocktitan.net/company-logo/nvda.webp",
            close=495.50,
            volume=5_000_000,
            volume_sma=4_000_000.0,
            volume_ratio=1.25,
        )

        notifier = DiscordNotifier()
        notifier.send(ticker_data)

        # Verify embed was created with correct title
        mock_embed_class.assert_called_once()
        call_args = mock_embed_class.call_args[1]
        assert call_args["title"] == "NVIDIA Corporation (NVDA)"

        # Verify thumbnail was set with correct URL
        mock_embed.set_thumbnail.assert_called_once_with(
            url="https://static.stocktitan.net/company-logo/nvda.webp"
        )

        # Verify logging with correct ticker
        mock_logger.info.assert_any_call("Sending to Discord", ticker="NVDA")


class TestNotifyAllPlatforms:
    """Test notify_all_platforms orchestrator function."""

    @pytest.fixture
    def mock_ticker_functions(self):
        """Mock get_ticker_details and get_ticker_stats."""
        mock_details = {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "description": "Technology company",
            "type": "CS",
            "logo_url": "https://static.stocktitan.net/company-logo/aapl.webp",
        }

        mock_stats = {
            "close": 150.25,
            "volume": 2_500_000,
            "volume_sma": 2_000_000.0,
            "volume_ratio": 1.25,
        }

        with (
            patch("hvcwatch.notification.get_ticker_details") as mock_get_details,
            patch("hvcwatch.notification.get_ticker_stats") as mock_get_stats,
        ):
            mock_get_details.return_value = mock_details
            mock_get_stats.return_value = mock_stats
            yield mock_get_details, mock_get_stats

    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_success(
        self, mock_notifier_class, mock_logger, mock_ticker_functions
    ):
        """✅ Test successful notification to all platforms."""
        mock_get_details, mock_get_stats = mock_ticker_functions
        mock_notifier = Mock()
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("AAPL")

        # Verify ticker data was fetched
        mock_get_details.assert_called_once_with("AAPL")
        mock_get_stats.assert_called_once_with("AAPL")

        # Verify Discord notifier was created and called
        mock_notifier_class.assert_called_once()
        mock_notifier.send.assert_called_once()

        # Verify the TickerData passed to send() has correct fields
        call_args = mock_notifier.send.call_args[0]
        ticker_data = call_args[0]
        assert ticker_data.ticker == "AAPL"
        assert ticker_data.name == "Apple Inc."
        assert ticker_data.price == 150.25
        assert ticker_data.volume == 2_500_000

        # Verify logging
        mock_logger.info.assert_any_call(
            "Fetching ticker data for notifications", ticker="AAPL"
        )
        mock_logger.info.assert_any_call(
            "Ticker data fetched successfully", ticker="AAPL"
        )
        mock_logger.info.assert_any_call(
            "Notification sent successfully", ticker="AAPL", platform="Discord"
        )

    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.get_ticker_details")
    def test_notify_all_platforms_fetch_error(self, mock_get_details, mock_logger):
        """❌ Test error handling when fetching ticker data fails."""
        mock_get_details.side_effect = Exception("API error")

        notify_all_platforms("INVALID")

        # Verify error was logged
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args
        assert error_call[1]["ticker"] == "INVALID"
        assert "API error" in error_call[1]["error"]

    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    def test_notify_all_platforms_send_error(
        self, mock_notifier_class, mock_logger, mock_ticker_functions
    ):
        """❌ Test error handling when sending notification fails."""
        mock_notifier = Mock()
        mock_notifier.send.side_effect = Exception("Webhook error")
        mock_notifier_class.return_value = mock_notifier

        notify_all_platforms("AAPL")

        # Verify error was logged
        error_calls = [call for call in mock_logger.error.call_args_list]
        assert len(error_calls) == 1
        error_call = error_calls[0]
        assert error_call[1]["ticker"] == "AAPL"
        assert error_call[1]["platform"] == "Discord"
        assert "Webhook error" in error_call[1]["error"]

    @patch("hvcwatch.notification.logger")
    @patch("hvcwatch.notification.DiscordNotifier")
    @pytest.mark.parametrize("ticker", ["TSLA", "MSFT", "GOOGL", "AMZN"])
    def test_notify_all_platforms_various_tickers(
        self, mock_notifier_class, mock_logger, ticker
    ):
        """✅ Test notify_all_platforms with various ticker symbols."""
        mock_details = {
            "ticker": ticker,
            "name": f"{ticker} Corporation",
            "description": "Test company",
            "type": "CS",
            "logo_url": f"https://example.com/{ticker.lower()}.png",
        }

        mock_stats = {
            "close": 100.0,
            "volume": 1_000_000,
            "volume_sma": 900_000.0,
            "volume_ratio": 1.11,
        }

        with (
            patch("hvcwatch.notification.get_ticker_details") as mock_get_details,
            patch("hvcwatch.notification.get_ticker_stats") as mock_get_stats,
        ):
            mock_get_details.return_value = mock_details
            mock_get_stats.return_value = mock_stats

            mock_notifier = Mock()
            mock_notifier_class.return_value = mock_notifier

            notify_all_platforms(ticker)

            # Verify fetching with correct ticker
            mock_get_details.assert_called_once_with(ticker)
            mock_get_stats.assert_called_once_with(ticker)

            # Verify notification was sent
            mock_notifier.send.assert_called_once()

            # Verify logging mentions correct ticker
            mock_logger.info.assert_any_call(
                "Fetching ticker data for notifications", ticker=ticker
            )
